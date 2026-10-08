"""Phase 1 fixes from the failed run 20261008-114021-d140: keep the loop on track."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from precedent.apps.server import create_app
from precedent.worker import runner
from precedent.worker.compact import compact_snapshot
from precedent.worker.events import EventLog, read_events
from precedent.worker.failures import WriteGate
from precedent.worker.guard import Guard, exact_options
from precedent.world.generator import generate

FIX = Path(__file__).parent / "fixtures" / "snapshots"
SELECT = SimpleNamespace(name="browser_select_option")
NAV = SimpleNamespace(name="browser_navigate")


def _guard(tmp_path):
    log = EventLog("r1", root=tmp_path)
    return Guard(log, WriteGate(), threading.Lock(), tmp_path), log


def _page(url):
    return {"content": [{"type": "text", "text": f"### Page\n- Page URL: {url}\n- Page Title: T"}]}


def test_exact_options_come_from_the_last_snapshot():
    snapshot = compact_snapshot((FIX / "bill_new.txt").read_text())
    advice = exact_options(snapshot, "e68")
    assert "FIG-1842.pdf (Mail attachments)" in advice
    assert "fresh snapshot" in exact_options(snapshot, "e999")


def test_a_failed_select_is_answered_with_the_exact_options(tmp_path):
    guard, _ = _guard(tmp_path)
    guard.last_snapshot = compact_snapshot((FIX / "bill_new.txt").read_text())
    error = {"content": [{"type": "text", "text": "### Error\nTimeout 4000ms exceeded."}],
             "isError": True}  # fmt: skip
    out = guard.after_tool(SELECT, {"target": "e68", "values": ["FIG-1842.pdf"]}, None, error)
    assert "FIG-1842.pdf (Mail attachments)" in out["content"][0]["text"]


def test_remembered_facts_plan_pages_and_budget_are_in_the_run_state(tmp_path):
    guard, log = _guard(tmp_path)
    guard.update_plan(["Read the invoice email and its PDF | amount and due date",
                       "Enter the bill in Books | one draft bill"])  # fmt: skip
    guard.remember("amount INR 1,12,000", "FIG-1842.pdf")
    guard.after_tool(NAV, {}, None, _page("http://g/mail/m/m-0032"))
    state = guard.run_state()
    assert "amount INR 1,12,000 (from FIG-1842.pdf)" in state
    assert "s1 [todo] Read the invoice email" in state
    assert "http://g/mail/m/m-0032 (opened 1x)" in state
    assert "Budget used: steps 0/60" in state
    assert [e.data.get("kind") for e in read_events(log.path) if e.type == "note"] == ["fact"]


def test_the_run_state_is_added_to_each_model_call(tmp_path):
    guard, _ = _guard(tmp_path)
    request = SimpleNamespace(contents=[], config=SimpleNamespace(system_instruction="Base."))
    guard.before_model(None, request)
    assert request.config.system_instruction.startswith("Base.")
    assert "[Run state, written by the system]" in request.config.system_instruction


def test_reopening_a_page_and_reading_in_circles_earn_nudges(tmp_path):
    guard, _ = _guard(tmp_path)
    texts = [guard.after_tool(NAV, {}, None, _page("http://g/chat/general"))["content"][0]["text"]
             for _ in range(3)]  # fmt: skip
    assert "opened this page three times" in texts[2] and "three times" not in texts[1]
    for i in range(9):
        last = guard.after_tool(NAV, {}, None, _page(f"http://g/p{i}"))["content"][0]["text"]
    assert "12 browser steps without a decision or save" in last
    guard.record_decision("o", "m", "d", ["s"])
    assert guard.since_progress == 0


def test_a_placeholder_plan_is_refused(tmp_path):
    guard, log = _guard(tmp_path)
    assert "error" in guard.update_plan(["plan-step-1 | see test"], reason="testing")
    assert read_events(log.path) == []


def test_form_filling_tool_is_offered_to_the_model():
    assert "browser_fill_form" in runner.BROWSER_TOOLS


def test_the_apps_hide_console_links_and_state_from_the_worker(tmp_path):
    generate("northwind", 7, tmp_path / "7")
    client = TestClient(create_app(7, tmp_path))
    agent = {"X-Precedent-Agent": "ava"}
    assert "Ava’s tasks" in client.get("/books/bills").text
    assert "Ava’s tasks" not in client.get("/books/bills", headers=agent).text
    assert client.get("/work-status", headers=agent).status_code == 404


def test_budget_text_reflects_time_used(tmp_path):
    guard, _ = _guard(tmp_path)
    guard.started = time.monotonic() - 30
    assert "seconds 30/1200" in guard.run_state() or "seconds 29/1200" in guard.run_state()


def test_ref_wrappers_are_removed_before_the_tool_runs(tmp_path):
    guard, log = _guard(tmp_path)
    args = {"target": "[ref=f8e73]", "text": "FIG-1842"}
    guard.before_tool(SimpleNamespace(name="browser_type"), args, None)
    assert args["target"] == "f8e73"
    form = {
        "fields": [{"target": "ref=f8e62", "value": "x"}, {"target": "#f-amount", "value": "1"}]
    }
    guard.before_tool(SimpleNamespace(name="browser_fill_form"), form, None)
    assert [f["target"] for f in form["fields"]] == ["f8e62", "#f-amount"]


def test_an_unmatched_target_gets_specific_advice(tmp_path):
    guard, _ = _guard(tmp_path)
    error = {"content": [{"type": "text", "text": 'Error: "#f-x" does not match any elements.'}],
             "isError": True}  # fmt: skip
    out = guard.after_tool(SimpleNamespace(name="browser_type"), {}, None, error)
    assert "bare id" in out["content"][0]["text"]


def test_thinking_follows_the_situation(tmp_path):
    guard, _ = _guard(tmp_path)
    assert guard.thinking_level() == ("HIGH", "writing the plan")
    guard.update_plan(["Read the invoice and its PDF | the facts", "Enter the bill | a draft"])
    assert guard.thinking_level()[0] == "LOW"
    guard.last_snapshot = compact_snapshot((FIX / "bill_new.txt").read_text())
    assert guard.thinking_level() == ("MEDIUM", "a form is on the page")
    guard.last_snapshot = ""
    guard.record_decision("o", "m", "d", ["s"])
    guard.before_tool(SimpleNamespace(name="record_decision"), {}, None)
    assert guard.thinking_level()[0] == "MEDIUM"
    guard.last_tool = "browser_navigate"
    guard.attention = "high:a save had an unknown result"
    assert guard.thinking_level() == ("HIGH", "a save had an unknown result")
    assert guard.thinking_level()[0] == "LOW"  # attention is used once
