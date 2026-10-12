from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from precedent.console import server
from precedent.worker.events import EventLog


def active_console(tmp_path, source="http://127.0.0.1:9100/screen.mjpg"):
    log = EventLog("live-run", root=tmp_path)
    log.emit("run_started", request="Read a record", seed=7)
    log.emit("note", kind="screen", url=source)
    app = server.create_app(tmp_path)
    app.state.manager.processes["live-run"] = SimpleNamespace(poll=lambda: None)
    return log, app, TestClient(app)


def test_live_workspace_has_no_capture_player_or_expansion_control(tmp_path):
    log, app, client = active_console(tmp_path)
    response = client.get("/runs/live-run/workspace")
    assert response.status_code == 200
    assert "Continuous live stream" in response.text
    assert "capture-select" not in response.text
    assert "Expand browser" not in response.text
    assert "Play recorded views" not in response.text
    assert client.get("/static/watch.js").text.count("data.run_url + '/workspace'") == 1
    log.emit("run_finished", outcome="unknown")
    assert client.get("/runs/live-run/screen").status_code == 409


def test_stream_never_connects_to_an_unmanaged_or_external_source(tmp_path):
    log, app, client = active_console(tmp_path, "http://example.com/screen.mjpg")
    assert client.get("/runs/live-run/screen").status_code == 502
    app.state.manager.processes.clear()
    assert client.get("/runs/live-run/screen").status_code == 409


def test_proxy_streams_multiple_frames_and_closes_upstream(tmp_path, monkeypatch):
    _, _, client = active_console(tmp_path)
    frames = [
        b"--avaframe\r\nContent-Type: image/jpeg\r\n\r\nfirst\r\n",
        b"--avaframe\r\nContent-Type: image/jpeg\r\n\r\nsecond\r\n",
    ]

    class FrameStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            for frame in frames:
                yield frame

        async def aclose(self):
            self.closed = True

    upstream = FrameStream()

    async def respond(request):
        assert str(request.url) == "http://127.0.0.1:9100/screen.mjpg"
        return httpx.Response(
            200,
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=avaframe"},
            stream=upstream,
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        server.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    response = client.get("/runs/live-run/screen")
    assert response.status_code == 200
    assert response.content == b"".join(frames)
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-store"
    assert upstream.closed
