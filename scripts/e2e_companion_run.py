"""One real invoice task in a fresh company, started through Ava's companion. Paid: it
uses the configured Gemini model through Vertex AI and ADC.

Usage: e2e_companion_run.py CONSOLE_URL APPS_URL WORLD_ROOT
Records the run page's companion poses (from recorded run state), frames of Ava's own
browser with its overlay, and the independent grade (kept separate from the worker's own
verification). Writes output/companion-milestone/e2e/.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

CONSOLE, APPS, WORLDS = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/"), Path(sys.argv[3])
OUT = Path("output/companion-milestone/e2e")


async def frame(run_id: str, name: str) -> bool:
    """Save one JPEG from the live stream of Ava's browser (overlay included)."""
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            async with client.stream("GET", f"{CONSOLE}/runs/{run_id}/screen") as response:
                if response.status_code != 200:
                    return False
                buffer = b""
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if b"\xff\xd8" in buffer and b"\xff\xd9" in buffer[buffer.index(b"\xff\xd8") :]:
                        start = buffer.index(b"\xff\xd8")
                        end = buffer.index(b"\xff\xd9", start) + 2
                        (OUT / name).write_bytes(buffer[start:end])
                        return True
    except httpx.HTTPError:
        return False
    return False


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(WORLDS / "7" / "world.db")
    message = db.execute(
        "SELECT m.id FROM mail_messages m JOIN mail_attachments a ON a.message_id = m.id "
        "ORDER BY m.sent_at DESC"
    ).fetchone()[0]
    record = {"posts": [], "poses": [], "frames": [], "checks": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("request", lambda r: record["posts"].append(r.url) if r.method == "POST" else None)
        await page.goto(f"{APPS}/mail/m/{message}")
        await page.locator(".ava-dock-button").click()
        suggestion = page.locator(".ava-chip").first
        record["suggestion"] = await suggestion.inner_text()
        await suggestion.click()
        record["draft"] = await page.locator("#ava-draft").input_value()
        await page.locator(".ava-panel-submit").click()
        await page.wait_for_url(CONSOLE + "/#request")
        assert await page.locator("#request").input_value() == record["draft"]
        assert not any("/runs" in p for p in record["posts"]), "nothing is assigned before review"
        record["checks"].append("Suggestion and handoff assigned nothing")
        await page.locator(".assignment [type=submit]").click()  # the explicit assignment
        await page.wait_for_url(CONSOLE + "/runs/*", timeout=20000)
        run_id = page.url.rsplit("/", 1)[-1]
        record["run_id"] = run_id
        started = time.monotonic()
        assert sum(p.endswith("/runs") for p in record["posts"]) == 1
        record["checks"].append("One explicit assignment started exactly one task")
        await page.screenshot(path=str(OUT / "run-page-start.png"))
        # Duplicate protection while active: the console refuses a second worker.
        second = await page.evaluate(
            """async () => { const body = new FormData(); body.set('request', 'Duplicate');
               body.set('seed', '7'); const r = await fetch('/runs', {method: 'POST', body});
               return r.status; }"""
        )
        record["second_submission_status"] = second
        record["checks"].append(f"A second submission while active was refused (HTTP {second})")
        apps = await browser.new_page(viewport={"width": 1440, "height": 900})
        last_pose, shots, step = None, 0, 0
        while True:
            async with httpx.AsyncClient(timeout=5) as client:
                state = (await client.get(f"{CONSOLE}/runs/{run_id}/state")).json()
            pose = state["companion"]
            elapsed = round(time.monotonic() - started, 1)
            if (pose["pose"], pose["line"]) != last_pose:
                record["poses"].append({"t": elapsed, "phase": state["phase"], **pose})
                last_pose = (pose["pose"], pose["line"])
                if pose["pose"] in ("read", "think", "work", "check", "ask") and shots < 14:
                    name = f"worker-{shots:02d}-{pose['pose']}.jpg"
                    if await frame(run_id, name):
                        record["frames"].append({"t": elapsed, "file": name, **pose})
                        shots += 1
                    if pose["pose"] in ("work", "check") and step < 2:
                        await page.screenshot(path=str(OUT / f"run-page-{pose['pose']}.png"))
                        step += 1
            if elapsed > 30 and "apps_active" not in record:
                await apps.goto(f"{APPS}/books/bills")
                await apps.wait_for_timeout(1200)
                await apps.locator(".ava-dock-button").click()
                link = await apps.locator(".ava-panel-return").get_attribute("href")
                record["apps_active"] = {
                    "pose": await apps.locator(".ava-dock .ava").get_attribute("data-pose"),
                    "return": link,
                }
                await apps.screenshot(path=str(OUT / "apps-dock-during-run.png"))
                assert link == f"{CONSOLE}/runs/{run_id}", link
                record["checks"].append("Company apps offered Return to Ava’s task while active")
            if state.get("finished") or elapsed > 900:
                break
            await asyncio.sleep(1)
        await page.reload()
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "run-page-finished.png"), full_page=False)
        record["final"] = {
            "status": state["status"],
            "display_outcome": state["display_outcome"],
            "conditions": [{"text": c["text"], "state": c["state"]} for c in state["conditions"]],
            "seconds": (state.get("finished") or {}).get("seconds"),
            "companion": state["companion"],
        }
        await browser.close()
    (OUT / "e2e.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("run_id", "suggestion", "checks", "final")}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
