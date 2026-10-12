"""Scheduling semantics and end-to-end local application proof, without model calls."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from precedent.apps.server import create_app
from precedent.contracts import MeetingIntent
from precedent.grader.grade import grade_meeting
from precedent.scheduling import instant, next_week, options, overlap
from precedent.worker.meetings import Tables, meeting_goal, verify, write_policy
from precedent.worker.verify import record_fields
from precedent.world import db
from precedent.world.generator import generate


@pytest.fixture
def company(tmp_path):
    generate("northwind", 7, tmp_path / "7")
    conn = db.connect(tmp_path / "7/world.db")
    client = TestClient(create_app(7, tmp_path))
    yield client, conn, tmp_path / "7"
    conn.close()


def draft_form(client):
    h = client.get("/calendar/availability?recipient=E-ana").text
    rows = Tables(h).rows("available-options")
    cfg = record_fields(h)
    slots = [rows[0]["Start (local)"], rows[2]["Start (local)"]]
    facts = [
        "We need to review 24 unused seats before the vendor renewal.",
        "Please compare the annual and monthly pricing before we decide.",
    ]
    return dict(
        recipient_id="E-ana",
        topic="vendor renewal",
        subject="Vendor renewal catch-up",
        body="Hi Ana,\n"
        + " ".join(facts)
        + "\nCould we meet for 30 minutes at "
        + " or ".join(s.replace("T", " ") for s in slots)
        + " Asia/Kolkata? Please confirm.",
        range_start=cfg["Range start"],
        range_end=cfg["Range end"],
        duration="30",
        timezone="Asia/Kolkata",
        slot1=slots[0],
        slot2=slots[1],
        source_refs="/mail/m/m-meeting-context\n/chat/renewal-planning",
        source_quotes="\n".join(facts),
    )


def save(client, form):
    r = client.post("/mail/drafts/new", data=form, headers={"X-Precedent-Agent": "ava"})
    assert r.status_code == 200, r.text
    return r.url.path.rsplit("/", 1)[-1]


def test_dates_overlap_and_dst():
    assert next_week("2026-10-11") == ("2026-10-12", "2026-10-19")
    assert next_week("2026-10-12") == ("2026-10-19", "2026-10-26")
    a = instant("2026-10-10T09:00", "Asia/Kolkata")
    assert a.hour == 3 and a.minute == 30
    assert not overlap(a, a + timedelta(hours=1), a + timedelta(hours=1), a + timedelta(hours=2))
    for value in ("2026-03-08T02:30", "2026-11-01T01:30"):
        with pytest.raises(ValueError):
            instant(value, "America/New_York")
    assert instant("2026-03-06T09:00", "America/New_York").hour == 14
    assert instant("2026-03-09T09:00", "America/New_York").hour == 13


def test_meeting_intent_schema_supported_by_installed_model_sdk():
    from google.genai import types

    types.Schema.model_validate(MeetingIntent.model_json_schema())
    with pytest.raises(ValueError):
        MeetingIntent(participant="Ana", topic="renewal", hold_option=3)


def test_meeting_episode_cannot_become_an_invoice_skill(tmp_path):
    from precedent.learning.store import Store

    store = Store(tmp_path)
    episode = store.put(
        "local:test:ava", "episode", "Meeting prepared", {"task_family": "meeting", "observed": []}
    )
    with pytest.raises(ValueError, match="meeting skill validation"):
        store.draft_skill("local:test:ava", episode["id"])


def test_all_day_and_insufficient_slots():
    busy = [
        dict(
            start_at="2026-10-12T00:00:00+00:00",
            end_at="2026-10-13T00:00:00+00:00",
            status="confirmed",
        )
    ]
    assert options(busy, "UTC", "2026-10-12", "2026-10-13", 30) == []
    assert options([], "UTC", "2026-10-17", "2026-10-19", 30) == []
    assert len(options([], "UTC", "2026-10-12", "2026-10-13", 30)) == 16


def test_week_all_day_end_is_exclusive_and_hours_are_sourced(company):
    client, conn, _ = company
    event = dict(conn.execute("SELECT * FROM calendar_events LIMIT 1").fetchone())
    event.update(
        id="all-day-boundary",
        title="All day boundary proof",
        start_at="2026-10-12T00:00:00+05:30",
        end_at="2026-10-13T00:00:00+05:30",
        all_day=1,
    )
    db.write(conn, "system", "Calendar", "fixture", "calendar_events", event["id"], None, event)
    conn.execute("UPDATE scheduling_settings SET work_start=10, work_end=16")
    conn.commit()
    html = client.get("/calendar/?start=2026-10-12").text
    days = html.split('<section class="calendar-day">')[1:]
    assert "All day boundary proof" in days[0]
    assert "All day boundary proof" not in days[1]
    assert "10:00 – 16:00" in html


def test_draft_persistence_reconcile_and_concurrent_edit(company):
    client, conn, world = company
    form = draft_form(client)
    did = save(client, form)
    assert client.post("/mail/drafts/new", data=form).status_code == 409
    assert conn.execute("SELECT count(*) FROM mail_drafts").fetchone()[0] == 1
    # Reopening the app is a process-local state reset, not regeneration.
    restarted = TestClient(create_app(7, world.parent))
    assert did in restarted.get("/mail/drafts").text
    form.update(version="1", body=form["body"] + " Looking forward to it.")
    assert restarted.post(f"/mail/drafts/{did}/edit", data=form).status_code == 200
    assert (
        client.post(
            f"/mail/drafts/{did}/edit", data=form, headers={"X-Precedent-Agent": "ava"}
        ).status_code
        == 409
    )
    assert conn.execute("SELECT updated_by FROM mail_drafts").fetchone()[0] == "human"
    assert (
        conn.execute("SELECT count(*) FROM audit_log WHERE entity='mail_drafts'").fetchone()[0] == 2
    )


def hold_form(form, did):
    return dict(
        calendar_id="cal-E-priya",
        title="Vendor renewal",
        start_at=form["slot1"],
        end_at=(datetime.fromisoformat(form["slot1"]) + timedelta(minutes=30)).isoformat(),
        participant_id="E-ana",
        draft_id=did,
    )


def test_hold_permission_conflict_and_lost_ack(company, monkeypatch):
    client, conn, _ = company
    form = draft_form(client)
    did = save(client, form)
    assert write_policy(MeetingIntent())("POST", "/calendar/new", b"")
    assert write_policy(MeetingIntent(local_hold=True))("POST", "/calendar/new", b"") is None
    assert write_policy(MeetingIntent(local_hold=True))("POST", "/books/bills/new", b"")
    # App commits the hold and drops its acknowledgement, using the existing failure hook.
    client.app.state.drop_next.add("/calendar/new")
    r = client.post(
        "/calendar/new", data=hold_form(form, did), headers={"X-Precedent-Agent": "ava"}
    )
    assert r.status_code == 502
    assert (
        conn.execute("SELECT count(*) FROM calendar_events WHERE draft_id=?", [did]).fetchone()[0]
        == 1
    )
    r = client.post("/calendar/new", data=hold_form(form, did))
    assert r.status_code == 409
    event = dict(conn.execute("SELECT * FROM calendar_events WHERE draft_id=?", [did]).fetchone())
    assert event["status"] == "tentative"
    other = {**hold_form(form, did), "draft_id": "", "title": "Conflicting hold"}
    assert client.post("/calendar/new", data=other).status_code == 409
    forbidden = {**other, "calendar_id": "cal-E-ana"}
    assert client.post("/calendar/new", data=forbidden).status_code == 409


def test_missing_colleague_calendar_and_bad_values(company):
    client, conn, _ = company
    conn.execute("UPDATE calendars SET readable=0 WHERE owner_id='E-ana'")
    conn.commit()
    assert (
        record_fields(client.get("/calendar/availability?recipient=E-ana").text)["Coverage"]
        == "organizer only"
    )
    form = draft_form(client)
    form["timezone"] = "Europe/London"
    assert client.post("/mail/drafts/new", data=form).status_code == 409
    form["timezone"] = "Asia/Kolkata"
    form["recipient_id"] = "missing"
    assert client.post("/mail/drafts/new", data=form).status_code == 409


def test_meeting_verifier_real_http(live_apps):
    base, raw = live_apps
    with httpx.Client(base_url=base, follow_redirects=True) as c:
        form = draft_form(c)
        did = save(c, form)
        goal = meeting_goal(
            "Prepare a catch-up", MeetingIntent(participant="Ana Pereira", topic="vendor renewal")
        )
        captured = {
            p: c.get(p).text for p in ["/mail/m/m-meeting-context", "/chat/renewal-planning"]
        }
        results, links = verify(base, goal, captured, [("POST", "/mail/drafts/new", 303)])
        assert all(r.result == "pass" for r in results), [
            (r.condition_id, r.result, r.evidence) for r in results
        ]
        assert any(x["path"].endswith(did) for x in links)
        raw.execute("UPDATE mail_drafts SET recipient_email='wrong@example.test' WHERE id=?", [did])
        raw.commit()
        results, _ = verify(base, goal, captured, [])
        assert (
            next(r for r in results if r.condition_id == "meeting_no_duplicates").result == "fail"
        )


def test_linked_hold_does_not_mask_an_unrelated_new_conflict(live_apps):
    base, conn = live_apps
    with httpx.Client(base_url=base, follow_redirects=True) as client:
        form = draft_form(client)
        did = save(client, form)
        response = client.post(
            "/calendar/new", data=hold_form(form, did), headers={"X-Precedent-Agent": "ava"}
        )
        assert response.status_code == 200
        goal = meeting_goal(
            "Prepare a catch-up and local hold",
            MeetingIntent(participant="Ana Pereira", topic="vendor renewal", local_hold=True),
        )
        sources = {
            p: client.get(p).text for p in ["/mail/m/m-meeting-context", "/chat/renewal-planning"]
        }
        results, _ = verify(base, goal, sources, [("POST", "/calendar/new", 303)])
        assert all(r.result == "pass" for r in results)
        cursor = conn.execute("SELECT * FROM calendar_events WHERE draft_id=?", [did])
        event = dict(
            zip((column[0] for column in cursor.description), cursor.fetchone(), strict=True)
        )
        # A newly observed attendee commitment, independent of this task's reservation.
        event.update(
            id="changed-attendee-schedule",
            calendar_id="cal-E-ana",
            draft_id=None,
            status="confirmed",
            title="New conflicting commitment",
        )
        db.write(conn, "system", "Calendar", "fixture", "calendar_events", event["id"], None, event)
        conn.commit()
        results, _ = verify(base, goal, sources, [])
        assert next(r for r in results if r.condition_id == "meeting_availability").result == "fail"


def test_independent_meeting_grader_and_wrong_slot(company):
    client, conn, world = company
    form = draft_form(client)
    save(client, form)
    from precedent.contracts import HiddenTruth

    task = next(
        t
        for t in HiddenTruth.model_validate_json((world / "hidden.json").read_text()).tasks
        if t.task_id == "M1_prepare"
    )
    now = datetime.now(UTC)
    window = ((now - timedelta(minutes=1)).isoformat(), (now + timedelta(seconds=1)).isoformat())
    result = grade_meeting(conn, task, window, world)
    assert all(r.result == "pass" for r in result), [
        (r.name, r.actual) for r in result if r.result != "pass"
    ]
    conn.execute("UPDATE mail_drafts SET slot1='1999-01-01T10:00:00+00:00'")
    conn.commit()
    assert any(r.result == "fail" for r in grade_meeting(conn, task, window, world))


def test_fabricated_quotes_are_rejected_before_save(company):
    client, conn, _ = company
    form = draft_form(client)
    form["source_quotes"] = "The vendor approved our contract.\nThe meeting is already confirmed."
    form["body"] += form["source_quotes"]
    assert client.post("/mail/drafts/new", data=form).status_code == 409
    assert conn.execute("SELECT count(*) FROM mail_drafts").fetchone()[0] == 0


def test_discard_uses_version_and_audit(company):
    client, conn, _ = company
    did = save(client, draft_form(client))
    assert client.post(f"/mail/drafts/{did}/discard", data={"version": "0"}).status_code == 409
    assert client.post(f"/mail/drafts/{did}/discard", data={"version": "1"}).status_code == 200
    row = conn.execute("SELECT * FROM audit_log WHERE action='draft.discard'").fetchone()
    assert row["actor"] == "human" and row["after_json"] is None
    assert client.get(f"/mail/drafts/{did}").status_code == 404


def test_missing_organizer_calendar_is_not_free(company):
    client, conn, _ = company
    conn.execute("UPDATE calendars SET readable=0 WHERE owner_id='E-priya'")
    conn.commit()
    html = client.get("/calendar/availability?recipient=E-ana").text
    assert record_fields(html)["Coverage complete"] == "no"
    assert record_fields(html)["Coverage"] == "unavailable"
    assert not Tables(html).rows("available-options")


def test_gateway_meeting_permissions_and_uncertain_draft(live_apps):
    from precedent.worker.failures import WriteGate
    from precedent.worker.gateway import Gateway
    from tests.conftest import TOKEN

    base, conn = live_apps
    gate = WriteGate()
    gw = Gateway(base, gate)
    gw.write_policy = write_policy(MeetingIntent())
    gw.start()
    try:
        with httpx.Client(base_url=gw.url, follow_redirects=True) as client:
            form = draft_form(client)
            gate.on_decision(["mail source"])
            assert client.post("/calendar/new", data={}).status_code == 409
            assert (
                client.post("/chat/renewal-planning", data={"body": "Send this"}).status_code == 409
            )
            httpx.post(
                base + "/__scenario/drop-next-response",
                params={"path": "/mail/drafts/new"},
                headers={"X-Scenario-Token": TOKEN},
            )
            response = client.post("/mail/drafts/new", data=form)
            assert response.status_code == 502
            assert gate.locked
            assert client.post("/mail/drafts/new", data=form).status_code == 409
            assert conn.execute("SELECT count(*) FROM mail_drafts").fetchone()[0] == 1
            html = client.get("/mail/drafts").text
            assert len(Tables(html).rows("draft-list")) == 1
            assert gate.searched
    finally:
        gw.stop()


def test_completed_meeting_assessment_survives_later_edits_and_reset(company, tmp_path):
    import json

    from precedent.grader.grade import grade
    from precedent.workspace import instance_id

    client, conn, world = company
    start = datetime.now(UTC)
    form = draft_form(client)
    chat_only_quote = "For our vendor renewal catch-up:"
    form["source_quotes"] += "\n" + chat_only_quote
    form["body"] += "\n" + chat_only_quote
    did = save(client, form)
    end = datetime.now(UTC)
    truth = json.loads((world / "hidden.json").read_text())
    task = next(t for t in truth["tasks"] if t["task_id"] == "M1_prepare")
    root = tmp_path / "runs"
    run = root / "proof"
    run.mkdir(parents=True)
    events = [
        dict(
            run_id="proof",
            seq=1,
            ts=start.isoformat(),
            type="run_started",
            data=dict(
                seed=7, request=task["request"], company=dict(instance_id=instance_id(world))
            ),
        ),
        dict(run_id="proof", seq=2, ts=end.isoformat(), type="run_finished", data={}),
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    # A later audited edit must be reversed even before first assessment.
    old = dict(conn.execute("SELECT * FROM mail_drafts WHERE id=?", [did]).fetchone())
    db.write(
        conn,
        "human",
        "mail",
        "draft.update",
        "mail_drafts",
        did,
        old,
        {**old, "recipient_email": "wrong@example.test"},
        ts=(end + timedelta(seconds=2)).isoformat(),
    )
    channel = dict(
        conn.execute("SELECT * FROM chat_channels WHERE name='renewal-planning'").fetchone()
    )
    db.write(
        conn,
        "human",
        "chat",
        "channel.rename",
        "chat_channels",
        channel["id"],
        channel,
        {**channel, "name": "later-renamed-channel"},
        ts=(end + timedelta(seconds=3)).isoformat(),
    )
    conn.commit()
    result = grade(7, "M1_prepare", "proof", worlds_root=world.parent, runs_root=root)
    assert result.overall == "pass", result.model_dump()
    assert (
        conn.execute("SELECT recipient_email FROM mail_drafts").fetchone()[0]
        == "wrong@example.test"
    )
    generate("northwind", 7, world)
    assert instance_id(world) != events[0]["data"]["company"]["instance_id"]
    assert grade(7, "M1_prepare", "proof", worlds_root=world.parent, runs_root=root) == result


def test_invalid_meeting_claim_mapping_stays_unknown(live_apps):
    base, _ = live_apps
    with httpx.Client(base_url=base, follow_redirects=True) as c:
        save(c, draft_form(c))
        goal = meeting_goal(
            "Prepare a catch-up", MeetingIntent(participant="Ana", topic="vendor renewal")
        )
        goal.conditions[0].claims = ["draft_saved", "meeting_identity"]
        captured = {
            p: c.get(p).text for p in ["/mail/m/m-meeting-context", "/chat/renewal-planning"]
        }
        results, _ = verify(base, goal, captured, [])
        assert results[0].result == "unknown"
