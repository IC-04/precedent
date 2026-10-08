"""Ava's screen: her own Chromium, driven by Playwright MCP, watched live by people.

We launch the browser (isolated profile, remote debugging on localhost). Playwright MCP
attaches to it and does all of Ava's work. Separately, this module attaches over CDP to
(1) stream the page as an MJPEG video for the console and (2) draw Ava's cursor and
captions with a script that exists only in Ava's browser, hidden from her page snapshots.
Nothing here touches the company apps or influences Ava's actions.
"""

from __future__ import annotations

import asyncio
import base64
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

OVERLAY = Path(__file__).with_name("ava_overlay.js")
BOUNDARY = b"avaframe"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Frames:
    """The latest JPEG frame, shared between the CDP listener and the MJPEG server."""

    def __init__(self) -> None:
        self.jpeg: bytes | None = None
        self.count = 0
        self.changed = threading.Condition()

    def put(self, jpeg: bytes) -> None:
        with self.changed:
            self.jpeg, self.count = jpeg, self.count + 1
            self.changed.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[bytes | None, int]:
        with self.changed:
            if self.count == seen:
                self.changed.wait(timeout)
            return self.jpeg, self.count


def _mjpeg_server(frames: Frames, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's naming
            if self.path.split("?")[0] == "/frame.jpg":
                jpeg, _ = frames.wait(-1, 0)
                self.send_response(200 if jpeg else 204)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                if jpeg:
                    self.wfile.write(jpeg)
                return
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seen = 0
            try:
                while True:
                    jpeg, seen = frames.wait(seen, 1.0)  # repeat the last frame at least 1/s
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                                     + jpeg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


class AvaBrowser:
    """Launches Ava's Chromium and exposes its CDP endpoint for Playwright MCP."""

    def __init__(self, executable: str, headed: bool = False, size: tuple[int, int] = (1280, 860)):
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="ava-profile-")
        args = [executable, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", f"--window-size={size[0]},{size[1]}",
                "about:blank"]
        if not headed:
            args.insert(1, "--headless=new")
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.endpoint = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        self.close()
        raise RuntimeError("Ava's browser did not start")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


class Screen:
    """Live view and overlay for one AvaBrowser. Failures here never stop Ava's work."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.frames = Frames()
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/screen.mjpg"
        self._server = _mjpeg_server(self.frames, self.port)
        self._pw: Any = None
        self._browser: Any = None
        self._cdp: Any = None
        self._page: Any = None
        self.caption = ""

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.endpoint)
        context = self._browser.contexts[0]
        await context.add_init_script(path=str(OVERLAY))
        context.on("page", lambda page: asyncio.ensure_future(self._watch(page)))
        await self._watch(context.pages[0])

    async def _watch(self, page: Any) -> None:
        """Stream this page (the newest page wins)."""
        if self._cdp is not None:
            try:
                await self._cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001 - the old page may be gone
                pass
        self._page = page
        self._cdp = cdp = await page.context.new_cdp_session(page)

        async def on_frame(params: dict) -> None:
            self.frames.put(base64.b64decode(params["data"]))
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:  # noqa: BLE001
                pass

        cdp.on("Page.screencastFrame", lambda p: asyncio.ensure_future(on_frame(p)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 70,
                                                "maxWidth": 1280, "maxHeight": 860})
        try:  # the init script covers new documents; draw on the current one too
            await page.evaluate(OVERLAY.read_text())
        except Exception:  # noqa: BLE001
            pass

    async def say(self, caption: str) -> None:
        """Show a caption in Ava's browser (and remember it across page loads)."""
        self.caption = caption
        if self._page is None:
            return
        try:
            await self._page.evaluate("c => window.__ava && window.__ava.say(c)", caption)
        except Exception:  # noqa: BLE001 - a navigation may be in flight; the next caption wins
            pass

    async def stop(self) -> None:
        try:
            if self._cdp is not None:
                await self._cdp.send("Page.stopScreencast")
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._server.shutdown()
            self._server.server_close()


def caption_for(tool: str, args: dict) -> str:
    """Plain-language caption for a browser action, from its own arguments."""
    element = str(args.get("element") or "").strip().strip('"')
    element = element.split('"')[1] if element.count('"') >= 2 else element
    if tool == "browser_navigate":
        path = str(args.get("url", "")).split("//", 1)[-1].split("/", 1)[-1].strip("/")
        app = path.split("/")[0] if path else "the company apps"
        return f"Opening {app.capitalize() if app else 'the company apps'}"
    if tool == "browser_click":
        return f"Clicking {element}" if element else "Clicking"
    if tool == "browser_type":
        return f"Typing into {element}" if element else "Typing"
    if tool == "browser_fill_form":
        names = [str(f.get("name", "")) for f in args.get("fields") or [] if isinstance(f, dict)]
        return "Filling " + (", ".join(n for n in names if n)[:80] or "the form")
    if tool == "browser_select_option":
        values = ", ".join(map(str, args.get("values") or []))
        return f"Choosing {values}"[:90]
    if tool == "browser_navigate_back":
        return "Going back"
    if tool == "browser_snapshot":
        return "Reading the page"
    return "Working"
