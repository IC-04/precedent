"""Encrypted local records. Artifact changes use the existing audited write path."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet

from precedent.world.db import connect, write

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, app TEXT, action TEXT,
 entity TEXT, entity_id TEXT, before_json TEXT, after_json TEXT);
"""


class Vault:
    def __init__(self, root: Path, key_path: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        key_path = key_path.expanduser().resolve()
        if key_path == self.root or self.root in key_path.parents:
            raise ValueError("Encryption key must live outside connected storage")
        key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if key_path.stat().st_mode & 0o077:
                raise ValueError("Credential key permissions must be 0600") from None
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        self.path = self.root / "connected.sqlite"
        self.lock = threading.RLock()
        with connect(self.path) as conn:
            conn.executescript(SCHEMA)
        os.chmod(self.path, 0o600)
        if not self.get("owner"):
            self.put("owner", {"id": secrets.token_hex(16), "session": secrets.token_urlsafe(32)})

    def get(self, key: str):
        with self.lock, connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM records WHERE id=?", [key]).fetchone()
            return json.loads(self.cipher.decrypt(row[0].encode())) if row else None

    def put(self, key: str, value: dict, actor: str = "owner"):
        with self.lock, connect(self.path) as conn:
            row = conn.execute("SELECT * FROM records WHERE id=?", [key]).fetchone()
            after = {"id": key, "payload": self.cipher.encrypt(json.dumps(value).encode()).decode()}
            write(
                conn,
                actor,
                "connected",
                "record.save",
                "records",
                key,
                dict(row) if row else None,
                after,
            )

    def delete(self, key: str):
        with self.lock, connect(self.path) as conn:
            row = conn.execute("SELECT * FROM records WHERE id=?", [key]).fetchone()
            if row:
                # Remove historical ciphertext too: forgetting data includes audit payloads.
                conn.execute("DELETE FROM audit_log WHERE entity_id=?", [key])
                conn.execute("DELETE FROM records WHERE id=?", [key])

    def consume(self, key: str):
        with self.lock:
            result = self.get(key)
            self.delete(key)
            if result and result.get("expires", 0) > time.time():
                return result
        return None

    def delete_prefix(self, prefix: str):
        with self.lock, connect(self.path) as conn:
            keys = [r[0] for r in conn.execute("SELECT id FROM records") if r[0].startswith(prefix)]
        for key in keys:
            self.delete(key)

    def list(self, prefix: str):
        with self.lock, connect(self.path) as conn:
            keys = [r[0] for r in conn.execute("SELECT id FROM records") if r[0].startswith(prefix)]
            values = []
            for key in keys:
                value = self.get(key)
                if value.get("expires", float("inf")) <= time.time():
                    self.delete(key)
                else:
                    values.append(value)
            return values

    def identity(self):
        owner = self.get("owner")
        grants = [self.get("connection:" + p) or {} for p in ("gmail", "slack")]
        binding = owner["id"] + ":" + ":".join(g.get("generation", "none") for g in grants)
        return hashlib.sha256(binding.encode()).hexdigest()[:32]

    def ticket(self):
        ticket = secrets.token_urlsafe(32)
        self.put("ticket:" + ticket, {"expires": time.time() + 300})
        return ticket

    def authenticated(self, value: str | None):
        return bool(value) and secrets.compare_digest(value, self.get("owner")["session"])
