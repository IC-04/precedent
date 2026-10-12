from types import SimpleNamespace

from fastapi.testclient import TestClient

from precedent.console.server import create_app
from precedent.worker.events import EventLog


def test_watch_follows_only_this_consoles_unfinished_managed_task(tmp_path):
    old = EventLog("old-run", root=tmp_path)
    old.emit("run_started", request="Old task", seed=7)
    app = create_app(tmp_path, launcher=lambda *a, **kw: None)
    client = TestClient(app)
    assert "Waiting for your task" in client.get("/watch").text
    assert client.get("/watch/state").json() == {"run_url": None}
    assert app.state.manager.processes == {}

    live = EventLog("live-run", root=tmp_path)
    live.emit("run_started", request="Current task", seed=7)
    app.state.manager.processes["live-run"] = SimpleNamespace(poll=lambda: None)
    response = client.get("/watch/state")
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["run_url"] == "/runs/live-run"
    # Ava's companion pose comes from the same recorded state, never elapsed time.
    assert body["companion"]["pose"] in {"read", "think", "work", "check", "ask", "listen"}

    live.emit("run_finished", outcome="unknown")
    assert client.get("/watch/state").json() == {"run_url": None}
    app.state.manager.processes["live-run"] = SimpleNamespace(poll=lambda: 0)
    assert client.get("/watch/state").json() == {"run_url": None}
