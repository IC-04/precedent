"""Audited company scheduling persistence, shared by Mail and Calendar UI."""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request

from precedent.scheduling import instant, intent_key, suitable
from precedent.world import db


def settings(conn):
    row = conn.execute("SELECT * FROM scheduling_settings WHERE id='company'").fetchone()
    if row is None:
        raise ValueError(
            "Calendar needs a newly generated company. Existing company data is preserved."
        )
    return dict(row)


def contacts(conn):
    return [
        dict(r) for r in conn.execute("SELECT * FROM employees WHERE id != 'ava' ORDER BY name")
    ]


def calendars(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM calendars ORDER BY name")]


def events(conn, owners=None):
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT e.*, c.owner_id, c.name AS calendar_name FROM calendar_events e "
            "JOIN calendars c ON c.id=e.calendar_id WHERE c.readable=1 AND e.status!='cancelled' "
            "ORDER BY e.start_at,e.id"
        )
    ]
    return [r for r in rows if owners is None or r["owner_id"] in owners]


def actor(request: Request):
    return "ava" if request.headers.get("x-precedent-agent") else "human"


def mutation(conn, request, table, row, before=None):
    db.write(
        conn,
        actor(request),
        "mail" if table == "mail_drafts" else "calendar",
        ("draft" if table == "mail_drafts" else "event") + (".update" if before else ".create"),
        table,
        row["id"],
        before,
        row,
    )


def draft_values(conn, form):
    cfg = settings(conn)
    person = conn.execute(
        "SELECT * FROM employees WHERE id=?", [str(form.get("recipient_id", ""))]
    ).fetchone()
    if person is None or person["id"] == cfg["organizer_id"]:
        raise ValueError("Choose a colleague from the directory")
    out = {
        k: str(form.get(k, "")).strip()
        for k in (
            "topic",
            "subject",
            "body",
            "range_start",
            "range_end",
            "timezone",
            "slot1",
            "slot2",
            "source_refs",
            "source_quotes",
        )
    }
    if not all(out.values()):
        raise ValueError(
            "Complete the draft, two time options, and source references before saving"
        )
    if out["timezone"] != cfg["timezone"]:
        raise ValueError("Use the displayed company scheduling timezone")
    duration = int(form.get("duration", 30))
    if not 15 <= duration <= 240:
        raise ValueError("Duration must be 15–240 minutes")
    span = (
        datetime.fromisoformat(out["range_end"]) - datetime.fromisoformat(out["range_start"])
    ).days
    if not 0 < span <= 31:
        raise ValueError("Choose a date range of 1–31 days")
    if any(
        len(out[k]) > limit
        for k, limit in [
            ("body", 12000),
            ("subject", 200),
            ("topic", 140),
            ("source_refs", 2000),
            ("source_quotes", 4000),
        ]
    ):
        raise ValueError("The draft is too long")
    paths = out["source_refs"].splitlines()
    if not all(re.fullmatch(r"/(mail/m|chat)/[A-Za-z0-9_.-]+", p.strip()) for p in paths):
        raise ValueError("Use one local Mail message or Chat channel path per line")
    source_text = []
    for path in paths:
        key = path.strip().rsplit("/", 1)[-1]
        if path.startswith("/mail/m/"):
            row = conn.execute("SELECT body FROM mail_messages WHERE id=?", [key]).fetchone()
            if row:
                source_text.append(row[0])
        else:
            source_text.extend(
                row[0]
                for row in conn.execute(
                    "SELECT m.body FROM chat_messages m JOIN chat_channels c ON c.id=m.channel_id "
                    "WHERE c.name=?",
                    [key],
                )
            )
    quotes = [q.strip() for q in out["source_quotes"].splitlines() if q.strip()]

    def normalized(text):
        return " ".join(text.casefold().split())

    if len(quotes) < 2:
        raise ValueError("Add at least two short supporting quotes.")
    for quote in quotes:
        if len(quote) < 12 or not any(
            normalized(quote) in normalized(source) for source in source_text
        ):
            raise ValueError(
                f"Supporting quote is not in the linked source: {quote!r}. "
                "Read the source again and copy its exact words."
            )
        if normalized(quote) not in normalized(out["body"]):
            raise ValueError(
                f"The Message field does not contain this Supporting quote verbatim: "
                f"{quote!r}. Keep this form open. Either include those exact words "
                "in Message or shorten Supporting quotes to exact factual phrases "
                "present in BOTH the Message and source. Do not create a new draft."
            )
    for field in ("slot1", "slot2"):
        a = instant(out[field], out["timezone"])
        b = a + timedelta(minutes=duration)
        if not suitable(
            a.isoformat(),
            b.isoformat(),
            [],
            out["timezone"],
            out["range_start"],
            out["range_end"],
            duration,
            cfg["work_start"],
            cfg["work_end"],
        ):
            raise ValueError("Proposed times must fit the date range and working hours")
        out[field] = a.isoformat()
    if out["slot1"] == out["slot2"]:
        raise ValueError("Choose two distinct options")
    return {
        **out,
        "organizer_id": cfg["organizer_id"],
        "recipient_id": person["id"],
        "recipient_email": person["email"],
        "duration": duration,
        "status": "draft",
        "intent_key": intent_key(
            cfg["organizer_id"], person["id"], out["topic"], out["range_start"], out["range_end"]
        ),
    }


def save_draft(conn, request, form, draft_id=None):
    values = draft_values(conn, form)
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = (
            conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft_id]).fetchone()
            if draft_id
            else None
        )
        if draft_id and before is None:
            raise ValueError("Draft no longer exists")
        if before and int(form.get("version", 0)) != before["version"]:
            raise ValueError("Someone edited this draft. Reopen it before making changes.")
        existing = conn.execute(
            "SELECT id FROM mail_drafts WHERE intent_key=?", [values["intent_key"]]
        ).fetchone()
        if existing and existing["id"] != draft_id:
            raise ValueError(
                f"This meeting already has draft {existing['id']}. "
                "Open Drafts and review it before retrying."
            )
        stamp = datetime.now(UTC).isoformat()
        row = {
            **values,
            "id": draft_id or "draft-" + uuid.uuid4().hex[:12],
            "version": before["version"] + 1 if before else 1,
            "created_by": before["created_by"] if before else actor(request),
            "created_at": before["created_at"] if before else stamp,
            "updated_by": actor(request),
            "updated_at": stamp,
        }
        mutation(conn, request, "mail_drafts", row, dict(before) if before else None)
        conn.commit()
        return row["id"]
    except (ValueError, sqlite3.Error):
        conn.rollback()
        raise


def save_event(conn, request, form, event_id=None):
    cfg = settings(conn)
    cal = conn.execute("SELECT * FROM calendars WHERE id=?", [form.get("calendar_id")]).fetchone()
    if cal is None or not cal["writable"] or cal["owner_id"] != cfg["organizer_id"]:
        raise ValueError("Only the organizer's calendar can be changed")
    a, b = (
        instant(str(form.get("start_at", "")), cfg["timezone"]),
        instant(str(form.get("end_at", "")), cfg["timezone"]),
    )
    if not timedelta(minutes=15) <= b - a <= timedelta(hours=8):
        raise ValueError("An event must last between 15 minutes and 8 hours")
    title = str(form.get("title", "")).strip()
    if not title or len(title) > 200:
        raise ValueError("Enter a title of 1–200 characters")
    draft_id = str(form.get("draft_id", "")).strip() or None
    participant = str(form.get("participant_id", "")).strip() or None
    if (
        participant
        and not conn.execute("SELECT id FROM employees WHERE id=?", [participant]).fetchone()
    ):
        raise ValueError("Unknown participant")
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = (
            conn.execute("SELECT * FROM calendar_events WHERE id=?", [event_id]).fetchone()
            if event_id
            else None
        )
        if event_id and (before is None or before["calendar_id"] != cal["id"]):
            raise ValueError("Event cannot be edited here")
        if before and int(form.get("version", 0)) != before["version"]:
            raise ValueError("Someone edited this event. Reopen it before changing it.")
        if draft_id:
            draft = conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft_id]).fetchone()
            if (
                draft is None
                or a.isoformat() not in (draft["slot1"], draft["slot2"])
                or b - a != timedelta(minutes=draft["duration"])
            ):
                raise ValueError("Choose an option from the linked draft")
            if participant != draft["recipient_id"]:
                raise ValueError("The participant must match the linked draft")
        busy = [e for e in events(conn, [cfg["organizer_id"], participant]) if e["id"] != event_id]
        from precedent.scheduling import overlap

        if any(overlap(a, b, instant(e["start_at"]), instant(e["end_at"])) for e in busy):
            raise ValueError("This time is now busy. Check availability again.")
        stamp = datetime.now(UTC).isoformat()
        row = dict(
            id=event_id or "event-" + uuid.uuid4().hex[:12],
            calendar_id=cal["id"],
            title=title,
            start_at=a.isoformat(),
            end_at=b.isoformat(),
            timezone=cfg["timezone"],
            all_day=0,
            status="tentative",
            participant_id=participant,
            draft_id=draft_id,
            version=before["version"] + 1 if before else 1,
            created_by=before["created_by"] if before else actor(request),
            updated_by=actor(request),
            created_at=before["created_at"] if before else stamp,
            updated_at=stamp,
        )
        mutation(conn, request, "calendar_events", row, dict(before) if before else None)
        conn.commit()
        return row["id"]
    except (ValueError, sqlite3.Error):
        conn.rollback()
        raise
