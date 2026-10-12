"""Ava's screen: her own Chromium, driven by Playwright MCP, watched live by people.

We launch the browser (isolated profile, remote debugging on localhost). Playwright MCP
attaches to it and does all of Ava's work. Separately, this module attaches over CDP to
(1) stream the page as an MJPEG video for the console and (2) show worker action
captions with a script that exists only in Ava's browser, hidden from her page snapshots.
Nothing here touches the company apps or influences Ava's actions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
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
ART = Path(__file__).parents[1] / "apps" / "static" / "ava"


def overlay_script() -> str:
    """The overlay with Ava's shared drawing and poses inlined: one character everywhere,
    and nothing loaded from (or visible to) the company pages Ava works in."""
    art = {"svg": (ART / "ava.svg").read_text(), "css": (ART / "ava.css").read_text()}
    return OVERLAY.read_text().replace("/*AVA_ART*/ null", json.dumps(art), 1)


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
        self.closed = False
        self.changed = threading.Condition()

    def close(self) -> None:
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def put(self, jpeg: bytes) -> None:
        with self.changed:
            self.jpeg, self.count = jpeg, self.count + 1
            self.changed.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[bytes | None, int]:
        with self.changed:
            if self.count == seen:
                self.changed.wait(timeout)
            return self.jpeg, self.count


def _mjpeg_server(frames: Frames, port: int, focus=None, focus_path=None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if not focus or self.path != focus_path or self.headers.get("Origin"):
                self.send_error(403)
                return
            try:
                focus()
                self.send_response(204)
                self.end_headers()
            except Exception:  # noqa: BLE001 - closed browser remains a viewing failure
                self.send_error(503, "Browser is unavailable")

        def do_GET(self):  # noqa: N802 - http.server's naming
            if self.path.split("?")[0] == "/frame.jpg":
                jpeg, _ = frames.wait(-1, 0)
                self.send_response(200 if jpeg else 204)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                if jpeg:
                    self.wfile.write(jpeg)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}"
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = 0
            try:
                while not frames.closed:
                    jpeg, seen = frames.wait(seen, 1.0)  # repeat the last frame at least 1/s
                    if jpeg is None:
                        continue
                    self.wfile.write(
                        b"--"
                        + BOUNDARY
                        + b"\r\nContent-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                        + jpeg
                        + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


class AvaBrowser:
    """Launches Ava's Chromium and exposes its CDP endpoint for Playwright MCP."""

    def __init__(
        self,
        executable: str,
        headed: bool = False,
        size: tuple[int, int] = (1280, 860),
        initial_url: str = "about:blank",
        profile: str | None = None,
    ):
        self.port = free_port()
        # A given profile is the owner's signed-in one: reused, and never deleted here.
        self.keep_profile = profile is not None
        self.profile = profile or tempfile.mkdtemp(prefix="ava-profile-")
        self.process: subprocess.Popen | None = None
        args = [
            executable,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            # Chromium history caching can restore snapshot refs from a frame
            # that CDP has replaced. Fresh documents keep MCP targets consistent.
            "--disable-features=BackForwardCache",
            f"--window-size={size[0]},{size[1]}",
            initial_url,
        ]
        if not headed:
            args.insert(1, "--headless=new")
        try:
            self.process = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError:
            if not self.keep_profile:
                shutil.rmtree(self.profile, ignore_errors=True)
            raise
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
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if not self.keep_profile:
            shutil.rmtree(self.profile, ignore_errors=True)


class Screen:
    """Live view and captions for one AvaBrowser. Failures never stop Ava's work."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.frames = Frames()
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/screen.mjpg"
        focus_path = "/focus/" + secrets.token_hex(16)
        self.focus_url = f"http://127.0.0.1:{self.port}{focus_path}"
        self._loop = None
        self._server = _mjpeg_server(self.frames, self.port, self._focus, focus_path)
        self._pw: Any = None
        self._browser: Any = None
        self._cdp: Any = None
        self._page: Any = None
        self._serving = False
        self._seq = 0
        self._script = overlay_script()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self._serving = True
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.endpoint)
        context = self._browser.contexts[0]
        await context.add_init_script(script=self._script)
        context.on("page", lambda page: asyncio.ensure_future(self._watch(page)))
        await self._watch(context.pages[0])

    def _focus(self) -> None:
        if self._page is None or self._loop is None:
            raise RuntimeError("Browser has not connected")
        asyncio.run_coroutine_threadsafe(self._page.bring_to_front(), self._loop).result(3)

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
        await cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 70, "maxWidth": 1280, "maxHeight": 860},
        )
        try:  # the init script covers new documents; draw on the current one too
            await page.evaluate(self._script)
        except Exception:  # noqa: BLE001
            pass

    async def say(self, caption: str, pose: str | None = None) -> None:
        """Show Ava's pose and caption in her browser (remembered across page loads).

        Called only from trusted runner callbacks with recorded lifecycle states. It is
        bounded so decoration never slows the work; a late, older state is ignored."""
        if self._page is None:
            return
        self._seq += 1
        state = {"seq": self._seq, "text": caption, **({"pose": pose} if pose else {})}
        try:
            await asyncio.wait_for(
                self._page.evaluate("s => window.__ava && window.__ava.show(s)", state), 1.5
            )
        except Exception:  # noqa: BLE001 - a navigation may be in flight; the next state wins
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
            self.frames.close()  # ends every open MJPEG stream
            if self._serving:  # shutdown() waits forever on a server that never started
                self._server.shutdown()
            self._server.server_close()


def pose_for_tool(tool: str) -> str:
    """Reading a page is reading; every other browser action is hands-on work."""
    return "read" if tool in ("browser_snapshot", "browser_wait_for") else "work"


def caption_for(tool: str, args: dict) -> str:
    """Plain-language caption for a browser action, from its own arguments."""
    raw = str(args.get("element") or "").strip()
    quoted = re.search(r'"([^"]+)"', raw)
    element = quoted.group(1) if quoted else raw.strip('"')
    host = str(args.get("url", "")).split("//", 1)[-1].partition("/")[0]
    site = {"mail.google.com": "Gmail", "calendar.google.com": "Google Calendar"}.get(host)
    if tool == "browser_navigate":
        if site:
            return f"Opening {site}"
        path = str(args.get("url", "")).split("//", 1)[-1].partition("/")[2].strip("/")
        app = path.split("/")[0]
        return f"Opening {app.capitalize()}" if app else "Opening the company apps"
    if tool == "browser_tabs":
        action = args.get("action")
        if action == "new":
            return f"Opening a new tab{': ' + site if site else ''}"
        if action == "select":
            return f"Switching to tab {args.get('index', '')}".strip()
        return "Checking the open tabs"
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
    if tool == "browser_press_key":
        return f"Pressing {args.get('key', 'a key')}"[:90]
    return "Working"
