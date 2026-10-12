"""Runtime identity, separate from deterministic generated company content."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def instance_id(world: Path) -> str:
    """Restart preserves identity; regeneration removes this sidecar and rotates it."""
    path = world / "instance.json"
    if not path.exists():
        value = uuid.uuid4().hex
        try:
            with path.open("x") as stream:
                stream.write(json.dumps({"instance_id": value}))
        except FileExistsError:
            pass
    value = json.loads(path.read_text())["instance_id"]
    if not isinstance(value, str) or len(value) != 32:
        raise ValueError("Invalid company instance identity")
    return value
