"""Serve a generated company's Mail, Books, Drive and Chat apps with scenario hooks."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from precedent import companion
from precedent.apps import books, calendar, chat, drive, mail, scenario
from precedent.apps.common import render
from precedent.workspace import instance_id
from precedent.world.db import WORLDS, world_dir
from precedent.world.params import load_template


def create_app(seed: int, root: Path = WORLDS) -> FastAPI:
    world = world_dir(seed, root)
    if not (world / "world.db").exists():
        raise FileNotFoundError(f"No world at {world}. Run: precedent world --seed {seed}")
    app = FastAPI(title="Company apps", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.world = world
    from precedent.world.db import connect
    from precedent.world.meetings import ensure_schema

    with connect(world / "world.db") as connection:
        ensure_schema(connection)
    manifest = json.loads((world / "manifest.json").read_text())
    company = manifest.get("company")
    if not company:
        company = load_template(manifest["template"])["company"]
    app.state.company = {
        **{k: str(v) for k, v in company.items()},
        "seed": seed,
        "template": manifest["template"],
        "generated": True,
        "world_id": hashlib.sha256((world / "manifest.json").read_bytes()).hexdigest(),
        "instance_id": instance_id(world),
    }
    app.state.console_url = os.getenv("PRECEDENT_CONSOLE_URL", "http://localhost:8000")
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    app.state.labels = {}  # field -> label override (scenario hook)
    app.state.drop_next = set()  # POST paths whose next response is dropped
    for module in (mail, books, drive, chat, calendar, scenario):
        app.include_router(module.router)

    @app.middleware("http")
    async def drop_response(request: Request, call_next):
        """Scenario: commit the write, then lose the acknowledgement (uncertain write)."""
        path = request.url.path
        if request.method == "POST" and path in app.state.drop_next:
            app.state.drop_next.discard(path)
            await call_next(request)
            return HTMLResponse("<h1>502 Bad Gateway</h1>", status_code=502)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        """The company launcher: an employee's starting page with a link to each app."""
        from precedent.apps.common import get_conn

        connections = get_conn(request)
        conn = next(connections)
        try:

            def count(table):
                return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

            apps = [
                (
                    "Mail",
                    "/mail/",
                    "Invoices, handoffs and current company instructions.",
                    f"{count('mail_messages')} messages",
                ),
                (
                    "Books",
                    "/books/bills",
                    "Bills, vendors, approval requests and transaction history.",
                    f"{count('bills')} bills · {count('vendors')} vendors",
                ),
                (
                    "Drive",
                    "/drive/",
                    "Source invoices, policies and operating procedures.",
                    f"{count('files')} files",
                ),
                (
                    "Chat",
                    "/chat/",
                    "Conversations and colleague handoffs in company channels.",
                    f"{count('chat_channels')} channels",
                ),
            ]
            apps.insert(
                1,
                (
                    "Calendar",
                    "/calendar/",
                    "Find time, prepare meetings and keep local holds.",
                    f"{count('calendar_events')} events",
                ),
            )
            return render(request, "home.html", apps=apps)
        finally:
            connections.close()

    @app.get("/work-status")
    async def work_status(request: Request):
        if request.headers.get("x-precedent-agent"):
            # the console's state is for human viewers, never for the worker it describes
            return HTMLResponse("Not found", status_code=404)
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                response = await client.get(
                    app.state.console_url + "/workspace-status",
                    params={"seed": seed, "instance_id": app.state.company["instance_id"]},
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            return {"seed": seed, "run": None, "unavailable": True}

    # Ava's task drafts, handed to the console without the browser crossing origins:
    # a same-origin POST stores it here under a one-time token; the console fetches it
    # server-to-server from its configured company URL. Not a company record.
    app.state.handoffs = {}

    def human_request(request: Request) -> bool:
        if request.headers.get("x-precedent-agent"):
            return False  # the worker never sees or uses human assistance UI
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return False
        return request.headers.get("sec-fetch-site") not in ("cross-site", "same-site")

    @app.post("/ava/handoff")
    async def ava_handoff(request: Request):
        if not human_request(request):
            return JSONResponse({"detail": "Not available"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"detail": "Invalid draft"}, status_code=400)
        text = str(body.get("text", "")).strip() if isinstance(body, dict) else ""
        if not text or len(text) > 2000:
            return JSONResponse({"detail": "Write a draft of 1 to 2,000 characters."}, 400)
        now = time.monotonic()
        live = {k: v for k, v in app.state.handoffs.items() if now - v["created"] < 600}
        app.state.handoffs = dict(list(live.items())[-49:])
        token = secrets.token_urlsafe(24)
        app.state.handoffs[token] = {
            "text": text,
            "context": companion.clean_context(body.get("context")),
            "instance_id": app.state.company["instance_id"],
            "created": now,
        }
        return {"token": token}

    @app.get("/ava/handoff/{token}")
    def ava_handoff_read(request: Request, token: str):
        entry = (
            None
            if request.headers.get("x-precedent-agent")
            else app.state.handoffs.pop(token, None)
        )
        if entry is None or time.monotonic() - entry["created"] >= 600:
            return JSONResponse({"detail": "Draft not found or expired"}, status_code=404)
        return {k: entry[k] for k in ("text", "context", "instance_id")}

    @app.get("/workspace.json")
    def workspace(request: Request):
        """Public identity, used to bind console runs to the company actually served."""
        from precedent.apps.common import get_conn

        connections = get_conn(request)
        conn = next(connections)
        try:
            documents = [
                dict(row) for row in conn.execute("SELECT id, name FROM files ORDER BY name")
            ]
            meeting_example = None
            cfg = conn.execute("SELECT * FROM scheduling_settings WHERE id='company'").fetchone()
            message = conn.execute(
                "SELECT * FROM mail_messages WHERE id='m-meeting-context'"
            ).fetchone()
            if cfg and message:
                topic = message["subject"].removesuffix(" discussion").lower()
                meeting_example = (
                    f"Prepare a catch-up with {message['from_name']} next week about the {topic}. "
                    "Read our recent email and chat, find two suitable 30-minute times, and save "
                    "an email draft for me to review. Do not send it."
                )
            return {**app.state.company, "documents": documents, "meeting_example": meeting_example}
        finally:
            connections.close()

    return app
