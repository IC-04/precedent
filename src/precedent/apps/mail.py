"""Mail: the AP inbox. Read-only for the worker; attachments open in Drive."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from precedent.apps.common import get_conn, paginate, render

router = APIRouter(prefix="/mail")
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


@router.get("/")
def inbox(request: Request, conn: Conn, q: str = "", page: int = 1):
    where, params = "1 = 1", []
    if q:
        where = "(subject LIKE ? OR body LIKE ? OR from_name LIKE ? OR from_addr LIKE ?)"
        params = [f"%{q}%"] * 4
    sql = (
        "SELECT m.*, (SELECT count(*) FROM mail_attachments a WHERE a.message_id = m.id)"
        f" AS n_files FROM mail_messages m WHERE {where} ORDER BY sent_at DESC, id DESC"
    )
    rows, has_next, page = paginate(conn, sql, params, page)
    return render(request, "mail/inbox.html", rows=rows, q=q, page=page, has_next=has_next)


@router.get("/m/{mid}")
def message(request: Request, conn: Conn, mid: str):
    msg = conn.execute("SELECT * FROM mail_messages WHERE id = ?", [mid]).fetchone()
    if msg is None:
        return render(
            request, "mail/inbox.html", code=404, rows=[], q="", page=1, has_next=False, missing=mid
        )
    files = conn.execute(
        "SELECT f.* FROM mail_attachments a JOIN files f ON f.id = a.file_id"
        " WHERE a.message_id = ? ORDER BY f.name",
        [mid],
    ).fetchall()
    thread = conn.execute(
        "SELECT id, from_name, subject, sent_at FROM mail_messages WHERE thread_id = ?"
        " AND id != ? ORDER BY sent_at",
        [msg["thread_id"], mid],
    ).fetchall()
    # The sender's address is visible on the page; name the vendor only on an exact match.
    vendor = conn.execute(
        "SELECT name FROM vendors WHERE lower(email) = lower(?) AND status = 'active'",
        [msg["from_addr"] or ""],
    ).fetchone()
    return render(
        request,
        "mail/message.html",
        msg=msg,
        files=files,
        thread=thread,
        sender_vendor=vendor["name"] if vendor else None,
    )


# Persisted company email drafts. Task handoffs remain a separate human-only feature.
@router.get("/drafts")
def drafts(request: Request, conn: Conn, q: str = ""):
    rows = conn.execute(
        (
            "SELECT * FROM mail_drafts WHERE subject LIKE ? OR topic LIKE ? "
            "OR recipient_email LIKE ? ORDER BY updated_at DESC"
        ),
        [f"%{q}%"] * 3,
    ).fetchall()
    return render(request, "mail/drafts.html", rows=rows, q=q)


@router.get("/drafts/new")
def new_draft(request: Request, conn: Conn):
    from precedent.apps.calendar import context
    from precedent.scheduling import next_week

    try:
        ctx = context(conn)
    except ValueError as exc:
        return render(request, "calendar/unavailable.html", error=str(exc), code=409)
    start, end = next_week(ctx["cfg"]["reference_date"])
    return render(
        request,
        "mail/draft_form.html",
        **ctx,
        values={
            "timezone": ctx["cfg"]["timezone"],
            "duration": 30,
            "range_start": start,
            "range_end": end,
        },
        draft_id=None,
        error=None,
    )


@router.get("/drafts/{draft_id}")
def draft_detail(request: Request, conn: Conn, draft_id: str):
    from precedent.apps.calendar import context

    row = conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft_id]).fetchone()
    if row is None:
        return render(request, "calendar/unavailable.html", error="Draft not found", code=404)
    hold = conn.execute(
        "SELECT * FROM calendar_events WHERE draft_id=? AND status!='cancelled'", [draft_id]
    ).fetchone()
    return render(
        request,
        "mail/draft.html",
        **context(conn),
        draft=dict(row),
        hold=hold,
        ava_context={"kind": "draft", "id": draft_id, "label": row["subject"]},
    )


@router.get("/drafts/{draft_id}/edit")
def edit_draft(request: Request, conn: Conn, draft_id: str):
    from precedent.apps.calendar import context

    row = conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft_id]).fetchone()
    if row is None:
        return render(request, "calendar/unavailable.html", error="Draft not found", code=404)
    return render(
        request,
        "mail/draft_form.html",
        **context(conn),
        values=dict(row),
        draft_id=draft_id,
        error=None,
    )


@router.post("/drafts/new")
@router.post("/drafts/{draft_id}/edit")
async def save_draft(request: Request, conn: Conn, draft_id: str | None = None):
    from fastapi.responses import RedirectResponse

    from precedent.apps import meetings
    from precedent.apps.calendar import context

    form = dict(await request.form())
    try:
        did = meetings.save_draft(conn, request, form, draft_id)
    except (ValueError, sqlite3.IntegrityError) as exc:
        return render(
            request,
            "mail/draft_form.html",
            **context(conn),
            values=form,
            draft_id=draft_id,
            error=str(exc),
            code=409,
        )
    return RedirectResponse(f"/mail/drafts/{did}", 303)


@router.post("/drafts/{draft_id}/discard")
async def discard_draft(request: Request, conn: Conn, draft_id: str):
    from fastapi.responses import RedirectResponse

    from precedent.apps.meetings import actor
    from precedent.world import db

    form = await request.form()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM mail_drafts WHERE id=?", [draft_id]).fetchone()
    if row is None or str(row["version"]) != str(form.get("version")):
        conn.rollback()
        return render(
            request,
            "calendar/unavailable.html",
            error="Draft changed. Reopen it before discarding.",
            code=409,
        )
    if conn.execute(
        "SELECT id FROM calendar_events WHERE draft_id=? AND status!='cancelled'", [draft_id]
    ).fetchone():
        conn.rollback()
        return render(
            request,
            "calendar/unavailable.html",
            error="This draft has a local hold. Keep its context or edit the draft instead.",
            code=409,
        )
    db.write(
        conn, actor(request), "mail", "draft.discard", "mail_drafts", draft_id, dict(row), None
    )
    conn.commit()
    return RedirectResponse("/mail/drafts", 303)
