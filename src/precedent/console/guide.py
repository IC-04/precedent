"""Read-only guide content and version-matched prerecorded narration.

A chapter is either narrated by Ava (`narration`, optional `performance`) or performed as a
`dialogue` between Ava and Loki: one line per speaker, each synthesized in its own voice and
joined into one clip whose line start times (`cues`) drive the scene."""

import hashlib
import json
import re
from pathlib import Path

CONTENT = Path(__file__).with_name("guide.json")
EVIDENCE = Path(__file__).with_name("guide_evidence.json")
AUDIO = Path(__file__).parents[1] / "apps" / "static" / "audio" / "guide"
TAG = re.compile(r"\[[a-z ]+\]")


def script_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def spoken_text(chapter: dict) -> str:
    """What the voice performs: the narration with optional pause and delivery tags."""
    if "dialogue" in chapter:
        return "\n".join(line.get("performance") or line["text"] for line in chapter["dialogue"])
    return chapter.get("performance") or chapter["narration"]


def transcript(chapter: dict) -> str:
    """The words as read: narration, or each dialogue line with its speaker."""
    if "dialogue" in chapter:
        return " ".join(
            f"{line['speaker'].capitalize()}: {line['text']}" for line in chapter["dialogue"]
        )
    return chapter["narration"]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", TAG.sub(" ", text.lower().replace("’", "'")).replace("'", ""))


def performance_matches(chapter: dict) -> bool:
    """The transcript stays exact: the performance may add pauses, never different words."""
    if "dialogue" in chapter:
        return all(
            words(line.get("performance") or line["text"]) == words(line["text"])
            for line in chapter["dialogue"]
        )
    return words(spoken_text(chapter)) == words(chapter["narration"])


def chapter_key(chapter: dict, voice: dict, loki: dict | None = None) -> str:
    """Script, performance, provider, model, voice and delivery all invalidate a clip."""
    if "dialogue" in chapter:
        lines = [
            [line["speaker"], line["text"], line.get("performance") or line["text"]]
            for line in chapter["dialogue"]
        ]
        material = {"dialogue": lines, "voice": voice, "loki": loki}
    else:
        material = {
            "narration": chapter["narration"],
            "spoken": spoken_text(chapter),
            "voice": voice,
        }
    return script_hash(json.dumps(material, sort_keys=True))


def guide_key(chapter: dict, guide: dict) -> str:
    return chapter_key(chapter, guide["narration_voice"], guide.get("loki_voice"))


def tour_version(guide: dict) -> str:
    keys = [guide_key(c, guide) for c in guide["chapters"]]
    return "v-" + script_hash("".join(keys))[:12]


def mp3_seconds(data: bytes) -> float:
    """Duration from MPEG audio frame headers; 0 when the bytes are not a decodable MP3."""
    rates = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
    kbps = {
        3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
        2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    }
    i, seconds, frames = 0, 0.0, 0
    if data[:3] == b"ID3" and len(data) > 10:
        i = 10 + ((data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9])
    while i + 4 <= len(data):
        b1, b2 = data[i + 1], data[i + 2]
        version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        rate_index, bitrate_index = (b2 >> 2) & 3, b2 >> 4
        if data[i] != 0xFF or (b1 & 0xE0) != 0xE0 or version == 1 or layer != 1:
            if frames:
                break
            i += 1
            continue
        if rate_index == 3 or bitrate_index in (0, 15):
            break
        rate = rates[version][rate_index]
        bitrate = kbps[3 if version == 3 else 2][bitrate_index] * 1000
        samples = 1152 if version == 3 else 576
        size = samples // 8 * bitrate // rate + ((b2 >> 1) & 1)
        if size <= 4:
            break
        seconds += samples / rate
        frames += 1
        i += size
    return seconds if frames > 10 else 0.0


def load_guide(static: Path) -> dict:
    guide = json.loads(CONTENT.read_text())
    directory = static / "audio" / "guide"
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    voice = guide.get("narration_voice", {})
    entries = manifest.get("chapters", {}) if isinstance(manifest.get("chapters"), dict) else {}
    ready = []
    for chapter in guide["chapters"]:
        entry = entries.get(chapter["id"], {})
        file = str(entry.get("file", ""))
        ready.append(
            performance_matches(chapter)
            and entry.get("key") == guide_key(chapter, guide)
            and re.fullmatch(r"v-[0-9a-f]{12}/[a-z]+\.mp3", file) is not None
            and (directory / file).is_file()
        )
    if not entries and not voice.get("model"):
        # The first, unversioned manifest (script hash and voice name per flat file).
        entries, ready = {}, []
        for chapter in guide["chapters"]:
            legacy = manifest.get(chapter["id"], {}) if isinstance(manifest, dict) else {}
            file = f"{chapter['id']}.mp3"
            ready.append(
                "performance" not in chapter
                and "dialogue" not in chapter
                and legacy.get("script_hash") == script_hash(chapter["narration"])
                and legacy.get("voice") == voice.get("voice")
                and (directory / file).is_file()
            )
            seconds = mp3_seconds((directory / file).read_bytes()) if ready[-1] else 0
            entries[chapter["id"]] = {"file": file, "seconds": seconds}
    # All chapters from one matching version, or none: never a half-updated tour.
    complete = bool(ready) and all(ready)
    for chapter in guide["chapters"]:
        entry = entries.get(chapter["id"], {})
        file = entry.get("file")
        chapter["audio"] = f"/static/audio/guide/{file}" if complete else None
        cues = entry.get("cues")
        chapter["cues"] = (
            [float(c) for c in cues]
            if complete and isinstance(cues, list) and len(cues) == len(chapter.get("dialogue", []))
            else None
        )
        chapter["narration"] = transcript(chapter)
        chapter.pop("performance", None)
        for line in chapter.get("dialogue", []):
            line.pop("performance", None)
    guide["audio_ready"] = complete
    guide["audio_seconds"] = (
        round(sum(float(entries[c["id"]].get("seconds", 0)) for c in guide["chapters"]))
        if complete
        else None
    )
    loki = guide.get("loki_voice") or {}
    voices = voice.get("voice") + (f" and {loki['voice']}" if loki.get("voice") else "")
    guide["voice_label"] = (
        f"{voices} · {voice.get('model') or voice.get('provider')}" if complete else None
    )
    return guide


def load_evidence(path: Path = EVIDENCE) -> dict:
    """The guide's evidence snapshot, written by scripts/build_guide_evidence.py from retained
    runs. Empty when absent: the page then shows its text without numbers."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def evidence_runs(evidence: dict) -> set[str]:
    """Every run the snapshot cites, so the page links only to runs installed here."""
    found: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "run_id" and isinstance(item, str):
                    found.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(evidence)
    return found
