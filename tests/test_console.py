import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from precedent.console.server import RunManager, create_app
from precedent.console.state import reconstruct, safe_child
from precedent.worker.events import EventLog, read_events
from precedent.worker.questions import FileHuman
from precedent.worker.runner import ObservedBrowser, _close


def started(log):
    log.emit(
        "run_started", request="Review an invoice", seed=8, worker="precedent", model="scripted"
    )


def test_reconstruction_never_treats_a_claim_or_save_as_verification(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    log.emit(
        "goal_contract",
        outcome="Routed",
        conditions=[{"id": "c1", "kind": "must_be_true", "text": "Approval requested"}],
    )
    log.emit("note", kind="app_effect", method="POST", path="/books/bills/INV-1", status=303)
    log.emit("run_finished", outcome="unknown", claimed="pass", usd=None)
    state = reconstruct(read_events(log.path))
    assert state["conditions"][0]["state"] == "Pending"
    assert state["status"] == "Finished · unknown" and len(state["effects"]) == 1
    log.emit("check", condition_id="c1", text="Approval requested", result="unknown")
    assert reconstruct(read_events(log.path))["conditions"][0]["state"] == "Unknown"
    log.emit(
        "check", condition_id="c1", text="Approval requested", result="pass", evidence="Fresh page"
    )
    assert reconstruct(read_events(log.path))["conditions"][0]["state"] == "Verified"


def test_capacity_and_abandoned_runs_are_distinct(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    assert reconstruct(read_events(log.path))["status"] == "Interrupted"
    assert reconstruct(read_events(log.path), active=True)["status"] == "Working"
    log.emit("run_finished", outcome="unknown", error="429 quota exhausted")
    assert reconstruct(read_events(log.path))["status"] == "Interrupted · model capacity"


def test_replay_reload_sse_and_cross_run_capture_safety(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    shot = log.dir / "shots" / "view-1.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (log.dir / "shots" / "unreferenced.png").write_bytes(shot.read_bytes())
    log.emit(
        "observation", url="http://company/books", title="Books", screenshot="shots/view-1.png"
    )
    log.emit("run_finished", outcome="unknown")
    client = TestClient(create_app(tmp_path))
    first = client.get("/runs/r1/state").json()
    assert first == client.get("/runs/r1/state").json()
    assert first["mode"] == "Replay" and first["capture"]["href"].endswith("view-1.png")
    assert client.get("/runs/r1/shots/view-1.png").content == shot.read_bytes()
    assert client.get("/runs/r1/shots/unreferenced.png").status_code == 404
    other = EventLog("r2", root=tmp_path)
    started(other)
    assert client.get("/runs/r2/shots/view-1.png").status_code == 404
    outside = tmp_path / "outside.png"
    outside.write_bytes(shot.read_bytes())
    (log.dir / "shots" / "symlink.png").symlink_to(outside)
    log.emit("observation", screenshot="shots/symlink.png")
    assert client.get("/runs/r1/shots/symlink.png").status_code == 404
    assert client.get("/runs/%2e%2e/state").status_code == 404
    assert "event: state" in client.get("/runs/r1/events").text
    assert client.get("/runs/r1").status_code == 200


def test_foreign_events_do_not_authorize_captures(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    log.emit("observation", screenshot="shots/view-1.png")
    (log.dir / "shots" / "view-1.png").write_bytes(b"image")
    other = EventLog("r2", root=tmp_path)
    other.path.write_text(log.path.read_text())
    client = TestClient(create_app(tmp_path))
    assert client.get("/runs/r2/shots/view-1.png").status_code == 404


def test_run_specific_question_answers_and_duplicates(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    q = log.emit("question", text="Which account?", options=["A", "B"], question_id="q2")
    (log.dir / "launch.json").write_text(
        json.dumps({"request": "x", "seed": 8, "human_answers": True})
    )
    app = create_app(tmp_path)
    app.state.manager.processes["r1"] = SimpleNamespace(poll=lambda: None)
    client = TestClient(app)
    assert client.get("/runs/r1/state").json()["can_answer"]
    assert (
        client.post("/runs/r1/answer", data={"question_id": "q99", "answer": "A"}).status_code
        == 400
    )
    response = client.post(
        "/runs/r1/answer", data={"question_id": "q2", "answer": "B"}, follow_redirects=False
    )
    assert response.status_code == 303
    answer = asyncio.run(FileHuman(log, timeout=1)(q.data["text"], q.data["options"]))
    assert answer == {"text": "B", "by": "human"}
    assert (
        client.post("/runs/r1/answer", data={"question_id": "q2", "answer": "A"}).status_code == 409
    )
    log.emit("answer", question_id="q2", **answer)
    assert client.get("/runs/r1/state").json()["question"] is None
    app.state.manager.processes["r1"] = SimpleNamespace(poll=lambda: 0)
    assert (
        client.post("/runs/r1/answer", data={"question_id": "q2", "answer": "A"}).status_code == 409
    )


def test_question_timeout_is_a_system_answer(tmp_path):
    log = EventLog("r1", root=tmp_path)
    log.emit("question", text="Choice", options=[], question_id="q1")
    answer = asyncio.run(FileHuman(log, timeout=0)("Choice", []))
    assert answer["by"] == "system" and "blocked" in answer["text"]


def test_start_binds_seed_environment_and_single_concurrency(tmp_path):
    calls = []
    process = SimpleNamespace(poll=lambda: None)

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return process

    manager = RunManager(tmp_path, "http://company:8100", launcher=launch)

    async def company():
        return {"seed": 8, "name": "Alternate Company"}

    manager.company = company
    with pytest.raises(Exception, match="server changed"):
        asyncio.run(manager.start("x", 7))
    run_id = asyncio.run(manager.start("Review invoice", 8))
    assert calls[0][1]["env"]["PRECEDENT_APPS_URL"] == "http://company:8100"
    assert calls[0][1]["env"]["PRECEDENT_RUN_ID"] == run_id
    assert "--seed" in calls[0][0] and "8" in calls[0][0]
    assert calls[0][1]["start_new_session"]
    with pytest.raises(Exception, match="already working"):
        asyncio.run(manager.start("second", 8))


def test_post_refuses_cross_origin_and_validates_request(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert (
        client.post(
            "/runs", data={"request": "x", "seed": 7}, headers={"Origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    assert client.post("/runs", data={"request": "", "seed": 7}).status_code == 400
    assert client.post("/runs", data={"request": "x", "seed": "bad"}).status_code == 400


def test_partial_event_append_is_ignored_but_malformed_complete_event_is_not(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    original = log.path.read_text()
    log.path.write_text(original + '{"unfinished":')
    assert len(read_events(log.path)) == 1
    log.path.write_text(original + '{"unfinished":\n')
    with pytest.raises(ValueError):
        read_events(log.path)


def test_capture_uses_hidden_tool_and_moves_only_a_bounded_png(tmp_path):
    log = EventLog("r1", root=tmp_path)
    (log.dir / "mcp").mkdir()

    async def capture(**kwargs):
        Path(kwargs["args"]["filename"]).write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return {"isError": False}

    browser = object.__new__(ObservedBrowser)
    browser.screenshot_tool = SimpleNamespace(run_async=capture)
    result = asyncio.run(browser.capture(log))
    assert result["screenshot"].startswith("shots/")
    assert (log.dir / result["screenshot"]).exists()
    assert list((log.dir / "mcp").iterdir()) == []

    async def broken(**kwargs):
        raise RuntimeError("capture failed")

    browser.screenshot_tool = SimpleNamespace(run_async=broken)
    assert asyncio.run(browser.capture(log)) is None
    assert read_events(log.path)[-1].data["kind"] == "capture_unavailable"


def test_cleanup_always_stops_gateway_even_if_browser_close_fails(tmp_path):
    log = EventLog("r1", root=tmp_path)
    stopped = []

    async def close():
        raise RuntimeError("browser close failed")

    asyncio.run(
        _close(SimpleNamespace(close=close), SimpleNamespace(stop=lambda: stopped.append(1)), log)
    )
    assert stopped == [1]


def test_run_directory_symlinks_are_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError):
        safe_child(tmp_path, "alias")


def test_receipt_unknown_checks_and_unverified_success_claim(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    log.emit("goal_contract", conditions=[{"id": "c1", "text": "Done", "kind": "must_be_true"}])
    log.emit(
        "receipt",
        outcome="unknown",
        checks=[{"condition_id": "c1", "text": "Done", "result": "unknown"}],
    )
    log.emit("run_finished", outcome="pass", claimed="pass")
    state = reconstruct(read_events(log.path))
    assert state["conditions"][0]["state"] == "Unknown"
    assert (
        state["status"] == "Finished · unverified claim" and state["display_outcome"] == "unknown"
    )


def test_manager_shutdown_terminates_process_group_and_reaps(tmp_path, monkeypatch):
    import signal
    import subprocess

    calls = []
    waits = []

    def wait(timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired("scripted", timeout)

    process = SimpleNamespace(pid=777, poll=lambda: None, wait=wait)
    manager = RunManager(tmp_path, "http://company")
    manager.processes["r1"] = process
    monkeypatch.setattr(
        "precedent.console.server.os.killpg", lambda pid, sig: calls.append((pid, sig))
    )
    manager.close()
    assert calls == [(777, signal.SIGTERM), (777, signal.SIGKILL)] and waits == [5, 5]


def test_model_wait_is_distinct_from_work_and_timeout_explains_no_actions(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    log.emit("note", kind="model_wait", phase="goal", model="scripted", timeout_seconds=120)
    waiting = reconstruct(read_events(log.path), active=True)
    assert waiting["status"] == "Waiting for model"
    assert waiting["wait"]["phase"] == "goal"
    log.emit(
        "run_finished", outcome="unknown", error="Goal preparation timed out after 120 seconds"
    )
    stopped = reconstruct(read_events(log.path))
    assert stopped["status"] == "Stopped · model timeout"
    assert stopped["wait"] is None
    assert "No browser work began" in stopped["notice"]["text"]


def test_recorded_view_uses_evidence_available_at_that_observation(tmp_path):
    log = EventLog("r1", root=tmp_path)
    started(log)
    first = log.emit("observation", screenshot="shots/one.png", title="First")
    log.emit("decision_record", decided="Later decision", sources=["mail:m-1"])
    second = log.emit("observation", screenshot="shots/two.png", title="Second")
    log.emit("run_finished", outcome="unknown")
    client = TestClient(create_app(tmp_path))
    early = client.get(f"/runs/r1/state?at={first.seq}").json()
    late = client.get(f"/runs/r1/state?at={second.seq}").json()
    assert early["decisions"] == [] and len(late["decisions"]) == 1
    assert len(early["captures"]) == 2
    assert early["finished"] is None and not early["can_answer"]
    assert early["status"] == "Recorded step"
    assert client.get("/runs/r1/state?at=999").status_code == 400
    assert client.get("/runs/r1/state").json()["finished"]["outcome"] == "unknown"
