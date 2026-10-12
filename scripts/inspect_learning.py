"""Browser checks for the real learning workspace; no fabricated memories."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main(base):
    out = Path("output/learning-milestone")
    out.mkdir(parents=True, exist_ok=True)
    result = {"checks": [], "errors": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: result["errors"].append(str(error)))
        for width in [1440, 390]:
            await page.set_viewport_size({"width": width, "height": 1000})
            for tab in ["memory", "skills"]:
                await page.goto(f"{base}/mind?tab={tab}")
                await page.get_by_role("heading", name="Ava’s mind", exact=True).wait_for()
                assert await page.locator("body").evaluate("(e) => e.scrollWidth <= innerWidth + 1")
                await page.screenshot(path=str(out / f"{tab}-{width}.png"), full_page=True)
                result["checks"].append(f"{tab} at {width}px: heading, no horizontal overflow")
        await page.emulate_media(reduced_motion="reduce")
        await page.goto(base + "/mind")
        await page.locator("#mind-query").fill("invoice")
        await page.get_by_role("button", name="Search", exact=True).click()
        assert "q=invoice" in page.url
        result["checks"].append("Search form and reduced-motion view")
        assert not result["errors"], result["errors"]
        await browser.close()
    (out / "browser-checks.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://localhost:8016")
asyncio.run(main(parser.parse_args().base.rstrip("/")))
