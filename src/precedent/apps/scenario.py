"""Scenario hooks for the demo and the evaluation harness. Never used by the worker.

Every call needs the X-Scenario-Token header to match PRECEDENT_SCENARIO_TOKEN.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from precedent.apps.common import get_conn
from precedent.world import db

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def require_token(x_scenario_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("PRECEDENT_SCENARIO_TOKEN")
    if not expected or x_scenario_token != expected:
        raise HTTPException(status_code=403, detail="Scenario token required.")


router = APIRouter(prefix="/__scenario", dependencies=[Depends(require_token)])


class Edit(BaseModel):
    entity: str
    id: str
    fields: dict[str, Any]
    actor: str
    app: str = "books"


@router.post("/edit")
def edit(change: Edit, conn: Conn) -> dict[str, Any]:
    """A colleague's edit, logged with the colleague as the actor."""
    try:
        db.columns(conn, change.entity)  # checks the table name before any SQL uses it
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown entity.") from None
    before = db.row(conn, change.entity, change.id)
    if before is None:
        raise HTTPException(status_code=404, detail="No such record.")
    try:
        db.write(
            conn,
            change.actor,
            change.app,
            f"{change.entity}.update",
            change.entity,
            change.id,
            before,
            {**before, **change.fields},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    conn.commit()
    return {"ok": True, "after": db.row(conn, change.entity, change.id)}


@router.post("/drop-next-response")
def drop_next_response(request: Request, path: str) -> dict[str, Any]:
    """The next POST to `path` commits its write, then answers 502."""
    request.app.state.drop_next.add(path)
    return {"ok": True, "armed": sorted(request.app.state.drop_next)}


@router.post("/relabel")
def relabel(request: Request, field: str, label: str) -> dict[str, Any]:
    """Change one form label; the input's name stays the same."""
    request.app.state.labels[field] = label
    return {"ok": True, "labels": request.app.state.labels}


@router.post("/deliver")
def deliver(request: Request, conn: Conn, item: str) -> dict[str, Any]:
    """Deliver a held-back item (a later act's mail and attachment) into the world."""
    world = request.app.state.world
    held = json.loads((world / "held" / "items.json").read_text())
    entry = next((i for i in held if i["id"] == item), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such held item.")
    for f in entry["files"]:  # check everything before touching disk or the database
        seen = conn.execute("SELECT 1 FROM files WHERE sha256 = ?", [f["sha256"]]).fetchone()
        if seen or (world / "files" / f["name"]).exists():
            raise HTTPException(status_code=409, detail="Already delivered.")
    file_ids = []
    for f in entry["files"]:
        dest = world / "files" / f["name"]
        shutil.copyfile(world / f["path"], dest)
        fid = _next(conn, "files", "f")
        db.write(
            conn,
            "system",
            "drive",
            "file.upload",
            "files",
            fid,
            None,
            {
                "id": fid,
                "folder": f["folder"],
                "name": f["name"],
                "mime": f["mime"],
                "path": f"files/{f['name']}",
                "uploaded_by": None,
                "uploaded_at": entry["mail"]["sent_at"],
                "sha256": f["sha256"],
            },
        )
        file_ids.append(fid)
    mid = _next(conn, "mail_messages", "m")
    mail = {
        **entry["mail"],
        "id": mid,
        "thread_id": f"t-{mid[2:]}",
        "folder": "inbox",
        "to_addr": conn.execute("SELECT email FROM employees WHERE id = 'ava'").fetchone()[0],
    }
    db.write(conn, "system", "mail", "mail.receive", "mail_messages", mid, None, mail)
    for fid in file_ids:
        db.write(
            conn,
            "system",
            "mail",
            "mail.attach",
            "mail_attachments",
            mid,
            None,
            {"message_id": mid, "file_id": fid},
        )
    conn.commit()
    return {"ok": True, "message_id": mid, "file_ids": file_ids}


def _next(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    ids = [r[0] for r in conn.execute(f"SELECT id FROM {table}")]
    n = (
        max(
            (
                int(i.split("-")[1])
                for i in ids
                if i.startswith(prefix + "-") and i.split("-", 1)[1].isdigit()
            ),
            default=0,
        )
        + 1
    )
    return f"{prefix}-{n:04d}"
