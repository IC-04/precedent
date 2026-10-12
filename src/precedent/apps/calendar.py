"""The company Calendar: visible availability, local tentative events and contacts."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from precedent.apps import meetings as data
from precedent.apps.common import get_conn, render, templates
from precedent.scheduling import instant, next_week, options

router = APIRouter(prefix="/calendar")
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def local(value, timezone):
    return instant(str(value), timezone).astimezone(ZoneInfo(timezone))


def local_input(value, timezone):
    return local(value, timezone).strftime("%Y-%m-%dT%H:%M") if value else ""


templates.env.filters["calendar_time"] = lambda v, tz: local(v, tz).strftime("%a %d %b %Y, %H:%M")
templates.env.filters["local_input"] = local_input


def context(conn):
    cfg = data.settings(conn)
    people = data.contacts(conn)
    organizer = next(p for p in people if p["id"] == cfg["organizer_id"])
    return dict(cfg=cfg, contacts=people, organizer=organizer, calendars=data.calendars(conn))


@router.get("/")
def week(request: Request, conn: Conn, start: str = "", owner: str = ""):
    try:
        ctx = context(conn)
    except ValueError as exc:
        return render(request, "calendar/unavailable.html", error=str(exc))
    cfg = ctx["cfg"]
    try:
        first = date.fromisoformat(start or cfg["reference_date"])
    except ValueError:
        first = date.fromisoformat(cfg["reference_date"])
    first -= timedelta(days=first.weekday())
    days = [first + timedelta(days=i) for i in range(5)]
    events = data.events(conn, [owner] if owner else None)
    shown = []
    for event in events:
        a, b = local(event["start_at"], cfg["timezone"]), local(event["end_at"], cfg["timezone"])
        if a.date() < first + timedelta(days=7) and b.date() >= first:
            shown.append({**event, "local_start": a, "local_end": b})
    return render(
        request,
        "calendar/week.html",
        **ctx,
        days=days,
        events=shown,
        owner=owner,
        first=first.isoformat(),
        prev=(first - timedelta(days=7)).isoformat(),
        next=(first + timedelta(days=7)).isoformat(),
        next_week=next_week(cfg["reference_date"])[0],
    )


@router.get("/context")
def directory(request: Request, conn: Conn):
    try:
        return render(request, "calendar/context.html", **context(conn))
    except ValueError as exc:
        return render(request, "calendar/unavailable.html", error=str(exc), code=409)


@router.get("/availability")
def availability(
    request: Request,
    conn: Conn,
    recipient: str = "",
    start: str = "",
    end: str = "",
    duration: int = 30,
):
    ctx = context(conn)
    cfg = ctx["cfg"]
    default_start, default_end = next_week(cfg["reference_date"])
    start, end = start or default_start, end or default_end
    chosen = next((p for p in ctx["contacts"] if p["id"] == recipient), None)
    readable = {c["owner_id"] for c in ctx["calendars"] if c["readable"]}
    owners = [cfg["organizer_id"], recipient] if chosen else [cfg["organizer_id"]]
    coverage = "mutual" if chosen and all(p in readable for p in owners) else "organizer only"
    rows = data.events(conn, owners)
    # Whole-range event rows remain visible, including all-day and boundary overlaps.
    scoped = [
        e
        for e in rows
        if local(e["start_at"], cfg["timezone"]).date().isoformat() < end
        and local(e["end_at"], cfg["timezone"]).date().isoformat() >= start
    ]
    error = None
    try:
        if cfg["organizer_id"] not in readable:
            coverage = "unavailable"
            raise ValueError("The organizer calendar is not accessible; availability is unknown")
        free = options(
            scoped, cfg["timezone"], start, end, duration, cfg["work_start"], cfg["work_end"]
        )
    except ValueError as exc:
        free, error = [], str(exc)
    return render(
        request,
        "calendar/availability.html",
        **ctx,
        recipient=recipient,
        chosen=chosen,
        start=start,
        end=end,
        duration=duration,
        coverage=coverage,
        events=scoped,
        options=[
            o
            for day in dict.fromkeys(x["start"][:10] for x in free)
            for o in [x for x in free if x["start"].startswith(day)][:2]
        ][:12],
        total_options=len(free),
        error=error,
    )


@router.get("/new")
def new(request: Request, conn: Conn, draft: str = "", option: int = 1):
    ctx = context(conn)
    values = {
        "calendar_id": "cal-" + ctx["cfg"]["organizer_id"],
        "timezone": ctx["cfg"]["timezone"],
    }
    if draft:
        row = conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft]).fetchone()
        if row:
            a = local(row["slot1" if option == 1 else "slot2"], row["timezone"])
            values.update(
                title=row["topic"].capitalize(),
                start_at=a.isoformat(),
                end_at=(a + timedelta(minutes=row["duration"])).isoformat(),
                draft_id=draft,
                participant_id=row["recipient_id"],
            )
    return render(request, "calendar/form.html", **ctx, values=values, error=None, event_id=None)


@router.get("/events/{event_id}")
def detail(request: Request, conn: Conn, event_id: str):
    row = conn.execute("SELECT * FROM calendar_events WHERE id=?", [event_id]).fetchone()
    if row is None:
        return render(request, "calendar/unavailable.html", error="Event not found", code=404)
    return render(
        request,
        "calendar/event.html",
        **context(conn),
        event=dict(row),
        ava_context={"kind": "event", "id": event_id, "label": row["title"]},
    )


@router.get("/events/{event_id}/edit")
def edit(request: Request, conn: Conn, event_id: str):
    row = conn.execute("SELECT * FROM calendar_events WHERE id=?", [event_id]).fetchone()
    if row is None:
        return render(request, "calendar/unavailable.html", error="Event not found", code=404)
    return render(
        request,
        "calendar/form.html",
        **context(conn),
        values=dict(row),
        error=None,
        event_id=event_id,
    )


@router.post("/new")
@router.post("/events/{event_id}/edit")
async def save(request: Request, conn: Conn, event_id: str | None = None):
    form = dict(await request.form())
    try:
        eid = data.save_event(conn, request, form, event_id)
    except (ValueError, sqlite3.IntegrityError) as exc:
        return render(
            request,
            "calendar/form.html",
            **context(conn),
            values=form,
            error=str(exc),
            event_id=event_id,
            code=409,
        )
    return RedirectResponse(f"/calendar/events/{eid}", 303)
