"""Real browser checks and screenshots for the meeting workflow."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apps", default="http://localhost:8124")
    parser.add_argument("--console", default="http://localhost:8018")
    parser.add_argument("--draft", default="draft-1e9d559df51d")
    parser.add_argument("--hold")
    parser.add_argument("--run")
    args = parser.parse_args()
    out = Path("output/meeting-milestone")
    out.mkdir(parents=True, exist_ok=True)
    result = {"checks": [], "errors": []}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda err: result["errors"].append(str(err)))
        destinations = [
            ("calendar", args.apps + "/calendar/?start=2026-10-05"),
            ("availability", args.apps + "/calendar/availability?recipient=E-ana"),
            ("drafts", args.apps + "/mail/drafts"),
            ("compose", args.apps + "/mail/drafts/new"),
            ("saved-draft", args.apps + "/mail/drafts/" + args.draft),
            ("edit-draft", args.apps + "/mail/drafts/" + args.draft + "/edit"),
        ]
        if args.hold:
            destinations.append(("local-hold", args.apps + "/calendar/events/" + args.hold))
        if args.run:
            destinations.append(("completed-run", args.console + "/runs/" + args.run))
        for width in [1440, 390]:
            await page.set_viewport_size({"width": width, "height": 1000})
            for name, url in destinations:
                response = await page.goto(url)
                assert response.status == 200, (name, response.status)
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(out / f"{name}-{width}.png"), full_page=True)
                overflow = await page.locator("body").evaluate("(e)=>e.scrollWidth>innerWidth+1")
                result["checks"].append({"page": name, "width": width, "overflow": overflow})
                assert not overflow, (name, width)
        await page.set_viewport_size({"width": 1440, "height": 1000})
        await page.goto(args.apps + "/calendar/")
        await page.get_by_role("link", name="Next week", exact=True).click()
        assert "start=" in page.url
        await page.locator(".event-block").first.click()
        await page.get_by_role("heading", level=1).wait_for()
        assert "/calendar/events/" in page.url
        result["checks"].append({"event_details": True})
        await page.goto(args.apps + "/mail/drafts/" + args.draft + "/edit")
        body = await page.get_by_label("Message", exact=True).input_value()
        await page.reload()
        assert body == await page.get_by_label("Message", exact=True).input_value()
        result["checks"].append({"editable_draft_survives_reload": True})
        await page.goto(args.apps + "/calendar/")
        await page.locator(".ava-dock-button").click()
        await page.get_by_role("button", name="Prepare a catch-up", exact=True).wait_for()
        await page.get_by_role("button", name="Prepare a catch-up", exact=True).click()
        assert "[colleague]" in await page.locator("#ava-draft").input_value()
        await page.locator("#ava-draft").fill(
            "Prepare a catch-up with Ana Pereira next week about the vendor renewal. "
            "Save a draft; do not send it."
        )
        await page.get_by_role("button", name="Review in task composer ↗", exact=True).click()
        await page.wait_for_url(lambda url: url.startswith(args.console))
        assert "Ana Pereira" in await page.locator("#request").input_value()
        result["checks"].append({"navigation_and_companion": True})
        assert result["errors"] == []
        await browser.close()
    (out / "browser-checks.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


asyncio.run(main())
