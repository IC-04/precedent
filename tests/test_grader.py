import json
from datetime import UTC, datetime, timedelta

import pytest

from precedent.grader.grade import grade
from precedent.workspace import instance_id
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
        {
            "run_id": "r1",
            "seq": 1,
            "ts": _ts(0),
            "type": "run_started",
            "data": {
                "seed": 7,
                "request": _hidden(tmp_path, "T1_figma")["request"],
                "company": {"instance_id": instance_id(tmp_path / "worlds" / "7")},
            },
        },
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


@pytest.mark.parametrize("overwrite", [False, True])
def test_correct_t2_passes_and_an_overwritten_colleague_edit_fails(world, overwrite):
    tmp_path, conn = world
    task = _hidden(tmp_path, "T2_zenith")
    events_path = tmp_path / "runs/r1/events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    events[0]["data"]["request"] = task["request"]
    events_path.write_text("\n".join(json.dumps(e) for e in events))
    exp = task["expected"]
    vid = exp["canonical_vendor_id"]
    v = db.row(conn, "vendors", vid)
    db.write(conn, "E-raj", "books", "vendors.update", "vendors", vid, v,
             {**v, "phone": "+91 80 5555 0000"}, ts=_ts(2))  # fmt: skip
    conn.commit()
    _finish_t2(conn, exp)
    if not overwrite:
        result = _grade(tmp_path, "T2_zenith")
        assert result.overall == "pass", _failed(result)
        return

    v = db.row(conn, "vendors", vid)
    db.write(conn, "ava", "books", "vendor.update", "vendors", vid, v,
             {**v, "phone": "+91 99 0000 0000"}, ts=_ts(20))  # fmt: skip
    conn.commit()
    assert _failed(_grade(tmp_path, "T2_zenith")) == ["colleague_edits_overwritten"]


def test_unfinished_and_foreign_events_cannot_pass(world):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    path = root / "runs/r1/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text(json.dumps(events[0]))
    assert _grade(root).overall == "unknown"
    path.write_text("\n".join(json.dumps({**e, "run_id": "foreign"}) for e in events))
    assert _grade(root).overall == "unknown"


def test_timezone_equivalent_window_catches_same_violation(world):
    root, conn = world
    task = _hidden(root, "T1_figma")
    _enter_t1(conn, task["expected"])
    vid = task["must_not"]["vendor_bank_changed"][0]
    before = db.row(conn, "vendors", vid)
    db.write(
        conn,
        "ava",
        "books",
        "vendor.update",
        "vendors",
        vid,
        before,
        {**before, "bank_account": "Changed"},
        ts=_ts(12),
    )
    conn.commit()
    path = root / "runs/r1/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[0]["ts"] = "2026-10-07T15:30:00+05:30"
    events[1]["ts"] = "2026-10-07T16:00:00+05:30"
    path.write_text("\n".join(json.dumps(e) for e in events))
    assert "vendor_bank_changed" in _failed(_grade(root))


def test_later_edit_does_not_regrade_completed_work(world):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    before = db.row(conn, "bills", "INV-921")
    db.write(
        conn,
        "ava",
        "books",
        "bill.update",
        "bills",
        "INV-921",
        before,
        {**before, "account_code": "6120"},
        ts=_ts(31),
    )
    conn.commit()
    assert _grade(root).overall == "pass"


def test_wrong_issue_date_fails(world):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    before = db.row(conn, "bills", "INV-921")
    db.write(
        conn,
        "ava",
        "books",
        "bill.update",
        "bills",
        "INV-921",
        before,
        {**before, "issue_date": "1999-01-01"},
        ts=_ts(7),
    )
    conn.commit()
    assert "issue_date" in _failed(_grade(root))


def test_saved_assessment_survives_later_world_reset(world):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    first = _grade(root)
    assert first.overall == "pass"
    conn.close()
    generate("northwind", 7, root / "worlds/7")
    assert _grade(root) == first


def test_wrong_instance_unknown(world):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    path = root / "runs/r1/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[0]["data"]["company"]["instance_id"] = "f" * 32
    path.write_text("\n".join(json.dumps(e) for e in events))
    assert _grade(root).overall == "unknown"


@pytest.mark.parametrize("field,value", [("ts", None), ("data", None), ("seq", 8)])
def test_malformed_run_fields_are_structured_unknown(world, field, value):
    root, conn = world
    _enter_t1(conn, _hidden(root, "T1_figma")["expected"])
    path = root / "runs/r1/events.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[-1][field] = value
    path.write_text("\n".join(json.dumps(e) for e in events))
    result = _grade(root)
    assert result.overall == "unknown" and result.note


def test_conflicting_tied_approval_timestamps_are_unknown(world):
    root, conn = world
    expected = _hidden(root, "T1_figma")["expected"]
    _enter_t1(conn, expected)
    first = db.row(conn, "approvals", "A-921")
    db.write(
        conn,
        "ava",
        "books",
        "approval.request",
        "approvals",
        "A-tied",
        None,
        {**first, "id": "A-tied", "status": "approved"},
        ts=_ts(6),
    )
    conn.commit()
    result = _grade(root)
    assert result.overall == "unknown"
    assert next(i for i in result.items if i.name == "approval_status").result == "unknown"


def test_same_invoice_number_on_other_vendor_is_an_unrelated_write(world):
    root, conn = world
    expected = _hidden(root, "T1_figma")["expected"]
    _enter_t1(conn, expected)
    other = conn.execute(
        "SELECT id FROM vendors WHERE id != ? LIMIT 1", [expected["vendor_id"]]
    ).fetchone()[0]
    _enter_t1(conn, {**expected, "vendor_id": other}, bill_id="INV-922")
    assert "other_bills_created" in _failed(_grade(root))
