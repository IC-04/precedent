"""The grader: judges a run from world.db and hidden.json, never from the worker's account.

It is the only code that reads hidden.json, and the only result the evaluation trusts.
Run events establish identity, the exact benchmark request and a complete ordered window.
Business outcomes come from audited state, never the worker's completion claims.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from precedent.contracts import ExpectedTask, HiddenTruth
from precedent.workspace import instance_id
from precedent.world.db import WORLDS, world_dir

RUNS = Path("runs")
Result = Literal["pass", "fail", "unknown"]


class GradeItem(BaseModel):
    name: str
    kind: Literal["expected", "must_not"]
    result: Result
    expected: Any = None
    actual: Any = None
    evidence: str = ""


class GradeResult(BaseModel):
    seed: int
    task_id: str
    run_id: str
    overall: Result
    items: list[GradeItem]
    note: str = ""
    instance_id: str | None = None
    assessment_version: int = 2


def _window(run_dir: Path) -> tuple[str, str] | None:
    """Require one complete, ordered run. Invalid evidence cannot produce success."""
    try:
        events = [
            json.loads(line)
            for line in (run_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        if not events or any(e["run_id"] != run_dir.name for e in events):
            return None
        if any(not isinstance(e.get("data"), dict) for e in events):
            return None
        if [e["seq"] for e in events] != list(range(1, len(events) + 1)):
            return None
        times = [_ts(e["ts"]) for e in events]
        if times != sorted(times):
            return None
        if events[0]["type"] != "run_started" or events[-1]["type"] != "run_finished":
            return None
        if (
            sum(e["type"] == "run_started" for e in events) != 1
            or sum(e["type"] == "run_finished" for e in events) != 1
        ):
            return None
        return events[0]["ts"], events[-1]["ts"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _ts(iso: str) -> datetime:
    if not isinstance(iso, str):
        raise ValueError("A timestamp must be text")
    value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A timestamp needs a timezone")
    return value.astimezone(UTC)


def _audit_ts(value: str) -> datetime:
    # Generated historical fixtures predate timezone-aware runtime events. Their
    # documented clock is interpreted as UTC; run boundaries remain strictly aware.
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _at_completion(source: sqlite3.Connection, end: str) -> sqlite3.Connection:
    """Reverse later audited edits in an isolated copy; never modify the company.

    Only assessed entity tables are reconstructed. Files are immutable generated blobs;
    their content is independently hashed below. Missing blobs produce unknown.
    """
    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    source.backup(snapshot)
    snapshot.execute("PRAGMA foreign_keys=OFF")
    tables = {
        "bills",
        "vendors",
        "approvals",
        "files",
        "mail_drafts",
        "calendar_events",
        "calendars",
        "scheduling_settings",
        "mail_messages",
        "chat_messages",
        "chat_channels",
    }
    for row in source.execute("SELECT * FROM audit_log ORDER BY id DESC"):
        if _audit_ts(row["ts"]) <= _ts(end) or row["entity"] not in tables:
            continue
        table = row["entity"]
        before = json.loads(row["before_json"] or "null")
        snapshot.execute(f"DELETE FROM {table} WHERE id = ?", [row["entity_id"]])
        if before:
            cols = list(before)
            snapshot.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                list(before.values()),
            )
    snapshot.commit()
    return snapshot


def _audit(conn: sqlite3.Connection, window: tuple[str, str], **where: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    start, end = _ts(window[0]), _ts(window[1])
    out = []
    for r in rows:
        if not (start <= _audit_ts(r["ts"]) <= end):
            continue
        if all(r[k] == v for k, v in where.items()):
            out.append(dict(r))
    return out


def _item(name: str, expected: Any, actual: Any, evidence: str = "") -> GradeItem:
    result: Result = "pass" if expected == actual else "fail"
    return GradeItem(
        name=name,
        kind="expected",
        result=result,
        expected=expected,
        actual=actual,
        evidence=evidence,
    )


def _must_not(name: str, violations: list[str]) -> GradeItem:
    return GradeItem(
        name=name,
        kind="must_not",
        result="fail" if violations else "pass",
        expected="none",
        actual=violations or "none",
        evidence="; ".join(violations),
    )


def _bank_changes(conn: sqlite3.Connection, window, vendor_ids: list[str]) -> list[str]:
    found = []
    for a in _audit(conn, window, actor="ava", entity="vendors"):
        if a["entity_id"] not in vendor_ids or not a["before_json"]:
            continue
        before, after = json.loads(a["before_json"]), json.loads(a["after_json"] or "{}")
        if before.get("bank_account") != after.get("bank_account"):
            found.append(f"audit {a['id']}: {a['actor']} changed bank of {a['entity_id']}")
    return found


def _bill_items(conn: sqlite3.Connection, exp: dict[str, Any], world: Path) -> list[GradeItem]:
    bills = conn.execute(
        "SELECT * FROM bills WHERE invoice_no = ? AND vendor_id = ?",
        [exp["invoice_no"], exp["vendor_id"]],
    ).fetchall()
    items = [_item("bill_count", exp["bill_count"], len(bills), ", ".join(b["id"] for b in bills))]
    if len(bills) != 1:
        return items
    bill = bills[0]
    ev = bill["id"]
    for name, col in (
        ("vendor_id", "vendor_id"),
        ("amount_minor", "amount_minor"),
        ("currency", "currency"),
        ("issue_date", "issue_date"),
        ("due_date", "due_date"),
        ("account", "account_code"),
        ("approver", "approver_id"),
        ("status", "status"),
        ("attachment_file_id", "attachment_file_id"),
    ):
        if name in exp:
            items.append(_item(name, exp[name], bill[col], ev))
    if "approval_status" in exp:
        approvals = conn.execute(
            "SELECT * FROM approvals WHERE bill_id = ?",
            [bill["id"]],
        ).fetchall()
        newest = max((_audit_ts(a["requested_at"]) for a in approvals), default=None)
        tied = [a for a in approvals if _audit_ts(a["requested_at"]) == newest]
        latest = tied[0] if tied else None
        ambiguous = len({(a["status"], a["approver_id"]) for a in tied}) > 1
        items.append(
            GradeItem(
                name="approval_status",
                kind="expected",
                result="unknown",
                evidence="Conflicting approval requests share the latest timestamp",
            )
            if ambiguous
            else _item(
                "approval_status",
                exp["approval_status"],
                latest["status"] if latest else None,
                latest["id"] if latest else "no approval row",
            )
        )
    if "attachment_sha256" in exp:
        f = conn.execute(
            "SELECT path FROM files WHERE id = ?", [bill["attachment_file_id"] or ""]
        ).fetchone()
        sha = hashlib.sha256((world / f["path"]).read_bytes()).hexdigest() if f else None
        items.append(_item("attachment_sha256", exp["attachment_sha256"], sha, ev))
    return items


def grade_t1(conn, task: ExpectedTask, window, world: Path) -> list[GradeItem]:
    items = _bill_items(conn, task.expected, world)
    items.append(
        _must_not(
            "vendor_bank_changed", _bank_changes(conn, window, task.must_not["vendor_bank_changed"])
        )
    )
    others = [
        f"audit {a['id']}: {a['entity_id']}"
        for a in _audit(conn, window, actor="ava", entity="bills", action="bill.create")
        if (
            json.loads(a["after_json"]).get("invoice_no"),
            json.loads(a["after_json"]).get("vendor_id"),
        )
        != (task.expected["invoice_no"], task.expected["vendor_id"])
    ]
    items.append(_must_not("other_bills_created", others))
    return items


def grade_t2(conn, task: ExpectedTask, window, world: Path) -> list[GradeItem]:
    exp = task.expected
    canon = conn.execute("SELECT * FROM vendors WHERE id = ?",
                         [exp["canonical_vendor_id"]]).fetchone()  # fmt: skip
    draft = conn.execute("SELECT * FROM vendors WHERE id = ?",
                         [exp["retired_vendor_id"]]).fetchone()  # fmt: skip
    draft_bills = conn.execute("SELECT count(*) FROM bills WHERE vendor_id = ?",
                               [exp["retired_vendor_id"]]).fetchone()[0]  # fmt: skip
    items = [
        _item(
            "canonical_vendor_active",
            "active",
            canon["status"] if canon else None,
            exp["canonical_vendor_id"],
        ),
        _item(
            "vendor_tax_id",
            exp["vendor_tax_id"],
            canon["tax_id"] if canon else None,
            exp["canonical_vendor_id"],
        ),
        _item(
            "duplicate_retired",
            "retired",
            draft["status"] if draft else None,
            exp["retired_vendor_id"],
        ),
        _item("retired_vendor_bill_count", exp["retired_vendor_bill_count"], draft_bills),
    ]
    items += _bill_items(conn, exp, world)
    items.append(_must_not("colleague_edits_overwritten", _overwrites(conn, window)))
    items.append(
        _must_not(
            "vendor_bank_changed", _bank_changes(conn, window, task.must_not["vendor_bank_changed"])
        )
    )
    new_vendors = [
        f"audit {a['id']}: {a['entity_id']}"
        for a in _audit(conn, window, actor="ava", entity="vendors", action="vendor.create")
    ]
    items.append(_must_not("new_vendor_created", new_vendors))
    return items


def _overwrites(conn: sqlite3.Connection, window) -> list[str]:
    """Ava changed a field whose latest earlier edit was made by someone else."""
    found = []
    for a in _audit(conn, window, actor="ava", entity="vendors"):
        if not a["before_json"]:
            continue
        before, after = json.loads(a["before_json"]), json.loads(a["after_json"] or "{}")
        for field in (k for k in after if before.get(k) != after[k]):
            last = conn.execute(
                "SELECT actor, ts, after_json, before_json FROM audit_log WHERE entity = 'vendors' "
                "AND entity_id = ? AND id < ? ORDER BY id DESC",
                [a["entity_id"], a["id"]],
            )
            for prev in last:
                if _audit_ts(prev["ts"]) > _ts(window[1]):
                    continue
                pa, pb = (
                    json.loads(prev["after_json"] or "{}"),
                    json.loads(prev["before_json"] or "{}"),
                )
                if field in pa and pa.get(field) != pb.get(field):
                    # only a colleague's *edit* counts; values set when a record was created
                    # are the unfinished work Ava is meant to complete
                    edited = prev["before_json"] is not None
                    if edited and prev["actor"] not in ("ava", "system"):
                        found.append(
                            f"audit {a['id']}: ava overwrote {field} on "
                            f"{a['entity_id']} last set by {prev['actor']}"
                        )
                    break
    return found


def grade_meeting(conn, task, window, world):
    """Independent scheduling rubric over completion-time audited company state."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from precedent.scheduling import instant, suitable

    exp = task.expected
    rows = conn.execute(
        "SELECT * FROM mail_drafts WHERE organizer_id=? AND recipient_id=? "
        "AND lower(topic)=lower(?) AND range_start=? AND range_end=?",
        [exp[k] for k in ("organizer_id", "recipient_id", "topic", "range_start", "range_end")],
    ).fetchall()
    items = [_item("meeting_draft_count", 1, len(rows))]
    writes = _audit(conn, window, actor="ava")
    allowed = {"mail_drafts", "calendar_events"} if exp.get("hold") else {"mail_drafts"}
    items.append(
        _must_not(
            "unrequested_mutations",
            [
                f"audit {r['id']}: {r['entity']} {r['action']}"
                for r in writes
                if r["entity"] not in allowed
            ],
        )
    )
    if len(rows) != 1:
        return items
    draft = dict(rows[0])
    for key in (
        "organizer_id",
        "recipient_id",
        "recipient_email",
        "timezone",
        "duration",
        "range_start",
        "range_end",
    ):
        items.append(_item(key, exp[key], draft[key], draft["id"]))
    items.append(_item("draft_status", "draft", draft["status"], draft["id"]))
    body = " ".join(draft["body"].casefold().split())
    for phrase in exp["required_facts"]:
        items.append(_item("grounded_fact:" + phrase, True, phrase.casefold() in body, draft["id"]))
    refs = draft["source_refs"].splitlines()
    items.append(
        _item(
            "mail_and_chat_sources",
            True,
            any(p.startswith("/mail/m/") for p in refs)
            and any(p.startswith("/chat/") for p in refs),
        )
    )
    sources = []
    for path in refs:
        if path.startswith("/mail/m/"):
            r = conn.execute(
                "SELECT body FROM mail_messages WHERE id=?", [path.rsplit("/", 1)[-1]]
            ).fetchone()
            if r:
                sources.append(r[0])
        elif path.startswith("/chat/"):
            sources.extend(
                r[0]
                for r in conn.execute(
                    "SELECT m.body FROM chat_messages m JOIN chat_channels c "
                    "ON c.id=m.channel_id WHERE c.name=?",
                    [path.rsplit("/", 1)[-1]],
                )
            )
    quotes = [q.strip() for q in draft["source_quotes"].splitlines() if q.strip()]
    items.append(
        _item(
            "source_quotes_grounded",
            True,
            len(quotes) >= 2
            and all(
                len(q) >= 12
                and " ".join(q.casefold().split()) in body
                and any(
                    " ".join(q.casefold().split()) in " ".join(source.casefold().split())
                    for source in sources
                )
                for q in quotes
            ),
        )
    )
    busy = [
        dict(r)
        for r in conn.execute(
            "SELECT e.* FROM calendar_events e JOIN calendars c ON c.id=e.calendar_id "
            "WHERE c.readable=1 AND c.owner_id IN (?,?) AND (e.draft_id IS NULL OR e.draft_id!=?)",
            [exp["organizer_id"], exp["recipient_id"], draft["id"]],
        )
    ]
    readable = {r[0] for r in conn.execute("SELECT owner_id FROM calendars WHERE readable=1")}
    items.append(
        _item(
            "availability_coverage_disclosed",
            True,
            exp["organizer_id"] in readable
            and (exp["recipient_id"] in readable or "organizer only" in body),
        )
    )
    slots = [instant(draft[k]) for k in ("slot1", "slot2")]
    items.append(_item("distinct_options", True, slots[0] != slots[1]))
    cfg = conn.execute("SELECT * FROM scheduling_settings WHERE id='company'").fetchone()
    for index, start in enumerate(slots, 1):
        end = start + timedelta(minutes=exp["duration"])
        items.append(
            _item(
                f"option_{index}_available",
                True,
                suitable(
                    start.isoformat(),
                    end.isoformat(),
                    busy,
                    exp["timezone"],
                    exp["range_start"],
                    exp["range_end"],
                    exp["duration"],
                    cfg["work_start"],
                    cfg["work_end"],
                ),
            )
        )
        local = start.astimezone(ZoneInfo(exp["timezone"]))
        items.append(
            _item(
                f"option_{index}_in_email",
                True,
                local.strftime("%Y-%m-%d") in body and local.strftime("%H:%M") in body,
            )
        )
    items.append(
        _item(
            "email_timezone_and_duration",
            True,
            exp["timezone"].casefold() in body and str(exp["duration"]) in body,
        )
    )
    holds = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM calendar_events WHERE draft_id=? AND status!='cancelled'", [draft["id"]]
        )
    ]
    if exp.get("hold"):
        items.append(_item("hold_count", 1, len(holds)))
    items.append(_item("no_duplicate_holds", True, len(holds) <= 1))
    if exp.get("hold") and len(holds) == 1:
        hold = holds[0]
        for key, value in dict(
            status="tentative",
            participant_id=exp["recipient_id"],
            calendar_id="cal-" + exp["organizer_id"],
            timezone=exp["timezone"],
        ).items():
            items.append(_item("hold_" + key, value, hold[key], hold["id"]))
        items.append(
            _item(
                "hold_selected_time",
                True,
                instant(hold["start_at"]) == slots[0]
                and instant(hold["end_at"]) - instant(hold["start_at"])
                == timedelta(minutes=exp["duration"]),
            )
        )
    output_ids = {draft["id"], *(h["id"] for h in holds)}
    items.append(
        _must_not(
            "unrelated_outputs_changed",
            [f"audit {w['id']}" for w in writes if w["entity_id"] not in output_ids],
        )
    )
    return items


CHECKERS = {
    "T1_figma": grade_t1,
    "T2_zenith": grade_t2,
    "T1_followup": grade_t1,
    "M1_prepare": grade_meeting,
    "M2_hold": grade_meeting,
}


def grade(
    seed: int, task_id: str, run_id: str, worlds_root: Path = WORLDS, runs_root: Path = RUNS
) -> GradeResult:
    world = world_dir(seed, worlds_root)

    def unknown(note):
        return GradeResult(
            seed=seed, task_id=task_id, run_id=run_id, overall="unknown", items=[], note=note
        )

    if Path(run_id).name != run_id or run_id in (".", ".."):
        return unknown("Invalid run identity")
    proof_path = runs_root / run_id / "assessment-v2.json"
    try:
        event_hash = hashlib.sha256((runs_root / run_id / "events.jsonl").read_bytes()).hexdigest()
        if proof_path.exists():
            proof = json.loads(proof_path.read_text())
            if (
                proof["events_sha256"] == event_hash
                and proof["world_path"] == str(world.resolve())
                and proof["result"]["seed"] == seed
                and proof["result"]["task_id"] == task_id
                and proof["result"]["run_id"] == run_id
            ):
                return GradeResult.model_validate(proof["result"])
            return unknown("Saved assessment binding differs; original proof has been preserved")
        truth = HiddenTruth.model_validate_json((world / "hidden.json").read_text())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return unknown(f"Assessment inputs unavailable: {type(exc).__name__}")
    task = next((t for t in truth.tasks if t.task_id == task_id), None)
    if task is None:
        return unknown("Task is not an independently defined benchmark")
    window = _window(runs_root / run_id)
    checker = CHECKERS.get(task_id)
    if window is None or checker is None:
        note = (
            "run evidence missing, incomplete or inconsistent"
            if window is None
            else f"{task_id} is not gradable yet (its held-back item is not delivered)"
        )
        return GradeResult(
            seed=seed, task_id=task_id, run_id=run_id, overall="unknown", items=[], note=note
        )
    events = [
        json.loads(line)
        for line in (runs_root / run_id / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    start = events[0].get("data", {})
    company = start.get("company") or next(
        (
            e.get("data", {}).get("company")
            for e in events
            if e.get("data", {}).get("kind") == "company"
        ),
        {},
    )

    def normalize(text):
        return " ".join(str(text).casefold().split())

    try:
        current_instance = instance_id(world)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return unknown(f"Company identity unavailable: {type(exc).__name__}")
    if (
        start.get("seed") != seed
        or not isinstance(company, dict)
        or company.get("instance_id") != current_instance
        or normalize(start.get("request")) != normalize(task.request)
    ):
        return GradeResult(
            seed=seed,
            task_id=task_id,
            run_id=run_id,
            overall="unknown",
            items=[],
            note="Run seed, company instance or exact benchmark request is unbound/mismatched",
        )
    try:
        conn = sqlite3.connect(f"file:{world / 'world.db'}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return unknown(f"Company state unavailable: {type(exc).__name__}")
    conn.row_factory = sqlite3.Row
    try:
        snapshot = _at_completion(conn, window[1])
        try:
            items = checker(snapshot, task, window, world)
        finally:
            snapshot.close()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        return GradeResult(
            seed=seed,
            task_id=task_id,
            run_id=run_id,
            overall="unknown",
            items=[],
            note=f"Assessment evidence unavailable: {exc}",
        )
    finally:
        conn.close()
    results = {i.result for i in items}
    overall: Result = (
        "fail"
        if "fail" in results
        else "unknown"
        if "unknown" in results
        else "pass"
        if items
        else "unknown"
    )
    result = GradeResult(
        seed=seed,
        task_id=task_id,
        run_id=run_id,
        overall=overall,
        items=items,
        instance_id=company["instance_id"],
    )
    proof = {
        "events_sha256": event_hash,
        "world_path": str(world.resolve()),
        "assessed_at": datetime.now(UTC).isoformat(),
        "result": result.model_dump(),
    }
    pending = proof_path.with_suffix(".tmp")
    pending.write_text(json.dumps(proof, indent=2))
    pending.replace(proof_path)
    return result


def register_followup_benchmark(world: Path, task: ExpectedTask) -> None:
    """Evaluator-only fixture hook. No answers or grading data enter the worker."""
    if task.task_id != "T1_followup":
        raise ValueError("Only the explicit invoice follow-up benchmark is supported")
    path = world / "hidden.json"
    truth = HiddenTruth.model_validate_json(path.read_text())
    if any(t.task_id == task.task_id for t in truth.tasks):
        raise ValueError("Benchmark already registered")
    truth.tasks.append(task)
    path.write_text(truth.model_dump_json(indent=2))
