"""Chat: channels and messages. Ava can post (questions, notes to Finance)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from precedent.apps.common import ACTOR, get_conn, people, redirect, render, write

router = APIRouter(prefix="/chat")
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _channels(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM chat_channels ORDER BY name").fetchall()


@router.get("/")
def home(conn: Conn) -> RedirectResponse:
    first = _channels(conn)[0]["name"]
    return RedirectResponse(f"/chat/{first}")


def _channel_page(
    request: Request, conn: sqlite3.Connection, name: str, error: str | None = None, code: int = 200
):
    channel = conn.execute("SELECT * FROM chat_channels WHERE name = ?", [name]).fetchone()
    if channel is None:
        return render(
            request,
            "chat/channel.html",
            code=404,
            channel=None,
            channels=_channels(conn),
            messages=[],
            names={},
            roles={},
            error=None,
        )
    messages = conn.execute(
        "SELECT * FROM chat_messages WHERE channel_id = ? ORDER BY posted_at, id",
        [channel["id"]],
    ).fetchall()
    return render(
        request,
        "chat/channel.html",
        code=code,
        channel=channel,
        channels=_channels(conn),
        messages=messages,
        names=people(conn),
        roles={r["id"]: r["role"] for r in conn.execute("SELECT id, role FROM employees")},
        error=error,
    )


@router.get("/{name}")
def channel(request: Request, conn: Conn, name: str):
    return _channel_page(request, conn, name)


@router.post("/{name}")
async def post(request: Request, conn: Conn, name: str):
    channel = conn.execute("SELECT * FROM chat_channels WHERE name = ?", [name]).fetchone()
    if channel is None:
        return _channel_page(request, conn, name)
    body = str((await request.form()).get("body", "")).strip()
    if not body:
        return _channel_page(request, conn, name, error="Write a message first.", code=400)
    ids = [
        int(r[0].split("-")[1])
        for r in conn.execute("SELECT id FROM chat_messages")
        if r[0].startswith("cm-") and r[0][3:].isdigit()
    ]
    mid = f"cm-{max(ids, default=0) + 1:04d}"
    now = datetime.now(UTC).isoformat(timespec="seconds")
    write(
        conn,
        "chat",
        "message.post",
        "chat_messages",
        mid,
        None,
        {
            "id": mid,
            "channel_id": channel["id"],
            "author_id": ACTOR,
            "body": body,
            "posted_at": now,
        },
    )
    return redirect(f"/chat/{name}", "message_posted")
