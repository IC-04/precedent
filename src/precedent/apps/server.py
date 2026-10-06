"""One FastAPI server for Northwind's apps: /mail, /books, /drive, /chat (+ /__scenario)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from precedent.apps import books
from precedent.world.db import WORLDS, world_dir


def create_app(seed: int, root: Path = WORLDS) -> FastAPI:
    world = world_dir(seed, root)
    if not (world / "world.db").exists():
        raise FileNotFoundError(f"No world at {world}. Run: precedent world --seed {seed}")
    app = FastAPI(title="Company apps", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.world = world
    app.state.labels = {}  # field -> label override (scenario hook)
    app.state.drop_next = set()  # POST paths whose next response is dropped
    app.include_router(books.router)

    @app.middleware("http")
    async def drop_response(request: Request, call_next):
        """Scenario: commit the write, then lose the acknowledgement (uncertain write)."""
        path = request.url.path
        if request.method == "POST" and path in app.state.drop_next:
            app.state.drop_next.discard(path)
            await call_next(request)
            return HTMLResponse("<h1>502 Bad Gateway</h1>", status_code=502)
        return await call_next(request)

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/mail/")

    return app
