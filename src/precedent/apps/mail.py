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
    return render(request, "mail/message.html", msg=msg, files=files, thread=thread)
