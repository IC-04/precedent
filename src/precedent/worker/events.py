"""The run's event log: runs/<run_id>/events.jsonl, one contracts.Event per line.

Events are the single source of truth for the console and the evaluation (D9).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from precedent.contracts import Event, EventType

RUNS = Path("runs")


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def task_id_for(seed: int, request: str) -> str:
    """Stable id for 'this request on this world', used to find an unfinished run."""
    key = f"{seed}:{' '.join(request.lower().split())}"
    return "t-" + hashlib.sha256(key.encode()).hexdigest()[:10]


class EventLog:
    def __init__(self, run_id: str, task_id: str | None = None, root: Path = RUNS):
        self.run_id, self.task_id = run_id, task_id
        self.dir = root / run_id
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.seq = len(read_events(self.path)) if self.path.exists() else 0

    def emit(self, type: EventType, **data: Any) -> Event:
        self.seq += 1
        event = Event(run_id=self.run_id, seq=self.seq, type=type, task_id=self.task_id, data=data)
        with self.path.open("a") as f:
            f.write(event.model_dump_json() + "\n")
            f.flush()
        return event


def read_events(path: Path) -> list[Event]:
    lines = path.read_text().splitlines() if path.exists() else []
    events = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(Event.model_validate_json(line))
        except ValueError:
            if index == len(lines) - 1 and not path.read_bytes().endswith(b"\n"):
                break  # the reader caught the writer partway through its last append
            raise
    return events


def unfinished_run(task_id: str, root: Path = RUNS) -> Path | None:
    """The newest run for this task that never wrote run_finished (it crashed or was killed)."""
    candidates = []
    for path in root.glob("*/events.jsonl"):
        events = read_events(path)
        if (
            events
            and events[0].task_id == task_id
            and not any(e.type == "run_finished" for e in events)
        ):
            candidates.append((events[0].ts, path.parent))
    return max(candidates)[1] if candidates else None
