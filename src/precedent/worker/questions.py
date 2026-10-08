"""An asynchronous, run-specific human channel. Only the runner emits answer events."""

from __future__ import annotations

import asyncio
import json
import time

from precedent.worker.events import EventLog


class FileHuman:
    def __init__(self, log: EventLog, timeout: float = 600):
        self.log, self.timeout = log, timeout

    async def __call__(self, question: str, options: list[str]) -> dict:
        key = f"q{self.log.seq}"
        path = self.log.dir / "answers" / f"{key}.json"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if path.exists() and not path.is_symlink():
                try:
                    answer = json.loads(path.read_text())
                    if answer.get("question_id") == key and isinstance(answer.get("text"), str):
                        return {"text": answer["text"], "by": "human"}
                except (ValueError, OSError):
                    pass  # a writer may not have finished flushing its file yet
            await asyncio.sleep(0.3)
        return {
            "text": "No answer arrived within the question window. Finish as blocked.",
            "by": "system",
        }
