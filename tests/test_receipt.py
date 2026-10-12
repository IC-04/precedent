from precedent.worker.events import EventLog, read_events, unfinished_run
from precedent.worker.receipt import write_receipt


def test_receipt_reports_actual_partial_verification(tmp_path):
    log = EventLog("demo", root=tmp_path)
    log.emit(
        "goal_contract",
        conditions=[
            {"id": "invoice", "kind": "must_be_true", "text": "Invoice saved"},
            {"id": "safe", "kind": "must_not", "text": "Other records changed"},
        ],
    )
    log.emit(
        "check",
        condition_id="invoice",
        text="Invoice saved",
        result="pass",
        evidence="Fresh bill page",
    )
    receipt = write_receipt(
        log, "Save invoice", {"claimed": "pass", "summary": "Saved"}, {"outcome": "unknown"}
    )
    assert receipt.outcome == "unknown"
    assert receipt.pending == ["Check unresolved: Other records changed"]
    assert "1 of 2" in receipt.summary
    assert "not implemented" not in (log.dir / "receipt.md").read_text()


def test_receipt_pass_requires_checks_and_verified_run(tmp_path):
    log = EventLog("demo", root=tmp_path)
    log.emit(
        "goal_contract",
        conditions=[{"id": "invoice", "kind": "must_be_true", "text": "Invoice saved"}],
    )
    claimed = {"claimed": "pass", "summary": "Saved"}
    assert write_receipt(log, "Save invoice", claimed, {"outcome": "pass"}).outcome == "unknown"
    log.emit(
        "check",
        condition_id="invoice",
        text="Invoice saved",
        result="pass",
        evidence="Fresh bill page",
    )
    assert write_receipt(log, "Save invoice", claimed, {"outcome": "unknown"}).outcome == "unknown"
    receipt = write_receipt(log, "Save invoice", claimed, {"outcome": "pass"})
    assert receipt.outcome == "pass" and not receipt.pending
    assert "Outcome: pass" in (log.dir / "receipt.md").read_text()


def test_recheck_replaces_receipt_evidence_without_erasing_history(tmp_path):
    log = EventLog("demo", task_id="task", root=tmp_path)
    log.emit("run_started", request="Check amount")
    log.emit(
        "goal_contract",
        conditions=[{"id": "c1", "kind": "must_be_true", "text": "Amount correct"}],
    )
    log.emit("check", condition_id="c1", text="Amount correct", result="fail")
    log.emit("run_finished", outcome="fail")
    log.emit("note", kind="correction", text="Fixed comparison; reread the app")
    log.emit("check", condition_id="c1", text="Amount correct", result="pass")
    receipt = write_receipt(log, "Check amount", None, {"outcome": "pass"})
    assert receipt.outcome == "pass" and len(receipt.checks) == 1
    assert [e.data["result"] for e in read_events(log.path) if e.type == "check"] == [
        "fail",
        "pass",
    ]
    assert unfinished_run("task", tmp_path) is None
