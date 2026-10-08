import asyncio
import threading
from types import SimpleNamespace

import httpx
from google.genai import types

from precedent.worker import runner
from precedent.worker.events import EventLog, read_events
from precedent.worker.failures import WriteGate
from precedent.worker.gateway import Gateway
from precedent.worker.guard import Guard


def _guard(tmp_path):
    log = EventLog("r1", root=tmp_path)
    return Guard(log, WriteGate(), threading.Lock(), tmp_path), log


def _types(log):
    return [e.type for e in read_events(log.path)]


TOOL = SimpleNamespace(name="browser_click")


def test_after_tool_leaves_our_own_refusal_alone(tmp_path):
    guard, log = _guard(tmp_path)
    assert guard.after_tool(TOOL, {}, None, {"error": "Stopped: budget"}) is None
    assert _types(log) == []


def test_after_tool_turns_an_mcp_error_into_advice(tmp_path):
    guard, log = _guard(tmp_path)
    result = guard.after_tool(TOOL, {}, None, {
        "content": [{"type": "text", "text": "### Error\nRef e9 not found in the page"}],
        "isError": True,
    })  # fmt: skip
    assert result["isError"] and "fresh snapshot" in result["content"][0]["text"]
    assert _types(log) == ["failure", "observation"]


def test_after_tool_handles_a_plain_string(tmp_path):
    guard, log = _guard(tmp_path)
    result = guard.after_tool(TOOL, {}, None, "### Page\n- Page URL: http://x/a\n- Page Title: A")
    assert "Page URL" in result["content"][0]["text"]
    assert read_events(log.path)[-1].data["title"] == "A"


def test_tool_exception_is_classified_not_fatal(tmp_path):
    guard, log = _guard(tmp_path)
    out = guard.on_tool_error(TOOL, {}, None, RuntimeError("Timeout 5000ms exceeded"))
    assert "failed" in out["error"] and _types(log) == ["failure"]


def _snapshot_part(i):
    text = f"### Page\n- Page URL: http://x/p{i}\n- Page Title: P{i}\n### Snapshot\n" + "x" * 500
    return types.Part(
        function_response=types.FunctionResponse(
            name="browser_navigate", response={"content": [{"type": "text", "text": text}]}
        )
    )


def test_old_snapshots_shrink_without_touching_the_session(tmp_path):
    guard, _ = _guard(tmp_path)
    session_parts = [_snapshot_part(i) for i in range(5)]
    request = SimpleNamespace(contents=[
        types.Content(role="user", parts=[p.model_copy()]) for p in session_parts
    ])  # fmt: skip
    guard.before_model(None, request)
    texts = [c.parts[0].function_response.response["content"][0]["text"] for c in request.contents]
    assert texts[0].startswith("[older page snapshot omitted") and "http://x/p0" in texts[0]
    assert texts[-1].startswith("### Page")  # the newest three stay whole
    original = session_parts[0].function_response.response["content"][0]["text"]
    assert original.startswith("### Page")  # the session's copy is unchanged
    guard.before_model(None, request)  # a second pass changes nothing
    again = request.contents[0].parts[0].function_response.response["content"][0]["text"]
    assert again == texts[0]


def test_run_finished_is_written_even_when_setup_fails(tmp_path, monkeypatch, live_apps):
    def broken(*args, **kwargs):
        raise FileNotFoundError("Chromium not found")

    monkeypatch.setattr(runner, "browser_toolset", broken)
    cfg = runner.RunConfig(request="x", apps_url=live_apps[0], runs_root=tmp_path)
    summary = asyncio.run(runner.run(cfg))
    events = read_events(tmp_path / summary["run_id"] / "events.jsonl")
    assert events[-1].type == "run_finished"
    assert events[-1].data["outcome"] == "unknown" and "Chromium" in events[-1].data["error"]


class _Model:
    def __init__(self, name, ok):
        self.name, self.ok = name, ok

    async def generate_content_async(self, request):
        if not self.ok:
            raise RuntimeError(f"503 from {self.name}")
        yield f"answer from {self.name}"


def test_fallback_skips_the_model_that_just_failed(tmp_path, monkeypatch):
    tried = []

    def fake_model(name):
        tried.append(name)
        return _Model(name, ok=(name == "c"))

    monkeypatch.setattr(runner, "make_model", fake_model)
    log = EventLog("r1", root=tmp_path)
    fb = runner.Fallback("a", ["b", "c"], log)
    fb.agent = SimpleNamespace(model=None)
    request = SimpleNamespace(model="a")
    answer = asyncio.run(fb(None, request, RuntimeError("503 from a")))
    assert answer == "answer from c" and tried == ["b", "c"]
    assert fb.agent.model.name == "c"  # it stays on the model that answered


def test_browser_auto_requests_do_not_unlock_an_uncertain_write(live_apps):
    base, _ = live_apps
    gate = WriteGate(locked=True, uncertain=1)
    gw = Gateway(base, gate)
    gw.start()
    httpx.get(f"{gw.url}/favicon.ico")
    assert not gate.searched
    for path in (
        "/static/fonts/SourceSans3-Regular.otf",
        "/drive/f/f-1/preview/1.png",
        "/drive/f/f-1/download",
        "/work-status",
    ):
        httpx.get(gw.url + path)
        assert not gate.searched
    httpx.get(f"{gw.url}/books/bills?q=FIG-1842")
    assert gate.searched
    gw.stop()


def test_goal_preparation_timeout_cancels_model_and_records_terminal_run(
    tmp_path, monkeypatch, live_apps
):
    cancelled = []

    async def never_returns(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(runner, "write_goal", never_returns)
    monkeypatch.setattr(runner, "make_model", lambda name: object())
    result = asyncio.run(
        runner.run(
            runner.RunConfig(
                request="Do not change company data",
                apps_url=live_apps[0],
                runs_root=tmp_path,
                goal_timeout=0.03,
            )
        )
    )
    events = read_events(tmp_path / result["run_id"] / "events.jsonl")
    assert cancelled == [True]
    assert "Goal preparation timed out" in result["error"]
    assert events[-1].type == "run_finished"
    assert not any(e.type in ("goal_contract", "action", "observation") for e in events)
    assert any(e.type == "note" and e.data.get("phase") == "goal" for e in events)


def test_fallback_records_failure_and_retry_before_waiting_for_response(tmp_path, monkeypatch):
    log = EventLog("r1", root=tmp_path)

    class InspectingModel:
        async def generate_content_async(self, request):
            events = read_events(log.path)
            assert events[-1].data["kind"] == "model_wait"
            assert events[-1].data["model"] == "backup"
            assert "503" in events[-2].data["detail"]
            yield "answer"

    monkeypatch.setattr(runner, "make_model", lambda name: InspectingModel())
    response = asyncio.run(
        runner.Fallback("primary", ["backup"], log)(
            None, SimpleNamespace(model="primary"), RuntimeError("503 high demand")
        )
    )
    assert response == "answer"
