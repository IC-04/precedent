"""The only write path into a world database. Every write appends to audit_log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).with_name("schema.sql")
WORLDS = Path("worlds")
PRIMARY_KEYS = {"accounts": "code", "mail_attachments": "message_id"}


def world_dir(seed: int, root: Path = WORLDS) -> Path:
    return root / str(seed)


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create(path: Path) -> sqlite3.Connection:
    """Create an empty world database with the schema."""
    if path.exists():
        path.unlink()
    conn = connect(path)
    conn.executescript(SCHEMA.read_text())
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write(
    conn: sqlite3.Connection,
    actor: str,
    app: str,
    action: str,
    entity: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    ts: str | None = None,
) -> None:
    """Apply one change to `entity` (a table) and record it in audit_log.

    before=None inserts `after`; after=None deletes the row; otherwise the
    fields in `after` that differ from `before` are updated.
    """
    pk = PRIMARY_KEYS.get(entity, "id")
    if before is None and after is not None:
        cols = ", ".join(after)
        marks = ", ".join("?" for _ in after)
        conn.execute(f"INSERT INTO {entity} ({cols}) VALUES ({marks})", list(after.values()))
    elif after is None:
        conn.execute(f"DELETE FROM {entity} WHERE {pk} = ?", [entity_id])
    else:
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if changed:
            sets = ", ".join(f"{k} = ?" for k in changed)
            conn.execute(
                f"UPDATE {entity} SET {sets} WHERE {pk} = ?", [*changed.values(), entity_id]
            )
    conn.execute(
        "INSERT INTO audit_log (ts, actor, app, action, entity, entity_id, before_json, after_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ts or _now(),
            actor,
            app,
            action,
            entity,
            entity_id,
            json.dumps(before, sort_keys=True) if before is not None else None,
            json.dumps(after, sort_keys=True) if after is not None else None,
        ],
    )


def row(conn: sqlite3.Connection, entity: str, entity_id: str) -> dict[str, Any] | None:
    pk = PRIMARY_KEYS.get(entity, "id")
    r = conn.execute(f"SELECT * FROM {entity} WHERE {pk} = ?", [entity_id]).fetchone()
    return dict(r) if r else None


def dump_sha(conn: sqlite3.Connection) -> str:
    """SHA-256 of the SQL dump: equal for equal content, independent of file layout."""
    h = hashlib.sha256()
    for line in conn.iterdump():
        h.update(line.encode())
        h.update(b"\n")
    return h.hexdigest()
