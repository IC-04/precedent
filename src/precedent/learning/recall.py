"""Curated ADK event index; registry status is authoritative at retrieval time."""

from __future__ import annotations

import json

from google.adk.events import Event
from google.adk.memory import SqliteMemoryService
from google.genai import types

from precedent.learning.store import Store


async def index_entries(store: Store, scope: str, entries: list[dict]):
    memory = SqliteMemoryService(store.root / "recall.sqlite", max_results=12)
    try:
        events = [
            Event(
                id=f"{e['id']}:{e['version']}",
                author="curated_learning",
                content=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=json.dumps(
                                {
                                    "id": e["id"],
                                    "version": e["version"],
                                    "title": e["title"],
                                    "lesson": e["payload"].get("lesson", ""),
                                }
                            )
                        )
                    ],
                ),
            )
            for e in entries
            if e["kind"] != "skill"
        ]
        if events:
            await memory.add_events_to_memory(
                app_name="precedent", user_id=scope, events=events, session_id="curated"
            )
    finally:
        await memory.close()


async def recall(store: Store, scope: str, query: str, run_id: str) -> list[dict]:
    memory = SqliteMemoryService(store.root / "recall.sqlite", max_results=12)
    result = []
    try:
        hits = await memory.search_memory(app_name="precedent", user_id=scope, query=query)
        seen = set()
        for hit in hits.memories:
            try:
                data = json.loads("".join(p.text or "" for p in hit.content.parts or []))
                item = store.get(scope, data["id"])
            except (ValueError, KeyError, TypeError):
                continue
            if (
                item["id"] in seen
                or item["version"] != data.get("version")
                or item["status"] not in ("observed", "needs_revalidation")
            ):
                continue
            seen.add(item["id"])
            store.record_retrieval(scope, run_id, item)
            result.append(item)
            if len(result) == 5:
                break
        return result
    finally:
        await memory.close()
