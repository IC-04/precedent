"""Shared pieces for the company apps: database per request, rendering, parsing."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from precedent.world import db
from precedent.world.pdf import inr

ACTOR = "ava"  # the single signed-in user, "Ava (AP)"
PAGE_SIZE = 25

templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))

# Banner text after a redirect. The query string carries only a code, never free text.
DONE = {
    "bill_created": "Bill saved as a draft.",
    "bill_updated": "Bill updated.",
    "approval_requested": "Approval requested.",
    "vendor_created": "Vendor created.",
    "vendor_updated": "Vendor updated.",
    "vendor_retired": "Vendor retired.",
    "message_posted": "Message posted.",
}


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.world / "world.db")
    try:
        yield conn
    finally:
        conn.close()


def money(minor: int | None) -> str:
    if minor is None:
        return ""
    return f"{inr(minor)}.{abs(minor) % 100:02d}"


templates.env.filters["money"] = money


def render(request: Request, name: str, status: int = 200, **ctx: Any):
    labels = request.app.state.labels

    def label(field: str, default: str) -> str:
        return labels.get(field, default)

    ctx.update(banner=DONE.get(request.query_params.get("done", "")), label=label)
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def redirect(url: str, done: str) -> RedirectResponse:
    return RedirectResponse(f"{url}?done={done}", status_code=303)


def write(
    conn: sqlite3.Connection,
    app: str,
    action: str,
    entity: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Every UI write: through db.write() as Ava, committed at once."""
    db.write(conn, ACTOR, app, action, entity, entity_id, before, after)
    conn.commit()


def parse_amount(text: str) -> int:
    """'1,12,000', '112000', '₹1,12,000.00', 'INR 112000' -> minor units."""
    cleaned = re.sub(r"(?i)\b(inr|rs\.?)\b|₹|,|\s", "", text or "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Amount {text!r} is not a number.") from None
    if value <= 0:
        raise ValueError("Amount must be greater than zero.")
    return int((value * 100).to_integral_value())


def paginate(conn: sqlite3.Connection, sql: str, params: list[Any], page: int):
    """Rows for one page of 25, and whether a next page exists."""
    page = max(page, 1)
    rows = conn.execute(
        f"{sql} LIMIT ? OFFSET ?", [*params, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE]
    ).fetchall()
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE, page


def people(conn: sqlite3.Connection) -> dict[str, str]:
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM employees")}
    names["system"] = "System"
    return names


def activity(conn: sqlite3.Connection, entity: str, entity_id: str) -> list[dict[str, Any]]:
    """Audit entries for one record, oldest first, with the fields that changed."""
    names = people(conn)
    out = []
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE entity = ? AND entity_id = ? ORDER BY ts, id",
        [entity, entity_id],
    )
    for r in rows:
        before = json.loads(r["before_json"]) if r["before_json"] else {}
        after = json.loads(r["after_json"]) if r["after_json"] else {}
        changed = [
            f"{k}: {before.get(k) if before.get(k) is not None else '(empty)'} -> {v}"
            for k, v in after.items()
            if before and before.get(k) != v
        ]
        out.append(
            {
                "ts": r["ts"],
                "actor": names.get(r["actor"], r["actor"]),
                "action": r["action"],
                "changed": changed,
            }
        )
    return out
