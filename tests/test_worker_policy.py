from precedent.contracts import FailureKind
from precedent.worker.events import EventLog, read_events, task_id_for, unfinished_run
from precedent.worker.failures import WriteGate, classify_response, classify_tool_error


def test_classify_responses():
    assert classify_response("GET", 200) is None
    assert classify_response("GET", 503) is FailureKind.tool
    assert classify_response("GET", None, timed_out=True) is FailureKind.tool
    assert classify_response("POST", 303) is None
    assert classify_response("POST", 502) is FailureKind.uncertain_write
    assert classify_response("POST", None, timed_out=True) is FailureKind.uncertain_write
    assert classify_response("POST", 400) is FailureKind.interface
    assert classify_response("POST", 409) is FailureKind.interface
    assert classify_tool_error("Ref e14 not found in the current page") is FailureKind.interface
    assert classify_tool_error("Timeout 5000ms exceeded") is FailureKind.tool


def test_write_needs_a_decision_with_sources():
    gate = WriteGate()
    assert gate.on_request("POST") is not None  # no decision yet
    assert "source" in gate.on_decision([])
    assert gate.on_request("POST") is not None
    gate.on_decision(["mail:m-0032"])
    assert gate.on_request("POST") is None
    gate.on_response("POST", "/x", 303)
    assert gate.on_request("POST") is not None  # one decision, one save


def test_rejected_form_keeps_the_decision():
    gate = WriteGate()
    gate.on_decision(["s"])
    gate.on_request("POST")
    assert gate.on_response("POST", "/x", 400) is FailureKind.interface
    assert gate.on_request("POST") is None  # nothing was written; fixing the form is allowed


def test_uncertain_write_locks_until_search_and_new_decision():
    gate = WriteGate()
    gate.on_decision(["s"])
    gate.on_request("POST")
    assert gate.on_response("POST", "/bills/new", 502) is FailureKind.uncertain_write
    assert gate.on_request("POST") is not None
    assert "Search" in gate.on_decision(["s"])  # deciding again without searching is refused
    assert gate.on_request("GET") is None  # the search
    gate.on_decision(["books:search FIG-1842: absent"])
    assert gate.on_request("POST") is None  # one retry
    gate.on_response("POST", "/bills/new", 502)
    assert gate.fatal
    gate.on_request("GET")
    gate.on_decision(["s"])
    assert "stopped" in gate.on_request("POST")


def test_event_log_appends_valid_events(tmp_path):
    log = EventLog("r1", task_id="t-1", root=tmp_path)
    log.emit("run_started", request="x", worker="precedent", seed=7, model="m")
    log.emit("note", text="hello")
    events = read_events(tmp_path / "r1" / "events.jsonl")
    assert [(e.seq, e.type) for e in events] == [(1, "run_started"), (2, "note")]
    assert unfinished_run("t-1", tmp_path) == tmp_path / "r1"
    log.emit("run_finished", outcome="unknown", tokens_in=0, tokens_out=0, usd=None, seconds=1)
    assert unfinished_run("t-1", tmp_path) is None
    again = EventLog("r1", task_id="t-1", root=tmp_path)  # reopening continues the sequence
    assert again.emit("note", text="x").seq == 4


def test_task_id_ignores_case_and_spacing():
    assert task_id_for(7, "Enter  the invoice") == task_id_for(7, "enter the invoice")
    assert task_id_for(7, "x") != task_id_for(8, "x")
