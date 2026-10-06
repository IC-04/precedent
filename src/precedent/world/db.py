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
PRIMARY_KEYS = {"accounts": "code"}
INSERT_ONLY = {"mail_attachments", "audit_log"}  # no single-column key: never updated


class StaleWrite(Exception):
    """The row changed (or vanished) since the caller read it; nothing was written."""


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
    fields in `after` that differ from `before` are updated. Table and column
    names are checked against the schema. An update whose changed fields no
    longer match `before` raises StaleWrite, so a colleague's edit is not lost.
    """
    cols = _columns(conn, entity)
    unknown = set(after or {}) - cols
    if unknown:
        raise ValueError(f"unknown columns for {entity}: {sorted(unknown)}")
    if before is None and after is not None:
        names = ", ".join(after)
        marks = ", ".join("?" for _ in after)
        conn.execute(f"INSERT INTO {entity} ({names}) VALUES ({marks})", list(after.values()))
    else:
        if entity in INSERT_ONLY:
            raise ValueError(f"{entity} is insert-only")
        _update_or_delete(conn, entity, entity_id, before or {}, after)
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


def _columns(conn: sqlite3.Connection, entity: str) -> set[str]:
    cols = {r[1] for r in conn.execute("SELECT * FROM pragma_table_info(?)", [entity])}
    if not cols:
        raise ValueError(f"unknown table {entity!r}")
    return cols


def _update_or_delete(
    conn: sqlite3.Connection,
    entity: str,
    entity_id: str,
    before: dict[str, Any],
    after: dict[str, Any] | None,
) -> None:
    """Refuse to write over a row that differs from what the caller saw (lost update)."""
    pk = PRIMARY_KEYS.get(entity, "id")
    current = row(conn, entity, entity_id)
    if current is None:
        raise StaleWrite(f"{entity} {entity_id} does not exist")
    if after is None:
        conn.execute(f"DELETE FROM {entity} WHERE {pk} = ?", [entity_id])
        return
    changed = {k: v for k, v in after.items() if before.get(k) != v}
    stale = [k for k in changed if k in before and current[k] != before[k]]
    if stale:
        raise StaleWrite(f"{entity} {entity_id} changed since it was read: {stale}")
    if changed:
        sets = ", ".join(f"{k} = ?" for k in changed)
        conn.execute(f"UPDATE {entity} SET {sets} WHERE {pk} = ?", [*changed.values(), entity_id])


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
