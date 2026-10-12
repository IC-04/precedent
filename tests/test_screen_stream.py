"""Real Chromium + MCP + continuous frames, without a model or company writes."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from precedent.worker.runner import browser_toolset, chrome_path
from precedent.worker.screen import AvaBrowser, Screen


def test_frames_change_between_mcp_actions(tmp_path):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h1>Stream validation fixture - no AI run</h1><input aria-label='Human input'>"
                b"<div id='motion' style='width:200px;height:200px'></div>"
                b"<script>let frame=0;setInterval(()=>{frame++;"
                b"motion.style.background='hsl('+frame*12+' 80% 50%)';"
                b"motion.textContent='Frame '+frame;},100);</script>"
            )

        def log_message(self, *args):
            pass

    site = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=site.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{site.server_port}"

    async def check():
        browser = AvaBrowser(chrome_path(), initial_url=base)
        screen = Screen(browser.endpoint)
        tools = None
        try:
            await screen.start()
            await screen._page.wait_for_load_state("domcontentloaded")
            assert screen._page.url == base + "/"
            await screen.say("Preparing the task")
            before = await screen._page.evaluate("sessionStorage.getItem('__ava_overlay')")
            await screen._page.mouse.move(150, 150)
            await screen._page.get_by_label("Human input").focus()
            assert await screen._page.evaluate("sessionStorage.getItem('__ava_overlay')") == before
            assert await screen._page.locator("#__ava_host").get_attribute("aria-hidden") == "true"
            tools = browser_toolset(base, tmp_path, False, browser.endpoint)
            navigation = next(t for t in await tools.get_tools() if t.name == "browser_navigate")
            result = await navigation.run_async(args={"url": base}, tool_context=None)
            assert not result.get("isError"), result
            # No more browser tools execute. The observer must still deliver moving frames.
            pictures = set()
            buffer = b""
            async with asyncio.timeout(8):
                async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                    async with client.stream("GET", screen.url) as response:
                        assert response.headers["content-type"].startswith(
                            "multipart/x-mixed-replace"
                        )
                        async for chunk in response.aiter_bytes():
                            buffer += chunk
                            while b"\xff\xd8" in buffer and b"\xff\xd9" in buffer:
                                start = buffer.index(b"\xff\xd8")
                                end = buffer.index(b"\xff\xd9", start) + 2
                                pictures.add(buffer[start:end])
                                buffer = buffer[end:]
                            if len(pictures) >= 5:
                                break
            assert len(pictures) >= 5
            assert screen.frames.count >= 5
        finally:
            if tools is not None:
                await tools.close()
            await screen.stop()
            browser.close()
        assert not Path(browser.profile).exists()
        assert browser.process.poll() is not None
        assert screen.frames.closed

    try:
        asyncio.run(check())
    finally:
        site.shutdown()
        site.server_close()
        thread.join(timeout=3)
