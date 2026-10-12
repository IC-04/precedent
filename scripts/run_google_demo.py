"""Launch an authorized synthetic task through the owner UI and record actual browser frames.
No account credentials, OAuth pages, or invented execution events are used here.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    task = Path(sys.argv[1]).read_text()
    output = ROOT / "output/google-connected-worker-milestone"
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9229")
        owner = next(x for x in browser.contexts[0].pages if "localhost:8250" in x.url)
        await owner.goto("http://localhost:8250/workspace")
        await owner.locator("textarea[name=task]").fill(task)
        await owner.locator("input[name=consent]").check()
        await owner.get_by_role("button", name="Start working →", exact=True).click()
        run_id = owner.url.rsplit("/", 1)[-1]
        print("Run:", run_id, flush=True)
        directory = ROOT / ".connected/runs" / run_id
        deadline = time.monotonic() + 45
        screen = None
        while time.monotonic() < deadline:
            path = directory / "events.jsonl"
            events = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
            screen = next((e["data"] for e in events if e["data"].get("kind") == "screen"), None)
            if screen:
                break
            await asyncio.sleep(1)
        encoder_file = Path("/tmp/precedent-ffmpeg-path")
        if screen and encoder_file.exists():
            log = (output / (run_id + "-recording.log")).open("wb")
            subprocess.Popen(
                [
                    encoder_file.read_text(),
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-f",
                    "mpjpeg",
                    "-use_wallclock_as_timestamps",
                    "1",
                    "-i",
                    screen["url"],
                    "-t",
                    "90",
                    "-an",
                    "-vf",
                    "fps=15,scale=1280:-2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(output / (run_id + "-browser.mp4")),
                ],
                stdout=log,
                stderr=log,
            )
            print("Recording genuine live browser frames; OAuth excluded.", flush=True)
        else:
            print("Continuous recording unavailable; no video claimed.", flush=True)


asyncio.run(main())
