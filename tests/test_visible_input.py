import asyncio
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from precedent.worker.runner import browser_toolset, chrome_path
from precedent.worker.screen import AvaBrowser, Screen


@pytest.mark.parametrize("headed", [False, True])
def test_visible_input_types_clicks_selects_and_separates_human_pointer(tmp_path, headed):
    class Site(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""<title>Input validation fixture</title>
              <label>Search <input name='search'></label>
              <button onclick="document.querySelector('#result').textContent='Searched'">
                Search now</button>
              <select aria-label='Account'><option disabled>Select</option>
                <option value='a'>Alpha</option><option value='b'>Beta</option></select>
              <label>Due date <input type='date' name='due'></label><p id='result'></p>
              <a href='/next'>Next page</a>
              <form method='POST' action='/refused'><button>Submit refused</button></form>
              <div style='height:1200px'></div><button id='low'>Below fold</button>
              <script>window.typed=[];document.querySelector('input').addEventListener('input',e=>typed.push({value:e.target.value,at:performance.now()}));</script>""")

        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            self.send_response(409)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<title>Refused</title><h1>Write refused</h1>")

    site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{site.server_port}"

    async def check():
        browser = AvaBrowser(chrome_path(), initial_url=base, headed=headed)
        screen = Screen(browser.endpoint)
        toolset = browser_toolset(base, tmp_path, False, browser.endpoint)
        try:
            await screen.start()
            tools = {t.name: t for t in await toolset.get_tools()}
            assert "browser_run_code_unsafe" not in tools and "browser_fill_form" not in tools

            async def snapshot_target(label):
                result = await tools["browser_snapshot"].run_async(args={}, tool_context=None)
                text = "\n".join(c.get("text", "") for c in result["content"])
                match = re.search(re.escape(label) + r".*?\[ref=([^\]]+)\]", text)
                assert match, text
                return match.group(1)

            target = await snapshot_target('textbox "Search"')
            result = await tools["browser_type"].run_async(
                args={"target": target, "text": "Figma", "element": "Search"}, tool_context=None
            )
            assert not result.get("isError"), result
            assert "Snapshot" in "\n".join(c.get("text", "") for c in result["content"])
            typed = await screen._page.evaluate("window.typed")
            assert [r["value"] for r in typed] == ["F", "Fi", "Fig", "Figm", "Figma"]
            assert typed[-1]["at"] - typed[0]["at"] >= 200
            pointer = await screen._page.evaluate("window.__ava.position()")
            await screen._page.mouse.move(10, 10)
            await screen._page.get_by_label("Due date").focus()
            assert await screen._page.evaluate("window.__ava.position()") == pointer

            target = await snapshot_target('combobox "Account"')
            result = await tools["browser_select_option"].run_async(
                args={"target": target, "values": ["Beta"], "element": "Account"}, tool_context=None
            )
            assert not result.get("isError"), result
            assert await screen._page.get_by_label("Account").input_value() == "b"
            target = await snapshot_target('textbox "Due date"')
            result = await tools["browser_type"].run_async(
                args={"target": target, "text": "2026-10-21", "element": "Due date"},
                tool_context=None,
            )
            assert not result.get("isError"), result
            assert await screen._page.get_by_label("Due date").input_value() == "2026-10-21"

            target = await snapshot_target('button "Search now"')
            result = await tools["browser_click"].run_async(
                args={"target": target}, tool_context=None
            )
            assert not result.get("isError"), result
            assert await screen._page.locator("#result").inner_text() == "Searched"
            target = await snapshot_target('button "Below fold"')
            result = await tools["browser_click"].run_async(
                args={"target": target}, tool_context=None
            )
            assert not result.get("isError"), result
            assert await screen._page.evaluate("scrollY") > 500
            target = await snapshot_target('link "Next page"')
            result = await tools["browser_click"].run_async(
                args={"target": target}, tool_context=None
            )
            assert not result.get("isError"), result
            assert screen._page.url == base + "/next"
            assert "/next" in "\n".join(c.get("text", "") for c in result["content"])
            await tools["browser_navigate_back"].run_async(args={}, tool_context=None)
            target = await snapshot_target('textbox "Search"')
            result = await tools["browser_type"].run_async(
                args={"target": target, "text": "After back"}, tool_context=None
            )
            assert not result.get("isError"), result
            assert await screen._page.get_by_label("Search").input_value() == "After back"
            target = await snapshot_target('button "Submit refused"')
            await tools["browser_click"].run_async(args={"target": target}, tool_context=None)
            await tools["browser_navigate_back"].run_async(args={}, tool_context=None)
            target = await snapshot_target('textbox "Search"')
            result = await tools["browser_type"].run_async(
                args={"target": target, "text": "Recovered"}, tool_context=None
            )
            assert not result.get("isError"), result
            assert await screen._page.get_by_label("Search").input_value() == "Recovered"
        finally:
            await toolset.close()
            await screen.stop()
            browser.close()

    try:
        asyncio.run(check())
    finally:
        site.shutdown()
        site.server_close()
