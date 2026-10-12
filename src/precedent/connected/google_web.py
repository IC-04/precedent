"""Provider-backed working surfaces. Native changes are explicit form submissions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from precedent.connected.google import digest
from precedent.connected.providers import ProviderError
from precedent.connected.verify import inspect


def register(app, service, render, runs_root):
    @app.get("/mail")
    async def mail(request: Request, q: str = ""):
        return render(request, "mail", result=await service.search(q), query=q)

    @app.get("/mail/threads/{thread_id}")
    async def thread(request: Request, thread_id: str):
        return render(request, "thread", thread=await service.thread(thread_id))

    @app.get("/mail/compose")
    async def compose(
        request: Request, thread: str, start: str = "", end: str = "", duration: int = 30
    ):
        data = await service.thread(thread)
        schedule = await service.availability(start, end, duration) if start else None
        return render(
            request,
            "compose",
            thread=data,
            schedule=schedule,
            source_versions=digest(
                [
                    {"id": m["message_id"], "version": m["version"]}
                    for m in data["sources"]
                    if "DRAFT" not in m["labels"]
                ]
            ),
        )

    @app.get("/mail/drafts/{artifact_id}/edit")
    async def edit(request: Request, artifact_id: str):
        op = service.artifact(artifact_id)
        if not op or op["kind"] != "gmail_draft" or not op.get("native_id"):
            raise HTTPException(404)
        native = await service.read_draft(op["native_id"])
        s = op.get("schedule")
        schedule = await service.availability(s["start"], s["end"], s["duration"]) if s else None
        thread = await service.thread(op["thread"])
        return render(
            request,
            "compose",
            thread=thread,
            source_versions=digest(
                [
                    {"id": m["message_id"], "version": m["version"]}
                    for m in thread["sources"]
                    if "DRAFT" not in m["labels"]
                ]
            ),
            schedule=schedule,
            editing=op,
            native=native,
        )

    @app.post("/mail/drafts/save")
    async def save(request: Request):
        fields = dict(await request.form())
        try:
            if not fields.get("source_versions"):
                raise ValueError("Reopen the current conversation's draft form before saving.")
            fields["_trusted_request"] = (
                request.state.worker_grant["request"] if request.state.worker else ""
            )
            if fields.get("slot1") or fields.get("slot2"):
                fields["options"] = json.dumps(
                    [json.loads(fields["slot1"]), json.loads(fields["slot2"])]
                )
            op = await service.save_draft(fields, "ava" if request.state.worker else "owner")
            return RedirectResponse("/native/" + op["id"], 303)
        except (ProviderError, ValueError, KeyError) as exc:
            response = render(request, "workspace", artifacts=service.artifacts(), error=str(exc))
            response.status_code = 409
            return response

    @app.get("/calendar")
    async def calendar(request: Request, start: str = "", end: str = "", duration: int = 30):
        choices = await service.calendars()
        grant = await service.grant("gmail")
        if not grant.get("calendar_id"):
            return render(request, "calendar_select", calendars=choices)
        availability = await service.availability(start, end, duration)
        events = await service.events(availability["start"], availability["end"])
        return render(request, "calendar", schedule=availability, events=events)

    @app.post("/google/calendar/select")
    async def select_calendar(request: Request):
        await service.select_calendar(str((await request.form()).get("calendar", "")))
        return RedirectResponse("/calendar", 303)

    @app.get("/calendar/reserve")
    async def reserve_form(request: Request, draft: str = ""):
        artifact = service.artifact(draft) if draft else None
        return render(
            request, "reserve", artifact=artifact or {}, calendar=await service.calendar()
        )

    @app.post("/calendar/events/save")
    async def reserve(request: Request):
        if request.state.worker and not request.state.worker_grant.get("allow_event"):
            raise HTTPException(403, "The assigned task does not authorize a Calendar reservation.")
        try:
            op = await service.reserve(
                dict(await request.form()), "ava" if request.state.worker else "owner"
            )
            return RedirectResponse("/native/" + op["id"], 303)
        except (ProviderError, ValueError, KeyError) as exc:
            response = render(request, "workspace", artifacts=service.artifacts(), error=str(exc))
            response.status_code = 409
            return response

    @app.get("/native/{artifact_id}")
    async def native(request: Request, artifact_id: str):
        artifact = await service.reconcile(artifact_id)
        if not artifact:
            raise HTTPException(404)
        if artifact.get("native_id") and artifact["kind"] == "gmail_draft":
            await service.thread(artifact["thread"])
            native = await service.read_draft(artifact["native_id"])
        elif artifact.get("native_id"):
            native = (await inspect(service, artifact_id)).get("native", {})
        else:
            native = {}
        return render(request, "native", artifact=artifact, native=native)

    @app.get("/native/{artifact_id}/proof")
    async def proof(artifact_id: str):
        return await inspect(service, artifact_id)

    @app.get("/mind")
    def mind(request: Request):
        from precedent.learning.store import Store

        entries = Store(runs_root.parent / "learning").list(
            "google:" + service.stable_id() + ":ava"
        )
        return render(request, "mind", entries=entries)

    @app.post("/mind/preferences")
    async def preferences(request: Request):
        values = await request.form()
        start, end = int(values["work_start"]), int(values["work_end"])
        if not 0 <= start < end <= 23:
            raise HTTPException(400, "Choose valid working hours.")
        service.vault.put(
            "preferences:" + service.stable_id(),
            dict(work_start=start, work_end=end, approved=datetime.now(UTC).isoformat()),
        )
        return RedirectResponse("/mind", 303)

    @app.post("/mind/{entry_id}/skill")
    def candidate(entry_id: str):
        from precedent.learning.store import Store

        try:
            Store(runs_root.parent / "learning").draft_skill(
                "google:" + service.stable_id() + ":ava", entry_id
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from None
        return RedirectResponse("/mind", 303)
