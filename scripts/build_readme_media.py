"""Curate the existing film into public README media; never copy private run logs.

Requires the local ignored output/film-assets source package. Generated assets are
committed, so a reader does not need the source footage to view the README.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/film-assets"
TARGET = ROOT / "assets/readme"
SHOWCASE = ROOT / "output/readme-build/excerpts"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", *args], check=True)


def frame(segment: str, second: float, name: str, width: int = 1600) -> dict:
    out = TARGET / f"{name}.webp"
    ffmpeg(
        "-ss",
        str(second),
        "-i",
        str(SOURCE / "segments" / f"{segment}.mp4"),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-quality",
        "88",
        "-y",
        str(out),
    )
    return {
        "file": out.name,
        "source": f"segments/{segment}.mp4",
        "at_seconds": second,
        "kind": "recorded screenshot",
        "edits": "Resize only; source privacy masks retained",
    }


def preview(name: str, slices: list[tuple[str, float, float]], note: str) -> dict:
    inputs, trims = [], []
    for i, (segment, start, duration) in enumerate(slices):
        inputs += [
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(SOURCE / "segments" / f"{segment}.mp4"),
        ]
        trims.append(f"[{i}:v]setpts=PTS-STARTPTS,fps=8,scale=960:-2[v{i}]")
    chain = ";".join(trims) + ";" + "".join(f"[v{i}]" for i in range(len(slices)))
    chain += f"concat=n={len(slices)}:v=1:a=0,split[a][b];"
    chain += (
        "[a]palettegen=max_colors=192:stats_mode=diff[p];["
        "b][p]paletteuse=dither=bayer:bayer_scale=3[v]"
    )
    out = TARGET / f"{name}.gif"
    ffmpeg(*inputs, "-filter_complex", chain, "-map", "[v]", "-loop", "0", "-y", str(out))
    return {
        "file": out.name,
        "kind": "edited recorded preview",
        "caption": note,
        "output_seconds": sum(x[2] for x in slices),
        "fps": 8,
        "sources": [
            {"file": f"segments/{s}.mp4", "start_seconds": t, "duration_seconds": d}
            for s, t, d in slices
        ],
        "edits": (
            "Cuts, resize and GIF encoding. Existing speed, staging and privacy labels retained."
        ),
    }


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    (SHOWCASE / "media").mkdir(parents=True, exist_ok=True)
    assets = [
        frame("b01-hello", 9, "guide"),
        frame("c01-ask", 3, "workspace"),
        frame("c08-real-gmail", 3, "gmail"),
        frame("c09-real-calendar", 3, "calendar"),
        frame("d02-verdict", 3, "tribunal"),
        frame("e03-draft", 3, "memory"),
        frame("f04-review", 8, "teaching"),
        frame("c04-typing", 3, "poster"),
    ]
    gmail, calendar = Image.open(TARGET / "gmail.webp"), Image.open(TARGET / "calendar.webp")
    results = Image.new("RGB", (1600, 900), "#faf9f6")
    results.paste(gmail.resize((800, 450)), (0, 225))
    results.paste(calendar.resize((800, 450)), (800, 225))
    results.save(TARGET / "native-results.webp", quality=88)
    assets.append(
        {
            "file": "native-results.webp",
            "sources": ["gmail.webp", "calendar.webp"],
            "kind": "two recorded screenshots",
            "edits": "Side by side on paper; no UI content altered",
        }
    )
    assets += [
        preview(
            "execution",
            [
                ("c01-ask", 0.4, 3),
                ("c02-read", 1, 3),
                ("c04-typing", 1, 5),
                ("c06-calendar", 2, 3),
                ("c08-real-gmail", 1, 2),
                ("c09-real-calendar", 1, 2),
            ],
            (
                "One request across company apps, real Gmail and Calendar. "
                "Recorded run 5080; edited to 18 seconds."
            ),
        ),
        preview(
            "verification",
            [("d01-hearing", 10, 3), ("d02-verdict", 2, 3), ("d03-scene-caught", 4, 3)],
            (
                "Separate invoice hearing and a labelled staged explanation of "
                "recovery; not the Gmail run's verdict."
            ),
        ),
        preview(
            "learning",
            [
                ("e01-memory", 0.3, 3),
                ("e03-draft", 0.4, 3),
                ("f03-watch", 2, 3),
                ("f04-review", 6, 3),
            ],
            (
                "Recorded memory, demonstration interpretation and a draft skill. "
                "A candidate is not an activated skill."
            ),
        ),
    ]
    # Host short playable excerpts on Pages; the full film remains a release asset.
    for segment in [
        "c04-typing",
        "c06-calendar",
        "c08-real-gmail",
        "c09-real-calendar",
        "d03-scene-caught",
        "e03-draft",
        "f03-watch",
    ]:
        ffmpeg(
            "-i",
            str(SOURCE / "segments" / f"{segment}.mp4"),
            "-vf",
            "scale=1280:-2",
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-y",
            str(SHOWCASE / "media" / f"{segment}.mp4"),
        )
    for asset in assets:
        asset["bytes"] = (TARGET / asset["file"]).stat().st_size
    manifest = {
        "version": 1,
        "source_film": "output/film-assets/precedent-demo.mp4",
        "source_film_seconds": 286.14,
        "source_resolution": "1920x1080",
        "privacy": (
            "Use only reviewed edited segments with baked-in masks. Raw "
            "profiles, sources, run logs and OAuth screens are excluded."
        ),
        "film_url": (
            "https://github.com/IC-04/precedent/releases/d"
            "ownload/readme-showcase-v1/precedent-demo.mp4"
        ),
        "assets": assets,
        "runs": [
            {
                "id": "20261011-210344-d343",
                "task": "Gmail briefing and Calendar hold",
                "seconds": 158.2,
                "steps": 34,
                "worker_checks": "13/13 pass",
                "independent": "13/13 pass",
                "assessment": "Native browser execution; fresh Google API readback and Tribunal",
            },
            {
                "id": "20261012-121618-5080",
                "task": "Cross-app briefing (film source)",
                "seconds": 257.0,
                "steps": 41,
                "worker_checks": "16/16 pass",
                "independent": "15 pass, 1 disputed",
                "assessment": "Worker completed; independent Tribunal retained a dispute",
            },
            {
                "id": "20261010-185357-0f7d",
                "task": "Invoice entry and approval routing",
                "seconds": 270.4,
                "steps": 33,
                "worker_checks": "11/11 pass",
                "independent": "Tribunal 11/11; hidden-truth grade 14/14",
                "assessment": (
                    "Separate generated-company invoice run; source of the passing "
                    "hearing shown in the film"
                ),
            },
            {
                "id": "20261010-154410-fc9a",
                "task": "Different invoice after restart",
                "worker_checks": "12/12 pass",
                "independent": "14/14 pass",
                "assessment": (
                    "Scoped notes and an activated invoice skill reused; not a "
                    "general speedup claim"
                ),
            },
        ],
        "staged_recovery_run": "20261010-193810-dd3f",
        "chapter_seconds": [0, 55, 119, 138, 207, 269],
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(x["bytes"] for x in assets)
    print(
        f"Curated assets: {total / 1024**2:.2f} MiB; largest GIF: "
        f"{max(x['bytes'] for x in assets if x['file'].endswith('.gif')) / 1024**2:.2f} MiB"
    )


if __name__ == "__main__":
    main()
