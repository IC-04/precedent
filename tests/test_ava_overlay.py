"""Ava's companion in the worker browser: same character, read-only, invisible to snapshots.

Real Chromium + Playwright MCP against a local fixture page; no model, no company writes.
"""

import asyncio
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from precedent.worker.runner import browser_toolset, chrome_path
from precedent.worker.screen import AvaBrowser, Screen, overlay_script, pose_for_tool

PAGE = b"""<!doctype html><title>Overlay fixture</title><h1>Overlay validation fixture</h1>
<label>Amount <input aria-label="Amount"></label>
<button onclick="document.getElementById('out').textContent='Saved'">Save bill</button>
<p id="out"></p>"""


def test_overlay_inlines_the_shared_drawing():
    script = overlay_script()
    assert "/*AVA_ART*/ null" not in script
    assert 'class=\\"ava-art\\"' in script and "data-pose" in script
    assert pose_for_tool("browser_snapshot") == "read"
    assert pose_for_tool("browser_click") == "work"


def test_companion_states_are_trusted_hidden_and_inert(tmp_path):
    class Site(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{site.server_port}"
    shots = os.environ.get("PRECEDENT_OVERLAY_SHOTS")

    async def check():
        browser = AvaBrowser(chrome_path(), initial_url=base)
        screen = Screen(browser.endpoint)
        toolset = browser_toolset(base, tmp_path, False, browser.endpoint)
        try:
            await screen.start()
            await screen._page.wait_for_load_state("domcontentloaded")
            host = screen._page.locator("#__ava_host")
            tools = {t.name: t for t in await toolset.get_tools()}
            # Scripted lifecycle states, as the runner's callbacks send them.
            for pose, text in [
                ("read", "Preparing the goal and reading company context"),
                ("think", "Choosing the next step"),
                ("work", "Typing into Amount"),
                ("check", "Checking the saved record on freshly read pages"),
                ("ask", "Waiting for your answer on the task page"),
                ("away", "Stopped · see the task page"),
            ]:
                await screen.say(text, pose)
                assert await host.get_attribute("data-pose") == pose
                if shots:
                    await screen._page.screenshot(path=f"{shots}/overlay-{pose}.png")
            # An older state arriving late never overwrites a newer one.
            await screen._page.evaluate("window.__ava.show({seq: 1, pose: 'work', text: 'old'})")
            assert await host.get_attribute("data-pose") == "away"
            # Human pointer and focus do not drive Ava's pose or pointer.
            pointer = await screen._page.evaluate("window.__ava.position()")
            await screen._page.mouse.move(300, 200)
            await screen._page.get_by_label("Amount").focus()
            assert await host.get_attribute("data-pose") == "away"
            assert await screen._page.evaluate("window.__ava.position()") == pointer
            # The model's snapshot contains business UI, never the companion or its status.
            result = await tools["browser_snapshot"].run_async(args={}, tool_context=None)
            text = "\n".join(c.get("text", "") for c in result["content"])
            assert "Save bill" in text and "Amount" in text
            for hidden in ("Stopped", "Choosing the next step", "Needs your input", "Ava"):
                assert hidden not in text, hidden
            # Real clicks and typing still reach business controls through the companion.
            ref = re.search(r'button "Save bill".*?\[ref=([^\]]+)\]', text).group(1)
            done = await tools["browser_click"].run_async(args={"target": ref}, tool_context=None)
            assert not done.get("isError"), done
            assert await screen._page.locator("#out").inner_text() == "Saved"
            ref = re.search(r'textbox "Amount".*?\[ref=([^\]]+)\]', text).group(1)
            typed = await tools["browser_type"].run_async(
                args={"target": ref, "text": "1200", "element": "Amount"}, tool_context=None
            )
            assert not typed.get("isError"), typed
            assert await screen._page.get_by_label("Amount").input_value() == "1200"
            # State survives navigation within the session (a new document re-mounts).
            await screen._page.reload()
            await screen._page.wait_for_load_state("domcontentloaded")
            assert await host.get_attribute("data-pose") == "away"
            assert await host.count() == 1
        finally:
            await toolset.close()
            await screen.stop()
            browser.close()

    asyncio.run(check())
    site.shutdown()
