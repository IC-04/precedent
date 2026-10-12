"""Generate the guide's narration with Google Cloud Text-to-Speech and ADC, once per version.

  --check            verify TTS access and the configured voice; no synthesis
  --sample DIR       synthesize short introduction samples for comparison; never touches the app
  (default)          synthesize the whole tour into a new versioned folder (manifest.next.json)
  --activate         validate the pending version and switch the app to it in one rename

The voices, model and delivery prompts live in guide.json (`narration_voice` for Ava,
`loki_voice` for Loki) and are part of every chapter's cache key with its script and
performance text. A dialogue chapter is synthesized line by line in each speaker's voice
and joined into one clip; its manifest entry records each line's start time (`cues`). The
page serves narration only when every chapter matches the active manifest, so it never
plays a half-updated tour.
No credentials are written to the app and no provider request happens on page visits.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
from pathlib import Path

import google.auth
import requests
from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession

from precedent.console.guide import (
    AUDIO,
    CONTENT,
    guide_key,
    mp3_seconds,
    spoken_text,
    tour_version,
    words,
)

BASE = "https://texttospeech.googleapis.com/v1"
# Short comparison candidates for the introduction (voice, model). Gemini-TTS voices take
# a natural-language delivery prompt; the current Chirp 3 HD voice is the baseline.
SAMPLES = [
    ("Sulafat", "gemini-2.5-pro-tts"),
    ("Achird", "gemini-2.5-pro-tts"),
    ("Aoede", "gemini-2.5-pro-tts"),
]


def session_for(project: str) -> AuthorizedSession:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"], quota_project_id=project
    )
    return AuthorizedSession(credentials)


def synthesize(session, voice: dict, text: str, retries: int = 2) -> bytes:
    body = {
        "input": {"text": text},
        "voice": {"languageCode": voice["language"], "name": voice["voice"]},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    if voice.get("model"):
        body["voice"]["modelName"] = voice["model"]
        body["input"]["prompt"] = voice["style"]
    for attempt in range(3):  # the provider occasionally stalls; a read retry is safe
        try:
            response = session.post(BASE + "/text:synthesize", json=body, timeout=120)
            break
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise
    if not response.ok:
        raise SystemExit(f"Synthesis failed ({response.status_code}): {response.text[:1000]}")
    audio = base64.b64decode(response.json()["audioContent"])
    if mp3_seconds(audio) <= 0:
        raise SystemExit("The provider returned audio that is not a decodable MP3.")
    # A take that stops early is shorter than any natural reading. Measured: complete takes
    # run at 2.0 to 2.7 words a second; two truncated takes came back at 3.7 and 7.7.
    count = len(words(text))
    if count >= 10 and mp3_seconds(audio) < count / 3.2:
        if retries:
            return synthesize(session, voice, text, retries - 1)
        raise SystemExit(f"The provider returned a truncated take: {text[:60]}")
    return audio


def tighten(audio: bytes, longest: float, gap: float = 0.0) -> bytes:
    """Cap every silence at `longest` seconds and end on `gap` seconds of silence.

    Delivery directions occasionally produce multi-second pauses (a 7.7 s one was measured in
    the first Loki take). Only silence is shortened; the spoken words are untouched."""
    import subprocess
    import tempfile

    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "in.mp3", Path(tmp) / "out.mp3"
        source.write_bytes(audio)
        filters = (
            "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.05:"
            f"stop_periods=-1:stop_duration={longest}:stop_threshold=-42dB:stop_silence={longest}"
        )
        if gap:
            filters += f",apad=pad_dur={gap}"
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(source),
             "-af", filters, "-ar", "24000", "-ac", "1", "-b:a", "48k", str(target)],
            check=True,
        )  # fmt: skip
        return target.read_bytes()


def frames_only(audio: bytes) -> bytes:
    """MPEG frames without ID3 tags, so clips can be joined into one playable file."""
    if audio[:3] == b"ID3" and len(audio) > 10:
        audio = audio[10 + ((audio[6] << 21) | (audio[7] << 14) | (audio[8] << 7) | audio[9]) :]
    if len(audio) > 128 and audio[-128:-125] == b"TAG":
        audio = audio[:-128]
    return audio


def synthesize_dialogue(session, guide: dict, chapter: dict) -> tuple[bytes, list[float]]:
    """Each line in its speaker's voice, joined; cues are the line start times in seconds."""
    voices = {"ava": guide["narration_voice"], "loki": guide["loki_voice"]}
    joined, cues, at = b"", [], 0.0
    for line in chapter["dialogue"]:
        spoken = synthesize(
            session, voices[line["speaker"]], line.get("performance") or line["text"]
        )
        clip = frames_only(tighten(spoken, longest=0.5, gap=0.35))
        cues.append(round(at, 3))
        at += mp3_seconds(clip)
        joined += clip
    return joined, cues


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--candidate", type=Path, help="JSON {text, style} to audition")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    guide = json.loads(CONTENT.read_text())
    voice = guide["narration_voice"]
    if args.activate:
        return activate(guide)
    session = session_for(os.environ["GOOGLE_CLOUD_PROJECT"])
    response = session.get(BASE + "/voices", params={"languageCode": "en-US"}, timeout=30)
    if not response.ok:
        raise SystemExit(f"TTS access failed ({response.status_code}): {response.text[:1400]}")
    print(f"TTS access verified ({len(response.json().get('voices', []))} en-US voices listed).")
    if args.check:
        return
    if args.sample:
        args.sample.mkdir(parents=True, exist_ok=True)
        candidate = json.loads(args.candidate.read_text())
        for name, model in SAMPLES:
            path = args.sample / f"hello-{name.lower()}-{model}.mp3"
            trial = {**voice, "voice": name, "model": model, "style": candidate["style"]}
            audio = synthesize(session, trial, candidate["text"])
            path.write_bytes(audio)
            print(f"Sample: {path} ({mp3_seconds(audio):.2f}s)")
        return
    version = tour_version(guide)
    folder = AUDIO / version
    folder.mkdir(parents=True, exist_ok=True)
    chapters = {}
    try:  # clips already verified for an unchanged chapter are reused, never re-recorded
        active = json.loads((AUDIO / "manifest.json").read_text()).get("chapters", {})
    except (OSError, ValueError):
        active = {}
    for chapter in guide["chapters"]:
        path = folder / f"{chapter['id']}.mp3"
        cue_path = path.with_suffix(".cues.json")
        previous = active.get(chapter["id"], {})
        if not path.exists() and previous.get("key") == guide_key(chapter, guide):
            shutil.copy2(AUDIO / previous["file"], path)
            if previous.get("cues") is not None:
                cue_path.write_text(json.dumps(previous["cues"]))
            print(f"Reused: {chapter['id']}")
        if not path.exists():
            if "dialogue" in chapter:
                audio, cues = synthesize_dialogue(session, guide, chapter)
                cue_path.write_text(json.dumps(cues))
            else:
                audio = tighten(synthesize(session, voice, spoken_text(chapter)), longest=0.8)
            path.write_bytes(audio)
            print(f"Generated: {chapter['id']}")
        chapters[chapter["id"]] = {
            "file": f"{version}/{path.name}",
            "key": guide_key(chapter, guide),
            "seconds": round(mp3_seconds(path.read_bytes()), 3),
        }
        if "dialogue" in chapter:
            chapters[chapter["id"]]["cues"] = json.loads(cue_path.read_text())
    pending = {"version": version, "voice": voice, "chapters": chapters}
    (AUDIO / "manifest.next.json").write_text(json.dumps(pending, indent=2) + "\n")
    total = sum(c["seconds"] for c in chapters.values())
    print(f"Pending version {version}: {total:.1f}s. Review it, then run with --activate.")


def activate(guide: dict) -> None:
    pending_path = AUDIO / "manifest.next.json"
    pending = json.loads(pending_path.read_text())
    for chapter in guide["chapters"]:
        entry = pending["chapters"].get(chapter["id"])
        if not entry or entry["key"] != guide_key(chapter, guide):
            raise SystemExit(f"Pending audio does not match the current script: {chapter['id']}")
        if mp3_seconds((AUDIO / entry["file"]).read_bytes()) <= 0:
            raise SystemExit(f"Pending audio is not decodable: {entry['file']}")
    previous = AUDIO / "manifest.json"
    if previous.exists():
        shutil.copy2(previous, AUDIO / "manifest.previous.json")
    pending_path.replace(previous)  # one rename: the page sees the old tour or the new one
    print(f"Activated {pending['version']}.")
    # Clips from before versioning are kept aside, never deleted, for comparison or rollback.
    legacy = AUDIO / "legacy-chirp3-aoede"
    for stale in AUDIO.glob("*.mp3"):
        if re.fullmatch(r"[a-z]+\.mp3", stale.name):
            legacy.mkdir(exist_ok=True)
            stale.replace(legacy / stale.name)


if __name__ == "__main__":
    main()
