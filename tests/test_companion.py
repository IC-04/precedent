"""Ava's companion: truthful poses, bounded context, a narrow draft handoff, one Ava."""

import json
import re

import httpx
from fastapi.testclient import TestClient

from precedent import companion
from precedent.console.server import create_app
from precedent.worker.events import EventLog


def live(**state):
    return {"mode": "Live updates", "finished": None, "phase": "execute", **state}


def test_poses_follow_recorded_state_and_never_celebrate_an_unknown():
    pose = lambda s: companion.pose_for(s)["pose"]  # noqa: E731
    assert pose({"mode": "Replay", "finished": {"outcome": "pass"}, "display_outcome": "pass"}) == (
        "deliver"
    )
    # A pass claimed by the worker but not freshly verified is shown as unknown: no delivery.
    claimed = {"mode": "Replay", "finished": {"outcome": "pass"}, "display_outcome": "unknown"}
    assert pose(claimed) == "idle"
    assert "remain open" in companion.pose_for(claimed)["line"]
    assert pose({"mode": "Replay", "finished": {"error": "boom"}, "notice": {"t": 1}}) == "away"
    assert pose({"mode": "Replay", "finished": None}) == "away"  # stopped without a receipt
    assert pose(live(question={"question_id": "q1"})) == "ask"
    assert pose(live(question={"question_id": "q1"}, answer_submitted=True)) == "listen"
    assert pose(live(phase="verify")) == "check"
    assert pose(live(phase="prepare", wait={"phase": "goal"})) == "think"
    assert pose(live(phase="prepare")) == "read"
    acting = live(
        history=[
            {"type": "action", "seq": 9, "data": {"tool": "browser_type", "caption": "Typing"}}
        ],
        observation={"seq": 8},
    )
    assert companion.pose_for(acting) == {"pose": "work", "line": "Typing"}
    reading = live(history=[{"type": "action", "seq": 9, "data": {"tool": "browser_snapshot"}}])
    assert pose(reading) == "read"
    # After the action's observation the system is choosing its next step, not "working".
    observed = live(history=[{"type": "action", "seq": 9, "data": {}}], observation={"seq": 10})
    assert companion.pose_for(observed) == {"pose": "think", "line": "Choosing the next step"}


def test_context_is_bounded_visible_identity_only():
    assert companion.clean_context({"surface": "evil"}) is None
    assert companion.clean_context("x") is None
    context = companion.clean_context(
        {
            "surface": "books",
            "kind": "bill",
            "id": "INV-1/../../x",
            "label": "A" * 500,
            "vendor": " Figma\n ",
            "secret": "drop me",
            "attachment": "yes",
        }
    )
    assert context == {"surface": "books", "label": "A" * 140, "vendor": "Figma"}
    assert companion.clean_context({"surface": "drive", "kind": "file", "id": "f-0004"}) == {
        "surface": "drive",
        "kind": "file",
        "id": "f-0004",
    }


def test_script_json_cannot_close_its_script_element():
    rendered = companion.dock(
        "mail", "http://c", status_url="/s", handoff="apps", context={"label": "</script><b>"}
    )
    config = re.search(r'id="ava-config">(.*?)</script>', rendered).group(1)
    assert "</script>" not in config
    assert json.loads(config)["context"]["label"] == "</script><b>"


def test_company_pages_mount_one_ava_for_people_and_none_for_the_worker(live_apps):
    base, _ = live_apps
    page = httpx.get(base + "/mail/m/m-0032").text
    assert page.count("data-ava-dock") == 1 and page.count('class="ava-art"') == 1
    config = json.loads(re.search(r'id="ava-config">(.*?)</script>', page).group(1))
    assert config["context"]["kind"] == "message"
    assert config["context"]["vendor"] == "Figma"  # the visible sender address matches a vendor
    agent = httpx.get(base + "/mail/m/m-0032", headers={"X-Precedent-Agent": "ava"}).text
    assert "ava-config" not in agent and "companion.js" not in agent and "ava-art" not in agent
    for path in ["/", "/books/bills", "/books/bills/new", "/drive/", "/chat/general"]:
        assert httpx.get(base + path).text.count("data-ava-dock") == 1, path


def test_handoff_is_same_origin_one_time_and_never_for_the_worker(live_apps):
    base, conn = live_apps
    draft = {"text": "Find the latest invoice from Figma.", "context": {"surface": "mail"}}
    assert (
        httpx.post(
            base + "/ava/handoff", json=draft, headers={"X-Precedent-Agent": "ava"}
        ).status_code
        == 403
    )
    assert (
        httpx.post(
            base + "/ava/handoff", json=draft, headers={"Origin": "http://evil.test"}
        ).status_code
        == 403
    )
    assert (
        httpx.post(
            base + "/ava/handoff", json=draft, headers={"Sec-Fetch-Site": "same-site"}
        ).status_code
        == 403
    )
    assert httpx.post(base + "/ava/handoff", json={"text": "x" * 2001}).status_code == 400
    audit = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    token = httpx.post(base + "/ava/handoff", json=draft, headers={"Origin": base}).json()["token"]
    assert (
        httpx.get(f"{base}/ava/handoff/{token}", headers={"X-Precedent-Agent": "ava"}).status_code
        == 404
    )
    entry = httpx.get(f"{base}/ava/handoff/{token}").json()
    assert entry["text"] == draft["text"] and entry["instance_id"]
    assert httpx.get(f"{base}/ava/handoff/{token}").status_code == 404  # used once
    assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == audit  # no record writes


def test_compose_prefills_from_the_bound_company_and_starts_nothing(live_apps, tmp_path):
    base, _ = live_apps
    launched = []
    runs = tmp_path / "runs"
    client = TestClient(create_app(runs, base, launcher=lambda *a, **k: launched.append(a)))
    token = httpx.post(
        base + "/ava/handoff",
        json={
            "text": "Check FIG-1842 <b>",
            "context": {"surface": "drive", "label": "FIG-1842.pdf"},
        },
    ).json()["token"]
    page = client.get("/compose", params={"handoff": token}).text
    assert "Check FIG-1842 &lt;b&gt;</textarea>" in page
    assert "Drafted with Ava from Drive · FIG-1842.pdf" in page and "Nothing has started" in page
    again = client.get("/compose", params={"handoff": token}).text
    assert "already opened or has expired" in again
    assert "not valid" in client.get("/compose", params={"handoff": "../x"}).text
    assert not launched and not runs.exists()


def test_compose_refuses_a_draft_from_another_company(live_apps, tmp_path, monkeypatch):
    base, _ = live_apps
    token = httpx.post(base + "/ava/handoff", json={"text": "Do it"}).json()["token"]
    app = create_app(tmp_path, base)
    real = app.state.manager.company

    async def other_company():
        return {**await real(), "instance_id": "another-company"}

    monkeypatch.setattr(app.state.manager, "company", other_company)
    page = TestClient(app).get("/compose", params={"handoff": token}).text
    assert "different company" in page and "Do it</textarea>" not in page


def test_workspace_status_binds_runs_to_the_company_instance(tmp_path):
    for run, instance in [("r-a", "company-a"), ("r-b", "company-b")]:
        log = EventLog(run, root=tmp_path)
        log.emit("run_started", request=f"Task {run}", seed=7, worker="precedent", model="x")
        log.emit("run_finished", outcome="unknown")
        launch = {"request": "x", "seed": 7, "company": {"seed": 7, "instance_id": instance}}
        (log.dir / "launch.json").write_text(json.dumps(launch))
    client = TestClient(create_app(tmp_path))
    status = client.get("/workspace-status", params={"seed": 7, "instance_id": "company-a"}).json()
    assert status["run"]["run_id"] == "r-a" and status["run"]["active"] is False
    assert status["run"]["companion"]["pose"] == "idle"
    unknown = client.get("/workspace-status", params={"seed": 7, "instance_id": "fresh"}).json()
    assert unknown["run"] is None


def test_console_pages_have_exactly_one_ava(tmp_path):
    log = EventLog("r1", root=tmp_path)
    log.emit("run_started", request="Invoice", seed=7, worker="precedent", model="x")
    client = TestClient(create_app(tmp_path))
    for path in ["/", "/guide", "/runs/r1"]:
        page = client.get(path).text
        assert page.count('class="ava-art"') == 1, path
        assert page.count('id="ava-config"') == 1, path
    run = client.get("/runs/r1/state").json()
    assert run["companion"] == {"pose": "away", "line": "This session stopped without a result"}
