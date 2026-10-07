"""One FastAPI server for Northwind's apps: /mail, /books, /drive, /chat (+ /__scenario)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from precedent.apps import books, chat, drive, mail, scenario
from precedent.world.db import WORLDS, world_dir

LAUNCHER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Apps</title>
<style>body{font:15px/1.5 system-ui,sans-serif;margin:40px}a{display:block;margin:8px 0}</style>
</head><body><h1>Company apps</h1><p>Signed in as Ava (AP).</p>
<nav aria-label="Apps"><a href="/mail/">Mail: the accounts payable inbox</a>
<a href="/books/">Books: vendors, bills, approvals and history</a>
<a href="/drive/">Drive: policies and documents</a>
<a href="/chat/">Chat: team channels</a></nav></body></html>"""


def create_app(seed: int, root: Path = WORLDS) -> FastAPI:
    world = world_dir(seed, root)
    if not (world / "world.db").exists():
        raise FileNotFoundError(f"No world at {world}. Run: precedent world --seed {seed}")
    app = FastAPI(title="Company apps", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.world = world
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
    def home() -> str:
        """The company launcher: an employee's starting page with a link to each app."""
        return LAUNCHER

    return app
