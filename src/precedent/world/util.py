"""Small helpers shared by the generator modules."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path


def iso(d: date | datetime) -> str:
    if isinstance(d, datetime):
        return d.isoformat(timespec="seconds")
    return d.isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initials(name: str) -> str:
    words = [w for w in name.replace(".", " ").split() if w[0].isalnum()]
    if len(words) > 1:
        return "".join(w[0] for w in words[:3]).upper()
    return "".join(c for c in name if c.isalnum())[:3].upper()


def slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())
