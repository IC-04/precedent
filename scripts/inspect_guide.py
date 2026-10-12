"""Inspect the actual local guide with Chromium; never submit a paid agent task."""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://localhost:8012"
OUT = Path("output/guide-milestone")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {"checks": [], "durations": {}, "errors": [], "task_posts": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        if "--references" in sys.argv:
            for name, url in [
                ("linear-documents", "https://linear.app/docs/documents"),
                ("notion-wiki", "https://www.notion.com/help/wikis-and-verified-pages"),
            ]:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)
                await page.screenshot(path=str(OUT / f"reference-{name}.png"))
                print(f"Inspected reference: {url}", flush=True)
            await browser.close()
            return
        page.on("pageerror", lambda error: results["errors"].append(str(error)))
        page.on(
            "request",
            lambda request: (
                results["task_posts"].append(request.url)
                if request.method == "POST" and "/runs" in request.url
                else None
            ),
        )
        await page.goto(BASE + "/guide")
        await page.evaluate("document.fonts.ready")
        assert await page.locator("#tour-audio").evaluate("a => a.paused && !a.currentSrc")
        results["checks"].append("No autoplay or provider call on page load")
        for width, height in [(1440, 900), (1280, 800), (390, 844)]:
            await page.set_viewport_size({"width": width, "height": height})
            await page.screenshot(path=str(OUT / f"guide-{width}.png"))
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        results["checks"].append("1440, 1280 and 390 widths have no horizontal overflow")
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.locator("#tour-start").click()
        await page.wait_for_function("document.querySelector('audio').currentTime > 0.3")
        assert await page.locator("body").evaluate("e => e.classList.contains('tour-speaking')")
        await page.wait_for_timeout(900)
        assert await page.locator(".story-current").get_attribute("id") == "hello"
        assert await page.evaluate("scrollY > 50")
        results["checks"].append("Narration begins with automatic scroll and Ava at first scene")
        await page.locator(".player-transcript summary").click()
        await page.screenshot(path=str(OUT / "guide-speaking-1440.png"))
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(OUT / "guide-speaking-390.png"))
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.locator("#tour-toggle").click()
        assert await page.locator("#tour-audio").evaluate("a => a.paused")
        before = await page.locator("#tour-audio").evaluate("a => a.currentTime")
        await page.wait_for_timeout(300)
        assert await page.locator("#tour-audio").evaluate("a => a.currentTime") == before
        await page.locator("#tour-toggle").click()
        await page.wait_for_function("!document.querySelector('audio').paused")
        await page.locator("#tour-mute").click()
        assert await page.locator("#tour-audio").evaluate("a => a.muted")
        results["checks"].append("Actual MP3 playback, pause/resume, mute and speaking state")
        for index in range(5):
            await page.locator("#tour-chapter").select_option(str(index))
            await page.wait_for_function(
                "Number.isFinite(document.querySelector('audio').duration)"
            )
            duration = await page.locator("#tour-audio").evaluate("a => a.duration")
            results["durations"][str(index)] = duration
            await page.wait_for_timeout(850)
            assert (
                await page.locator(".story-current").get_attribute("id")
                == ["hello", "work", "company", "evidence", "next"][index]
            )
            if index in [1, 2, 4]:
                await page.screenshot(path=str(OUT / f"story-{index}.png"))
        # Reach the last chapter's real ended event, then restart and verify auto-advance.
        await page.locator("#tour-audio").evaluate("a => a.currentTime = a.duration - 0.2")
        await page.wait_for_function(
            "document.querySelector('#tour-status').textContent.startsWith('Tour complete')"
        )
        await page.locator("#tour-stop").click()
        assert await page.locator("#tour-chapter").input_value() == "0"
        assert await page.locator("#tour-audio").evaluate("a => a.paused && a.currentTime === 0")
        await page.locator("#tour-toggle").click()
        await page.wait_for_function("!document.querySelector('audio').paused")
        await page.locator("#tour-seek").evaluate(
            "e => {e.value = Number(e.max)-0.2; e.dispatchEvent(new Event('input'));}"
        )
        await page.wait_for_function("document.querySelector('#tour-chapter').value === '1'")
        results["checks"].append(
            "All five assets decode; seek, chapter switching, end and restart work"
        )
        active = {"run_url": None}
        await page.route("**/watch/state", lambda route: route.fulfill(json=active))
        active["run_url"] = "/runs/controlled-active-fixture"
        await page.wait_for_function(
            "document.querySelector('#tour-status').textContent === 'Tour paused while Ava works'",
            timeout=7000,
        )
        assert await page.locator("#tour-audio").evaluate("a => a.paused")
        assert (
            await page.locator(".guide-task").first.get_attribute("href")
            == "/runs/controlled-active-fixture"
        )
        results["checks"].append("Controlled active-task state stops narration and redirects CTA")
        await page.unroute("**/watch/state")
        await page.reload()
        await page.locator(".guide-task").first.click()
        await page.wait_for_url(BASE + "/#request")
        assert await page.locator("#request").evaluate("e => e === document.activeElement")
        await page.locator("[data-example]").first.click()
        assert "Figma" in await page.locator("#request").input_value()
        assert not results["task_posts"]
        results["checks"].append("Task CTA focuses composer; example fills it without submission")
        await page.goto(BASE + "/guide")
        await page.route("**/audio/guide/*.mp3", lambda route: route.abort())
        await page.locator("#tour-start").click()
        await page.wait_for_function(
            "document.querySelector('#tour-status').textContent.includes('Audio unavailable')"
        )
        assert await page.locator(".player-transcript").evaluate("e => e.open")
        await page.screenshot(path=str(OUT / "guide-audio-unavailable.png"))
        results["checks"].append("Unavailable audio exposes transcript and preserves guide")
        await page.unroute("**/audio/guide/*.mp3")
        await page.emulate_media(reduced_motion="reduce")
        assert (
            await page.locator(".guide-hero .ava-breath").first.evaluate(
                "e => getComputedStyle(e).animationName"
            )
            == "none"
        )
        await page.reload()
        await page.locator("#verification-note summary").click()
        await page.locator("#evidence").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "guide-evidence.png"))
        for selector in [".proof-links a", ".company-map a"]:
            for link in await page.locator(selector).all():
                url = await link.evaluate("e => e.href")
                response = await page.request.get(url)
                assert response.status == 200, (url, response.status)
        results["checks"].append("Evidence, original bill and four company links return 200")
        results["checks"].append("Reduced motion disables companion animation")
        await page.goto(BASE + "/guide")
        await page.locator("#tour-start").focus()
        await page.keyboard.press("Enter")
        await page.wait_for_function("!document.querySelector('audio').paused")
        await page.locator("#tour-toggle").focus()
        await page.keyboard.press("Space")
        assert await page.locator("#tour-audio").evaluate("a => a.paused")
        results["checks"].append("Keyboard starts and pauses playback; mobile player fits")
        await page.emulate_media(reduced_motion="no-preference")
        await page.reload()
        await page.locator("#tour-start").click()
        await page.wait_for_function("document.querySelector('audio').currentTime > 0.2")
        await page.wait_for_timeout(900)
        await page.mouse.move(600, 300)
        await page.mouse.wheel(0, 180)
        await page.wait_for_function(
            "document.querySelector('#tour-follow').getAttribute('aria-pressed') === 'false'"
        )
        assert await page.locator("#tour-follow").get_attribute("aria-pressed") == "false"
        await page.locator("#tour-follow").click()
        assert await page.locator("#tour-follow").get_attribute("aria-pressed") == "true"
        await page.locator("#tour-stop").click()
        assert await page.locator(".tour-guide-ava").is_hidden()
        results["checks"].append(
            "Manual scroll yields control, Follow Ava resumes, Stop resets companion"
        )
        await page.emulate_media(reduced_motion="reduce")
        await page.reload()
        assert await page.locator("#tour-follow").get_attribute("aria-pressed") == "false"
        results["checks"].append("Reduced motion starts with auto-scroll off")
        await page.screenshot(path=str(OUT / "guide-full.png"), full_page=True)
        await browser.close()
    assert not results["errors"], results["errors"]
    results["total_audio_seconds"] = sum(results["durations"].values())
    results["listening_limit"] = (
        "Playback and decoding verified; no audio-listening tool available."
    )
    (OUT / "validation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
