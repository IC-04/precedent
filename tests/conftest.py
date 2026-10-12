import socket
import sqlite3
import threading
import time

import pytest
import uvicorn

from precedent.apps.server import create_app
from precedent.world.generator import generate

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    """Tests never call a model: the in-run Tribunal is off and no Bedrock key is visible.
    Tribunal tests seat scripted jurors explicitly."""
    monkeypatch.setenv("PRECEDENT_TRIBUNAL", "0")
    monkeypatch.setenv("PRECEDENT_TRIBUNAL_PLANNER", "0")
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_apps(tmp_path, monkeypatch):
    """Seed-7 apps served over real HTTP in a thread. Yields (base_url, db connection)."""
    monkeypatch.setenv("PRECEDENT_SCENARIO_TOKEN", TOKEN)
    generate("northwind", 7, tmp_path / "7")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(7, tmp_path), port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    conn = sqlite3.connect(tmp_path / "7" / "world.db")
    yield f"http://127.0.0.1:{port}", conn
    conn.close()
    server.should_exit = True
    thread.join(timeout=5)
