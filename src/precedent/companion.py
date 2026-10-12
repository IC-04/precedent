"""Ava's companion: one drawing, one pose vocabulary, one truthful state mapping.

The console, the company apps and the worker browser's overlay all draw the same
`apps/static/ava/ava.svg` with `ava.css`. A pose says what recorded events show Ava
doing. It never encodes elapsed time or invented progress, and personality lines are
fixed presentation copy, never model output.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from markupsafe import Markup

ART = Path(__file__).parent / "apps" / "static" / "ava"
POSES = (
    "idle",  # present, nothing running
    "greet",  # opened by a person
    "listen",  # the task panel is open, waiting for words
    "speak",  # guide narration is playing
    "read",  # reading pages or company context
    "think",  # choosing the next action / waiting for a model response
    "work",  # a browser action is executing
    "check",  # fresh verification of the saved record
    "ask",  # waiting for a human answer
    "deliver",  # a finished run whose fresh checks all passed
    "away",  # interrupted, stopped or unavailable
)
# Short, warm and generic. Shown only when nothing operational needs saying.
AMBIENT_LINES = (
    "A little less busywork.",
    "One tab at a time.",
    "Give me an outcome; I’ll find the steps.",
    "I bring back the evidence.",
)


@cache
def svg() -> str:
    return (ART / "ava.svg").read_text()


def art(pose: str = "idle", *, label: str | None = None, cls: str = "") -> Markup:
    """Server-rendered Ava, so pages show her without JavaScript."""
    pose = pose if pose in POSES else "idle"
    role = f' role="img" aria-label="{Markup.escape(label)}"' if label else ' aria-hidden="true"'
    return Markup(
        f'<span class="ava ava-motion {Markup.escape(cls)}" data-pose="{pose}"{role}>{svg()}</span>'
    )


SURFACES = {"guide", "tasks", "run", "overview", "mail", "books", "drive", "chat", "calendar"}
KINDS = {"message", "bill", "file", "channel", "vendor", "draft", "event"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.#-]{0,63}$")


def clean_context(raw: Any) -> dict[str, str] | None:
    """Bounded, visible record identity only. Anything else is dropped, never trusted."""
    if not isinstance(raw, dict):
        return None
    surface = str(raw.get("surface", ""))
    if surface not in SURFACES:
        return None
    out = {"surface": surface}
    if raw.get("kind") in KINDS and SAFE_ID.fullmatch(str(raw.get("id", ""))):
        out["kind"], out["id"] = str(raw["kind"]), str(raw["id"])
    if raw.get("attachment") is True:
        out["attachment"] = "1"
    for key, limit in (("label", 140), ("vendor", 80), ("invoice", 40)):
        value = " ".join(str(raw.get(key) or "").split())[:limit]
        if value:
            out[key] = value
    return out


def script_json(value: Any) -> Markup:
    """JSON safe inside a <script> element (which is never entity-decoded)."""
    text = json.dumps(value, ensure_ascii=False)
    for raw, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        text = text.replace(raw, escaped)
    return Markup(text)


def dock(
    surface: str,
    console_url: str,
    *,
    status_url: str,
    handoff: str,
    context: dict | None = None,
    mount: str = "dock",
) -> Markup:
    """Ava's companion for a human-facing page. Without JavaScript it is a plain link
    to the task composer. Never rendered for the worker's own requests."""
    config = {
        "surface": surface,
        "console": console_url.rstrip("/"),
        "status": status_url,
        "handoff": handoff,
        "mount": mount,
        "context": clean_context({**(context or {}), "surface": surface}),
        "lines": AMBIENT_LINES,
    }
    data = script_json(config)
    if mount != "dock":
        return Markup(f'<script type="application/json" id="ava-config">{data}</script>')
    return Markup(
        f'<script type="application/json" id="ava-config">{data}</script>'
        f'<div class="ava-dock" data-ava-dock><a class="ava-dock-button" '
        f'href="{Markup.escape(config["console"])}/#request" aria-label="Ava · start a task">'
        f"{art('idle')}</a></div>"
    )


def pose_for(state: dict[str, Any]) -> dict[str, str]:
    """Pose and a short status line from a reconstructed run state (console/state.py).

    Only recorded events decide. Delivery is shown only for a fresh, fully verified
    pass; an unknown or failed result is never celebrated.
    """
    finished = state.get("finished")
    live = str(state.get("mode", "")).startswith("Live")
    if finished:
        if state.get("notice") or finished.get("error"):
            return {"pose": "away", "line": "Stopped · see what happened"}
        if state.get("display_outcome") == "pass":
            return {"pose": "deliver", "line": "Verified result · ready to inspect"}
        if state.get("display_outcome") == "fail":
            return {"pose": "idle", "line": "Work returned · a check failed"}
        if state.get("display_outcome") == "blocked":
            return {"pose": "idle", "line": "Could not finish · reasons recorded"}
        return {"pose": "idle", "line": "Work returned · some checks remain open"}
    if not live:
        return {"pose": "away", "line": "This session stopped without a result"}
    question = state.get("question")
    if question:
        if state.get("answer_submitted"):
            return {"pose": "listen", "line": "Reading your answer"}
        return {"pose": "ask", "line": "I need your input to continue"}
    if state.get("phase") == "verify":
        return {"pose": "check", "line": "Checking the saved record"}
    if state.get("wait"):
        return {"pose": "think", "line": "Waiting for the model"}
    if state.get("phase") != "execute":
        return {"pose": "read", "line": "Reading the company context"}
    history = state.get("history") or []
    action = next((e for e in reversed(history) if e.get("type") == "action"), None)
    decision = next((e for e in reversed(history) if e.get("type") == "decision_record"), None)
    observed = (state.get("observation") or {}).get("seq", -1)
    # An action without a later observation is still executing in the browser.
    if action and action.get("seq", -1) > observed:
        caption = (action.get("data") or {}).get("caption")
        if (action.get("data") or {}).get("tool") == "browser_snapshot":
            return {"pose": "read", "line": caption or "Reading the page"}
        return {"pose": "work", "line": caption or "Working in the browser"}
    if decision and decision.get("seq", -1) > max(observed, (action or {}).get("seq", -1)):
        return {"pose": "think", "line": "Recording a decision and its sources"}
    return {"pose": "think", "line": "Choosing the next step"}
