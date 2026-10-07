import json
from datetime import UTC, datetime, timedelta

import pytest

from precedent.grader.grade import grade
from precedent.world import db
from precedent.world.generator import generate


def _ts(minutes: int) -> str:
    return (datetime(2026, 10, 7, 10, 0, tzinfo=UTC) + timedelta(minutes=minutes)).isoformat(
        timespec="seconds"
    )


@pytest.fixture()
def world(tmp_path):
    generate("northwind", 7, tmp_path / "worlds" / "7")
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    events = [
        {"run_id": "r1", "seq": 1, "ts": _ts(0), "type": "run_started", "data": {}},
        {"run_id": "r1", "seq": 2, "ts": _ts(30), "type": "run_finished", "data": {}},
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    conn = db.connect(tmp_path / "worlds" / "7" / "world.db")
    yield tmp_path, conn
    conn.close()


def _hidden(tmp_path, task_id):
    truth = json.loads((tmp_path / "worlds" / "7" / "hidden.json").read_text())
    return next(t for t in truth["tasks"] if t["task_id"] == task_id)


def _enter_t1(conn, exp, *, account=None, route=True, bill_id="INV-921", minute=5):
    bill = {
        "id": bill_id, "vendor_id": exp["vendor_id"], "invoice_no": exp["invoice_no"],
        "amount_minor": exp["amount_minor"], "currency": "INR", "issue_date": "2026-09-28",
        "due_date": exp["due_date"], "account_code": account or exp["account"],
        "approver_id": None, "status": "draft", "attachment_file_id": exp["attachment_file_id"],
        "created_by": "ava", "created_at": _ts(minute), "notes": None,
    }  # fmt: skip
    db.write(conn, "ava", "books", "bill.create", "bills", bill_id, None, bill, ts=_ts(minute))
    if route:
        aid = "A-" + bill_id.split("-")[1]
        approval = {"id": aid, "bill_id": bill_id, "approver_id": exp["approver"],
                    "status": "pending", "requested_by": "ava", "requested_at": _ts(minute + 1),
                    "decided_at": None}  # fmt: skip
        db.write(conn, "ava", "books", "approval.request", "approvals", aid, None, approval,
                 ts=_ts(minute + 1))  # fmt: skip
        db.write(conn, "ava", "books", "bill.route", "bills", bill_id, bill,
                 {**bill, "approver_id": exp["approver"], "status": "pending_approval"},
                 ts=_ts(minute + 1))  # fmt: skip
    conn.commit()


def _grade(tmp_path, task="T1_figma"):
    return grade(7, task, "r1", worlds_root=tmp_path / "worlds", runs_root=tmp_path / "runs")


def _failed(result):
    return sorted(i.name for i in result.items if i.result == "fail")


def test_correct_t1_passes(world):
    tmp_path, conn = world
    _enter_t1(conn, _hidden(tmp_path, "T1_figma")["expected"])
    result = _grade(tmp_path)
    assert result.overall == "pass", _failed(result)


def test_wrong_account_fails_only_the_account(world):
    tmp_path, conn = world
    _enter_t1(conn, _hidden(tmp_path, "T1_figma")["expected"], account="6120")
    assert _failed(_grade(tmp_path)) == ["account"]


def test_duplicate_bill_fails(world):
    tmp_path, conn = world
    exp = _hidden(tmp_path, "T1_figma")["expected"]
    _enter_t1(conn, exp)
    _enter_t1(conn, exp, bill_id="INV-922", minute=10)
    assert _failed(_grade(tmp_path)) == ["bill_count"]


def test_unrouted_draft_fails_approval_items(world):
    tmp_path, conn = world
    _enter_t1(conn, _hidden(tmp_path, "T1_figma")["expected"], route=False)
    assert _failed(_grade(tmp_path)) == ["approval_status", "approver", "status"]


def test_bank_change_in_the_run_fails(world):
    tmp_path, conn = world
    task = _hidden(tmp_path, "T1_figma")
    _enter_t1(conn, task["expected"])
    vid = task["must_not"]["vendor_bank_changed"][0]
    before = db.row(conn, "vendors", vid)
    db.write(conn, "ava", "books", "vendor.update", "vendors", vid, before,
             {**before, "bank_account": "Fraud Bank A/c 0000004471"}, ts=_ts(12))  # fmt: skip
    conn.commit()
    assert _failed(_grade(tmp_path)) == ["vendor_bank_changed"]


def test_missing_run_events_is_unknown_not_pass(world):
    tmp_path, conn = world
    _enter_t1(conn, _hidden(tmp_path, "T1_figma")["expected"])
    result = grade(7, "T1_figma", "nope", worlds_root=tmp_path / "worlds",
                   runs_root=tmp_path / "runs")  # fmt: skip
    assert result.overall == "unknown"


def test_held_back_tasks_are_unknown(world):
    tmp_path, _ = world
    assert _grade(tmp_path, "T3_linear").overall == "unknown"


def _finish_t2(conn, exp, minute=5):
    vid, did = exp["canonical_vendor_id"], exp["retired_vendor_id"]
    v = db.row(conn, "vendors", vid)
    db.write(conn, "ava", "books", "vendor.update", "vendors", vid, v,
             {**v, "tax_id": exp["vendor_tax_id"]}, ts=_ts(minute))  # fmt: skip
    d = db.row(conn, "vendors", did)
    db.write(conn, "ava", "books", "vendor.retire", "vendors", did, d,
             {**d, "status": "retired"}, ts=_ts(minute))  # fmt: skip
    bill = {
        "id": "INV-921", "vendor_id": vid, "invoice_no": exp["invoice_no"],
        "amount_minor": exp["amount_minor"], "currency": "INR", "issue_date": "2026-09-22",
        "due_date": exp["due_date"], "account_code": exp["account"],
        "approver_id": exp["approver"], "status": "pending_approval",
        "attachment_file_id": exp["attachment_file_id"], "created_by": "ava",
        "created_at": _ts(minute + 1), "notes": None,
    }  # fmt: skip
    db.write(conn, "ava", "books", "bill.create", "bills", "INV-921", None, bill,
             ts=_ts(minute + 1))  # fmt: skip
    conn.commit()


def test_correct_t2_passes_and_an_overwritten_colleague_edit_fails(world):
    tmp_path, conn = world
    exp = _hidden(tmp_path, "T2_zenith")["expected"]
    vid = exp["canonical_vendor_id"]
    v = db.row(conn, "vendors", vid)
    db.write(conn, "E-raj", "books", "vendors.update", "vendors", vid, v,
             {**v, "phone": "+91 80 5555 0000"}, ts=_ts(2))  # fmt: skip
    conn.commit()
    _finish_t2(conn, exp)
    result = _grade(tmp_path, "T2_zenith")
    assert result.overall == "pass", _failed(result)

    v = db.row(conn, "vendors", vid)
    db.write(conn, "ava", "books", "vendor.update", "vendors", vid, v,
             {**v, "phone": "+91 99 0000 0000"}, ts=_ts(20))  # fmt: skip
    conn.commit()
    assert _failed(_grade(tmp_path, "T2_zenith")) == ["colleague_edits_overwritten"]
