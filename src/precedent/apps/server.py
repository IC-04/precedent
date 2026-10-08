"""Serve a generated company's Mail, Books, Drive and Chat apps with scenario hooks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from precedent.apps import books, chat, drive, mail, scenario
from precedent.apps.common import render
from precedent.world.db import WORLDS, world_dir
from precedent.world.params import load_template


def create_app(seed: int, root: Path = WORLDS) -> FastAPI:
    world = world_dir(seed, root)
    if not (world / "world.db").exists():
        raise FileNotFoundError(f"No world at {world}. Run: precedent world --seed {seed}")
    app = FastAPI(title="Company apps", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.world = world
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
    }
    app.state.console_url = os.getenv("PRECEDENT_CONSOLE_URL", "http://localhost:8000")
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    app.state.labels = {}  # field -> label override (scenario hook)
    app.state.drop_next = set()  # POST paths whose next response is dropped
    for module in (mail, books, drive, chat, scenario):
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
                    app.state.console_url + "/workspace-status", params={"seed": seed}
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            return {"seed": seed, "run": None, "unavailable": True}

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
            return {**app.state.company, "documents": documents}
        finally:
            connections.close()

    return app
