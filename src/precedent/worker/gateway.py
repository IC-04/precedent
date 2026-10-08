"""The worker's gateway: the only road from the worker's browser to the company apps.

Every non-GET request is a consequential write. The gateway asks the WriteGate before
letting one through, and reports what came back, so "decision before write" and
"never blind-retry an uncertain write" hold even if the model ignores its prompt.
It knows nothing about the apps: no paths, no names, no scenario token.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from precedent.contracts import FailureKind
from precedent.worker.failures import WriteGate

AGENT_HEADER = "X-Precedent-Agent"  # lets the apps leave out links meant for human viewers
HOP_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "content-encoding",
    "keep-alive",
    "x-scenario-token",
}


@dataclass
class Exchange:
    method: str
    path: str
    status: int | None
    refused: str | None = None
    timed_out: bool = False
    kind: FailureKind | None = None


AUTOMATIC = ("/favicon.ico", "/robots.txt", "/apple-touch-icon")
STATIC = (".ico", ".png", ".jpg", ".svg", ".css", ".js", ".woff", ".woff2", ".map")


def is_automatic(method: str, path: str) -> bool:
    """Requests the browser makes by itself, which say nothing about Ava's work."""
    bare = path.split("?", 1)[0].lower()
    return method.upper() == "GET" and (
        (bare.startswith(AUTOMATIC) or bare.startswith("/static/"))
        or bare.endswith(STATIC)
        or "/preview/" in bare
        or bare.endswith("/download")
        or bare in ("/workspace.json", "/work-status")
    )


def _page(title: str, text: str) -> bytes:
    return (
        f"<!doctype html><title>{escape(title)}</title><h1>{escape(title)}</h1>"
        f'<p role="alert">{escape(text)}</p>'
    ).encode()


class Gateway:
    def __init__(
        self,
        upstream: str,
        gate: WriteGate,
        on_exchange: Callable[[Exchange], None] | None = None,
        port: int = 0,
        timeout: float = 20.0,
    ):
        self.upstream = upstream.rstrip("/")
        self.gate, self.on_exchange = gate, on_exchange or (lambda e: None)
        self.lock = threading.Lock()
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.url = f"http://localhost:{self.server.server_address[1]}"

    def start(self) -> str:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.started = True
        return self.url

    def stop(self) -> None:
        if getattr(self, "started", False):
            self.server.shutdown()
        self.server.server_close()
        self.client.close()

    def forward(self, method: str, path: str, headers: dict[str, str], body: bytes):
        """Returns (status, headers, body) for the browser, and records the exchange."""
        if is_automatic(method, path):  # the browser's own requests (favicon...): not Ava's
            return self._pass_through(method, path, headers, body)
        with self.lock:
            refused = self.gate.on_request(method)
        if refused:
            self.on_exchange(Exchange(method, path, None, refused=refused))
            return (
                409,
                {"Content-Type": "text/html"},
                _page("Save refused by Ava's safety gate", refused),
            )
        clean = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        clean[AGENT_HEADER] = "ava"
        try:
            r = self.client.request(method, self.upstream + path, headers=clean, content=body)
        except httpx.TimeoutException:
            return self._lost(method, path, timed_out=True)
        except httpx.TransportError:
            return self._lost(method, path, timed_out=False)
        with self.lock:
            kind = self.gate.on_response(method, path, r.status_code)
        self.on_exchange(Exchange(method, path, r.status_code, kind=kind))
        out = {
            k: v.replace(self.upstream, self.url)
            for k, v in r.headers.items()
            if k.lower() not in HOP_HEADERS
        }
        return r.status_code, out, r.content

    def _pass_through(self, method: str, path: str, headers: dict[str, str], body: bytes):
        clean = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        clean[AGENT_HEADER] = "ava"
        try:
            r = self.client.request(method, self.upstream + path, headers=clean, content=body)
        except httpx.HTTPError:
            return 404, {}, b""
        return r.status_code, {"Content-Type": r.headers.get("content-type", "")}, r.content

    def _lost(self, method: str, path: str, timed_out: bool):
        with self.lock:
            kind = self.gate.on_response(method, path, None, timed_out=timed_out)
        self.on_exchange(Exchange(method, path, None, timed_out=timed_out, kind=kind))
        text = (
            "No response from the company app. If this was a save, it may or may not have happened."
        )
        return 504, {"Content-Type": "text/html"}, _page("No response", text)

    def _handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def _any(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, content = gateway.forward(
                    self.command, self.path, dict(self.headers.items()), body
                )
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any

            def log_message(self, *args):
                pass

        return Handler
