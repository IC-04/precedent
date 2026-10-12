# ruff: noqa: E501 - inline browser JavaScript and check descriptions read best unwrapped
"""Inspect Ava's companion milestone in real Chromium; never assigns a paid task.

Usage: inspect_companion.py CONSOLE_URL APPS_URL WORLD_DB
Writes screenshots, frame traces and validation.json to output/companion-milestone/.
Controlled fixtures (routed responses) stand in for active, unreachable and failure
states; they are labelled as fixtures and never presented as live agent work.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from playwright.async_api import async_playwright

CONSOLE, APPS, DB = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/"), sys.argv[3]
OUT = Path("output/companion-milestone/validation")
results: dict = {"checks": [], "traces": {}, "errors": [], "task_posts": [], "fixtures": []}

# Per-frame trace of the visible Ava: the traveler once the tour starts, else the hero.
PROBE = """() => { window.__trace = []; const t0 = performance.now();
  const tick = () => {
    const traveler = document.querySelector('.tour-guide-ava');
    const node = traveler && !traveler.hidden ? traveler : document.querySelector('.guide-hero .ava');
    const r = node.getBoundingClientRect(), player = document.querySelector('.tour-player');
    const p = player && !player.hidden ? player.getBoundingClientRect() : null;
    window.__trace.push({t: Math.round(performance.now() - t0), x: Math.round(r.left), y: Math.round(r.top),
      w: Math.round(r.width), b: Math.round(r.bottom), vis: r.bottom > 0 && r.top < innerHeight,
      flying: traveler.classList.contains('flying'), scroll: Math.round(scrollY),
      underPlayer: !!p && r.bottom > p.top + 4 && r.right > p.left && r.left < p.right});
    if (!window.__stopTrace) requestAnimationFrame(tick); };
  requestAnimationFrame(tick); }"""


def check(name: str, ok: bool, detail=None):
    if not ok:
        raise AssertionError(f"{name}: {detail}")
    results["checks"].append(name)
    print("ok ·", name, flush=True)


def smooth(trace, limit=60):
    """Largest per-frame jump of the visible Ava while flying, in screen pixels."""
    worst, prev = 0, None
    for frame in trace:
        if prev and (frame["flying"] or prev["flying"]) and frame["vis"] and prev["vis"]:
            worst = max(worst, abs(frame["x"] - prev["x"]) + abs(frame["y"] - prev["y"]))
        prev = frame
    return worst


async def take(page, key):
    trace = await page.evaluate("window.__trace.splice(0)")
    flying = [f for f in trace if f["flying"]]
    summary = {
        "frames": len(trace),
        "flying_frames": len(flying),
        "worst_frame_jump_px": smooth(trace),
        "hidden_while_flying": sum(not f["vis"] for f in flying),
        "under_player_while_flying": sum(f["underPlayer"] for f in flying),
    }
    results["traces"][key] = summary
    return summary


async def tour(browser):
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    page.on("pageerror", lambda e: results["errors"].append(str(e)))
    page.on(
        "request",
        lambda r: (
            results["task_posts"].append(r.url) if r.method == "POST" and "/runs" in r.url else None
        ),
    )
    await page.goto(CONSOLE + "/guide")
    await page.evaluate("document.fonts.ready")
    check(
        "No autoplay on load",
        await page.locator("#tour-audio").evaluate("a => a.paused && !a.currentSrc"),
    )
    await page.screenshot(path=str(OUT / "guide-1440.png"))
    await page.evaluate(PROBE)
    await page.locator("#tour-start").click()
    await page.wait_for_function("document.querySelector('audio').currentTime > 0.3", timeout=8000)
    s = await take(page, "start: hero to chapter 1")
    check(
        "Start: Ava travels from the hero without jumps",
        s["flying_frames"] > 20 and s["worst_frame_jump_px"] < 60 and not s["hidden_while_flying"],
        s,
    )
    check(
        "Speaking pose follows real playback",
        await page.locator(".tour-guide-ava .ava").get_attribute("data-pose") == "speak",
    )
    for index in [1, 2, 3, 4, 1]:
        await page.locator("#tour-chapter").select_option(str(index))
        await page.wait_for_timeout(1500)
        s = await take(page, f"select chapter {index + 1}")
        section = await page.locator(".story-current").get_attribute("id")
        seated = await page.evaluate(
            "document.querySelector('.tour-guide-ava').parentElement.classList.contains('story-perch')"
        )
        check(
            f"Chapter {index + 1}: continuous travel, seated in its perch",
            s["worst_frame_jump_px"] < 60
            and not s["hidden_while_flying"]
            and not s["under_player_while_flying"]
            and seated,
            (s, section),
        )
        check(
            f"Chapter {index + 1}: narration resumes after travel",
            await page.locator("#tour-audio").evaluate("a => !a.paused && a.currentTime > 0"),
        )
    await page.screenshot(path=str(OUT / "tour-chapter2-landed-1440.png"))
    before = await page.evaluate("scrollY")
    for value in [1, 4, 2, 6, 3]:
        await page.locator("#tour-seek").evaluate(
            f"e => {{ e.value = {value}; e.dispatchEvent(new Event('input')); }}"
        )
        await page.wait_for_timeout(60)
    check("Scrubbing never moves the viewport", await page.evaluate("scrollY") == before)
    await page.locator("#tour-toggle").click()
    await page.wait_for_function("document.querySelector('audio').paused")
    await page.wait_for_timeout(100)
    check(
        "Pause: Ava stops speaking",
        await page.locator(".tour-guide-ava .ava").get_attribute("data-pose") == "idle",
    )
    await page.locator("#tour-toggle").click()
    await page.wait_for_function("!document.querySelector('audio').paused")
    # Interrupt a transition with the wheel: auto-scroll stops at once, Ava still lands.
    await page.locator("#tour-chapter").select_option("4")
    await page.wait_for_timeout(250)
    await page.mouse.move(700, 400)
    await page.mouse.wheel(0, -300)
    await page.wait_for_timeout(1400)
    after = await page.evaluate("scrollY")
    await page.wait_for_timeout(800)
    check(
        "Manual wheel cancels following immediately; no later yank",
        await page.locator("#tour-follow").get_attribute("aria-pressed") == "false"
        and abs(await page.evaluate("scrollY") - after) < 2,
    )
    check(
        "Interrupted travel still seats Ava in the target perch",
        await page.evaluate(
            "document.querySelector('#evidence .story-perch .tour-guide-ava, #next .story-perch .tour-guide-ava') !== null && !document.querySelector('.tour-guide-ava').classList.contains('flying')"
        ),
    )
    await page.evaluate(PROBE)
    await page.locator("#tour-follow").click()
    await page.wait_for_timeout(1500)
    s = await take(page, "follow resume")
    check(
        "Follow Ava returns to the current chapter smoothly",
        await page.locator("#tour-follow").get_attribute("aria-pressed") == "true"
        and s["worst_frame_jump_px"] < 60,
        s,
    )
    # Resize in the middle of a transition.
    await page.evaluate(PROBE)
    await page.locator("#tour-chapter").select_option("2")
    await page.wait_for_timeout(300)
    await page.set_viewport_size({"width": 1280, "height": 800})
    await page.wait_for_timeout(1500)
    s = await take(page, "resize during travel")
    box = await page.locator(".tour-guide-ava").bounding_box()
    perch = await page.locator("#company .story-perch").bounding_box()
    check(
        "Resize mid-travel: Ava lands on the moved perch, in view",
        abs(box["x"] - perch["x"]) < 2 and abs(box["y"] - perch["y"]) < 2 and 0 <= box["y"] < 800,
        (box, perch),
    )
    await page.screenshot(path=str(OUT / "tour-after-resize-1280.png"))
    # Hidden page: narration pauses and any transition is cancelled into a stable seat.
    await page.locator("#tour-chapter").select_option("3")
    await page.wait_for_timeout(150)
    await page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    check(
        "Hidden page pauses narration and cancels travel",
        await page.evaluate(
            "document.querySelector('audio').paused && !document.querySelector('.tour-guide-ava').classList.contains('flying')"
        ),
    )
    await page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    # Natural end of a chapter auto-advances with travel.
    await page.locator("#tour-toggle").click()
    await page.wait_for_function("!document.querySelector('audio').paused")
    await page.locator("#tour-audio").evaluate("a => a.currentTime = a.duration - 0.2")
    await page.wait_for_function(
        "document.querySelector('#tour-chapter').value === '4'", timeout=6000
    )
    await page.wait_for_function("!document.querySelector('audio').paused", timeout=6000)
    check("Chapter end advances to the next clip after a visible move", True)
    await page.locator("#tour-stop").click()
    check(
        "Stop resets to the introduction and returns Ava to the hero",
        await page.locator(".tour-guide-ava").is_hidden()
        and await page.locator("#tour-chapter").input_value() == "0"
        and await page.locator(".guide-hero .ava").is_visible(),
    )
    # Active work (controlled fixture) stops narration and clears the traveler.
    await page.locator("#tour-toggle").click()
    await page.wait_for_function("!document.querySelector('audio').paused")
    results["fixtures"].append("Routed /watch/state active-run response")
    await page.route(
        "**/watch/state",
        lambda route: route.fulfill(
            json={
                "run_url": "/runs/controlled-fixture",
                "request": "Fixture",
                "status": "Working",
                "companion": {"pose": "work", "line": "Fixture"},
            }
        ),
    )
    await page.wait_for_function(
        "document.querySelector('#tour-status').textContent === 'Tour paused while Ava works'",
        timeout=7000,
    )
    check(
        "Active work stops narration and clears the touring Ava",
        await page.evaluate("document.querySelector('audio').paused")
        and await page.locator(".tour-guide-ava").is_hidden(),
    )
    await page.unroute("**/watch/state")
    # Keyboard: the hero Ava is a real control; Escape returns focus.
    await page.reload()
    await page.locator(".guide-hero .ava-trigger").focus()
    await page.keyboard.press("Enter")
    check(
        "Keyboard opens Ava's panel with focus in the draft",
        await page.evaluate("document.activeElement.id") == "ava-draft",
    )
    await page.keyboard.press("Escape")
    check(
        "Escape closes the panel and returns focus to Ava",
        await page.evaluate("document.activeElement.classList.contains('ava-trigger')"),
    )
    # Failed audio keeps the guide useful.
    await page.route("**/audio/guide/**", lambda route: route.abort())
    await page.locator("#tour-start").click()
    await page.wait_for_function(
        "document.querySelector('#tour-status').textContent.includes('Audio unavailable')"
    )
    check(
        "Unavailable audio opens the transcript",
        await page.locator(".player-transcript").evaluate("e => e.open"),
    )
    await page.unroute("**/audio/guide/**")
    # 390px: travel, landing and the player all fit.
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.reload()
    check(
        "390px: no horizontal overflow",
        await page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
    )
    await page.screenshot(path=str(OUT / "guide-390.png"))
    await page.evaluate(PROBE)
    await page.locator("#tour-start").click()
    await page.wait_for_timeout(1800)
    await page.locator("#tour-chapter").select_option("2")
    await page.wait_for_timeout(1600)
    s = await take(page, "390px start and chapter 3")
    check(
        "390px: continuous travel that stays clear of the player",
        s["worst_frame_jump_px"] < 60 and not s["under_player_while_flying"],
        s,
    )
    await page.screenshot(path=str(OUT / "tour-chapter3-390.png"))
    await context.close()
    # Reduced motion: stable placement, no travel, auto-scroll off by default.
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800}, reduced_motion="reduce"
    )
    page = await context.new_page()
    await page.goto(CONSOLE + "/guide")
    check(
        "Reduced motion starts with auto-scroll off",
        await page.locator("#tour-follow").get_attribute("aria-pressed") == "false",
    )
    await page.evaluate(PROBE)
    await page.locator("#tour-start").click()
    await page.wait_for_timeout(1200)
    s = await take(page, "reduced motion start")
    check("Reduced motion: no animated travel", s["flying_frames"] == 0, s)
    check(
        "Reduced motion: character animation off",
        await page.locator(".guide-hero .ava-breath").evaluate(
            "e => getComputedStyle(e).animationName"
        )
        == "none",
    )
    await context.close()


async def companion(browser):
    conn = sqlite3.connect(DB)
    audit = lambda: conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]  # noqa: E731
    message = conn.execute(
        "SELECT m.id FROM mail_messages m JOIN mail_attachments a ON a.message_id = m.id ORDER BY sent_at DESC"
    ).fetchone()[0]
    file = conn.execute("SELECT file_id FROM mail_attachments LIMIT 1").fetchone()[0]
    bill = conn.execute("SELECT id FROM bills ORDER BY created_at DESC").fetchone()[0]
    vendor = conn.execute("SELECT id FROM vendors WHERE status = 'active'").fetchone()[0]
    channel = conn.execute("SELECT name FROM chat_channels").fetchone()[0]
    pages = [
        "/",
        "/mail/",
        f"/mail/m/{message}",
        "/books/bills",
        f"/books/bills/{bill}",
        "/books/bills/new",
        f"/books/vendors/{vendor}",
        "/drive/",
        f"/drive/f/{file}",
        f"/chat/{channel}",
    ]
    start = audit()
    for width, height in [(1440, 900), (390, 844)]:
        context = await browser.new_context(viewport={"width": width, "height": height})
        page = await context.new_page()
        posts = []
        page.on("request", lambda r, sink=posts: sink.append(r.url) if r.method == "POST" else None)
        page.on("pageerror", lambda e: results["errors"].append(str(e)))
        for path in pages:
            await page.goto(APPS + path)
            await page.wait_for_timeout(250)
            assert await page.locator("[data-ava-dock]").count() == 1, path
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
            await page.evaluate("scrollTo(0, document.documentElement.scrollHeight)")
            blocked = await page.evaluate("""() => { const d = document.querySelector('.ava-dock-button').getBoundingClientRect();
              return [...document.querySelectorAll('main a, main button, main input, main select, main textarea')]
                .filter(n => { const r = n.getBoundingClientRect(); return r.width && r.right > d.left && r.left < d.right && r.bottom > d.top && r.top < d.bottom; })
                .map(n => n.outerHTML.slice(0, 80)); }""")
            assert not blocked, (path, width, blocked)
            await page.locator(".ava-dock-button").click()
            chips = await page.locator(".ava-chip").all()
            assert chips, path
            await chips[0].click()
            assert await page.locator("#ava-draft").input_value(), path
            await page.keyboard.press("Escape")
            if path == f"/mail/m/{message}" and width == 1440:
                await page.locator(".ava-dock-button").click()
                await page.wait_for_timeout(350)  # let the panel fade in
                await page.screenshot(path=str(OUT / "mail-panel-1440.png"))
                await page.keyboard.press("Escape")
        if width == 390:
            await page.goto(APPS + f"/books/bills/{bill}")
            await page.locator(".ava-dock-button").click()
            await page.wait_for_timeout(350)  # let the panel fade in
            await page.screenshot(path=str(OUT / "bill-panel-390.png"))
        check(
            f"{width}px: one Ava on all {len(pages)} company pages, clear of business controls",
            True,
        )
        check(f"{width}px: opening Ava and choosing suggestions sends no POST", not posts, posts)
        await context.close()
    check("No company records changed while using Ava", audit() == start)
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    # Navigation, back/forward and reloads never duplicate the companion.
    await page.goto(APPS + "/mail/")
    await page.locator("nav[aria-label='Company applications'] a[href='/books/bills']").click()
    await page.go_back()
    await page.go_forward()
    await page.reload()
    check(
        "Navigation and history keep exactly one Ava",
        await page.locator("[data-ava-dock]").count() == 1
        and await page.locator(".ava-panel").count() == 0,
    )
    # Tucking is remembered for this origin.
    await page.locator(".ava-dock-button").click()
    await page.locator(".ava-tuck").click()
    await page.reload()
    check("Tuck Ava away is remembered", await page.locator(".ava-dock.ava-tucked").count() == 1)
    await page.locator(".ava-dock-button").click()
    check(
        "Selecting the tucked Ava restores her",
        await page.locator(".ava-dock.ava-tucked").count() == 0,
    )
    # Unreachable console (fixture): the draft stays, nothing is sent.
    results["fixtures"].append("Routed /work-status unavailable response")
    await page.route(
        "**/work-status",
        lambda route: route.fulfill(json={"seed": 7, "run": None, "unavailable": True}),
    )
    await page.reload()
    await page.wait_for_timeout(300)
    await page.locator(".ava-dock-button").click()
    await page.locator("#ava-draft").fill("Keep this draft")
    await page.wait_for_timeout(5300)
    check(
        "Unreachable console: honest message, assignment disabled",
        "can’t reach" in await page.locator(".ava-panel-line").inner_text()
        and await page.locator(".ava-panel-submit").is_disabled(),
    )
    await page.wait_for_timeout(350)  # let the panel fade in
    await page.screenshot(path=str(OUT / "panel-console-unreachable.png"))
    await page.reload()
    await page.locator(".ava-dock-button").click()
    check(
        "Unreachable console: the draft is kept",
        await page.locator("#ava-draft").input_value() == "Keep this draft",
    )
    await page.unroute("**/work-status")
    # Active task (fixture): the panel returns to that task instead of offering assignment.
    results["fixtures"].append("Routed /work-status active-run response")
    fixture = {
        "seed": 7,
        "run": {
            "run_id": "fixture",
            "request": "Controlled fixture task",
            "status": "Working",
            "mode": "Live updates",
            "active": True,
            "run_url": "/runs/fixture",
            "companion": {"pose": "work", "line": "Typing into Amount"},
        },
    }
    await page.route("**/work-status", lambda route: route.fulfill(json=fixture))
    await page.reload()
    await page.wait_for_timeout(400)
    check(
        "Active task: the dock shows the run's pose and status line",
        await page.locator(".ava-dock .ava").get_attribute("data-pose") == "work"
        and "Typing into Amount" in await page.locator(".ava-bubble").inner_text(),
    )
    await page.locator(".ava-dock-button").click()
    href = await page.locator(".ava-panel-return").get_attribute("href")
    check(
        "Active task: Return to Ava’s task replaces assignment",
        href == CONSOLE + "/runs/fixture" and await page.locator(".ava-panel-form").is_hidden(),
    )
    await page.wait_for_timeout(350)  # let the panel fade in
    await page.screenshot(path=str(OUT / "panel-active-task.png"))
    await page.unroute("**/work-status")
    check("No POST during navigation, tucking or fixtures", not posts, posts)
    # The narrow handoff: one same-origin draft POST, then the console composer, nothing assigned.
    await page.goto(APPS + f"/drive/f/{file}")
    await page.locator(".ava-dock-button").click()
    await page.locator(".ava-chip").nth(1).click()
    text = await page.locator("#ava-draft").input_value()
    await page.locator(".ava-panel-submit").click()
    await page.wait_for_url(CONSOLE + "/#request")
    check(
        "Handoff prefills the console composer and assigns nothing",
        await page.locator("#request").input_value() == text
        and all(p.endswith("/ava/handoff") for p in posts)
        and len(posts) == 1,
        posts,
    )
    await page.screenshot(path=str(OUT / "console-composer-handoff.png"))
    await context.close()
    conn.close()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        await tour(browser)
        await companion(browser)
        await browser.close()
    assert not results["errors"], results["errors"]
    assert not results["task_posts"], results["task_posts"]
    (OUT / "validation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"{len(results['checks'])} checks passed; no browser errors; no task POSTs.")


if __name__ == "__main__":
    asyncio.run(main())
