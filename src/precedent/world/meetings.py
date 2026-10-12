"""Deterministic source-only meeting fixtures; no completed draft is seeded."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from precedent.contracts import ExpectedTask
from precedent.scheduling import instant, next_week
from precedent.world import db

SCHEMA = Path(__file__).with_name("meeting_schema.sql")


def ensure_schema(conn):
    conn.executescript(SCHEMA.read_text())


def seed(builder) -> list[ExpectedTask]:
    b = builder
    ensure_schema(b.conn)
    organizer, colleague = b.people["ap_clerk"], b.people["cfo"]
    tz = "Asia/Kolkata"
    ref = b.today.isoformat()
    start, end = next_week(ref)
    stamp = instant(ref + "T08:00", tz).isoformat()

    def add(table, row, app="calendar"):
        db.write(b.conn, "system", app, "fixture.create", table, row["id"], None, row, ts=stamp)

    add(
        "scheduling_settings",
        dict(
            id="company",
            organizer_id=organizer,
            timezone=tz,
            reference_date=ref,
            work_start=9,
            work_end=17,
        ),
    )
    for who in (organizer, colleague, b.people["design_lead"]):
        add(
            "calendars",
            dict(
                id="cal-" + who,
                owner_id=who,
                name=b.names[who],
                readable=1,
                writable=int(who == organizer),
            ),
        )
    for idx in range(10):
        day = datetime.fromisoformat(start) + timedelta(days=idx % 5)
        hour = 9 + (idx + b.seed) % 5
        a = day.replace(hour=hour)
        owner = organizer if idx % 2 else colleague
        add(
            "calendar_events",
            dict(
                id=f"event-seed-{idx}",
                calendar_id="cal-" + owner,
                title=["Team planning", "Customer review", "Focus time", "Weekly check-in"][
                    idx % 4
                ],
                start_at=instant(a.isoformat(), tz).isoformat(),
                end_at=instant((a + timedelta(hours=1)).isoformat(), tz).isoformat(),
                timezone=tz,
                all_day=0,
                status="confirmed",
                participant_id=None,
                draft_id=None,
                version=1,
                created_by="system",
                updated_by="system",
                created_at=stamp,
                updated_at=stamp,
            ),
        )
    topic = "vendor renewal" if b.seed == 7 else "software renewal"
    seats = 24 + b.seed % 7
    quote = f"We need to review {seats} unused seats before the {topic}."
    second = "Please compare the annual and monthly pricing before we decide."
    add(
        "mail_messages",
        dict(
            id="m-meeting-context",
            thread_id="renewal-planning",
            folder="inbox",
            from_name=b.names[colleague],
            from_addr=b.emails[colleague],
            to_addr=b.emails[organizer],
            subject=topic.capitalize() + " discussion",
            body=quote + "\n" + second,
            sent_at=stamp,
        ),
        "mail",
    )
    add("chat_channels", dict(id="renewal-planning", name="renewal-planning"), "chat")
    add(
        "chat_messages",
        dict(
            id="chat-meeting-context",
            channel_id="renewal-planning",
            author_id=colleague,
            body=f"For our {topic} catch-up: {second} {quote}",
            posted_at=stamp,
        ),
        "chat",
    )
    request = (
        f"Prepare a catch-up with {b.names[colleague]} next week about the {topic}. "
        "Read our recent email and chat, find two suitable 30-minute times, and save "
        "an email draft for me to review. Do not send it."
    )
    expected = dict(
        family="meeting",
        organizer_id=organizer,
        recipient_id=colleague,
        recipient_email=b.emails[colleague],
        topic=topic,
        range_start=start,
        range_end=end,
        duration=30,
        timezone=tz,
        required_facts=[f"{seats} unused seats", "annual and monthly pricing"],
        hold=False,
    )
    return [
        ExpectedTask(task_id="M1_prepare", request=request, expected=expected),
        ExpectedTask(
            task_id="M2_hold",
            request=request + " Also place a local tentative hold for the first proposed time.",
            expected={**expected, "hold": True},
        ),
    ]
