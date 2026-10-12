"""Play the guide's tour through the Tribunal scene in real Chromium and report, every half
second, whether the current dialogue line is visible above the tour player, and whether the
tour carries on afterwards. No task is started and no model is called.

  .venv/bin/python scripts/inspect_guide_scene.py [console URL] [viewport height] [mode]

mode: plain (default), wheel (the reader scrolls by hand mid-scene) or replay ("Play the
scene" pressed during the tour). Exits non-zero if a line is hidden while the tour frames the
scene, or if the tour stops before its last chapter.
"""

import asyncio
import sys

from playwright.async_api import async_playwright

STATE = """(() => {
  const audio = document.getElementById('tour-audio');
  const now = document.querySelector('.gx-bubble.now');
  const player = document.querySelector('.tour-player').getBoundingClientRect();
  const box = now ? now.getBoundingClientRect() : null;
  return {chapter: document.getElementById('tour-chapter').value,
          line: document.getElementById('scene').dataset.line, t: audio.currentTime,
          visible: box ? box.top >= 62 && box.bottom <= player.top : null,
          follow: document.getElementById('tour-follow').getAttribute('aria-pressed') === 'true',
          status: document.getElementById('tour-status').textContent};
})()"""


async def main(base: str, height: int, mode: str) -> int:
    problems, last = [], None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = await browser.new_page(viewport={"width": 1440, "height": height})
        page.on("pageerror", lambda error: problems.append(f"page error: {error}"))
        await page.goto(base + "/guide", wait_until="networkidle")
        await page.locator("#tour-start").click()
        await page.wait_for_timeout(1500)
        await page.locator("#tour-chapter").select_option("4")
        tour_scrolled_by_hand = False
        for tick in range(260):
            await page.wait_for_timeout(500)
            if mode == "wheel" and tick == 40:
                await page.mouse.move(700, 300)
                await page.mouse.wheel(0, 300)
                tour_scrolled_by_hand = True
            if mode == "replay" and tick == 20:
                await page.locator("#scene-play").click()
            state = await page.evaluate(STATE)
            key = (state["chapter"], state["line"], state["status"])
            if key != last:
                last = key
                print(f"{tick / 2:5.1f}s", state)
            # Judge only once the tour has landed on the scene and its audio is playing.
            framing = state["chapter"] == "4" and state["t"] > 0.5 and state["follow"]
            if framing and not tour_scrolled_by_hand and state["visible"] is False:
                problems.append(f"line {state['line']} hidden behind the tour player")
            if "complete" in state["status"].lower():
                break
        if "Tour complete" not in state["status"]:
            problems.append(f"the tour stopped early: {state['status']}")
        await browser.close()
    problems = list(dict.fromkeys(problems))
    print("\n".join(problems) or "Every line visible; the tour reached its last chapter.")
    return 1 if problems else 0


if __name__ == "__main__":
    args = sys.argv[1:] + [None] * 3
    sys.exit(
        asyncio.run(
            main(args[0] or "http://localhost:8011", int(args[1] or 760), args[2] or "plain")
        )
    )
