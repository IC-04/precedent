"""Pure event reconstruction. Intentions, app effects, verification and grading stay distinct."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from precedent.contracts import Event

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


def safe_child(root: Path, name: str) -> Path:
    if not SAFE_ID.fullmatch(name):
        raise ValueError("Invalid run identifier")
    if (root / name).is_symlink():
        raise ValueError("Symlinked run directory")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Path outside runs")
    return path


def shot_path(directory: Path, name: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", name):
        return None
    base = (directory / "shots").resolve()
    path = base / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
        return None
    if not base.is_relative_to(directory.resolve()):
        return None
    return path


def reconstruct(events: list[Event], active: bool = False) -> dict[str, Any]:
    state: dict[str, Any] = {
        "request": "Request unavailable",
        "status": "Starting" if active else "Interrupted",
        "mode": "Live updates" if active else "Replay",
        "goal": None,
        "plan": [],
        "precedents": [],
        "decisions": [],
        "checks": [],
        "history": [],
        "question": None,
        "observation": None,
        "receipt": None,
        "finished": None,
        "effects": [],
        "captures": [],
        "activity": "Preparing the worker" if active else "No activity recorded",
        "notes": [],
        "last_seq": 0,
        "seed": None,
        "worker": "precedent",
        "wait": None,
        "screen": None,
        "thinking": None,
    }
    questions: dict[str, dict] = {}
    for event in events:
        d = event.data
        if event.type in (
            "goal_contract",
            "plan",
            "plan_changed",
            "step_started",
            "action",
            "observation",
            "question",
            "run_finished",
        ):
            state["wait"] = None
        state["last_seq"] = event.seq
        state["last_activity_at"] = event.ts.isoformat()
        if event.type == "run_started":
            state.update({k: d[k] for k in ("request", "seed", "worker") if k in d})
            state["started_at"] = event.ts.isoformat()
            state["validation"] = d.get("validation")
        elif event.type == "goal_contract":
            state["goal"] = d
            state["activity"] = "Goal contract recorded"
        elif event.type in ("plan", "plan_changed"):
            state["plan"] = d.get("steps", [])
            state["activity"] = "Plan recorded" if event.type == "plan" else "Plan updated"
        elif event.type == "step_started":
            for step in state["plan"]:
                if step["id"] == d.get("step_id"):
                    step["status"] = "doing"
            state["activity"] = d.get("intent", "Plan step started")
        elif event.type == "action" and d.get("caption"):
            state["activity"] = d["caption"]
        elif event.type == "action":
            tool = d.get("tool", "browser action")
            state["activity"] = {
                "browser_navigate": "Opening " + str(d.get("args", {}).get("url", "a page")),
                "browser_navigate_back": "Returning to the previous page",
                "browser_type": "Entering information in a form",
                "browser_select_option": "Choosing a form value",
                "browser_click": "Selecting a browser control",
                "browser_wait_for": "Waiting for the page",
                "browser_snapshot": "Reading the browser",
            }.get(tool, tool.replace("_", " "))
        elif event.type == "precedent":
            state["precedents"].append(d)
        elif event.type == "decision_record":
            state["decisions"].append(d)
            state["activity"] = d.get("decided", "Decision recorded")
        elif event.type == "observation":
            if d.get("screenshot"):
                state["capture"] = {
                    **d,
                    "observation_seq": event.seq,
                    "captured_at": d.get("captured_at", event.ts.isoformat()),
                }
                state["captures"].append(state["capture"])
            state["observation"] = {**d, "ts": event.ts.isoformat(), "seq": event.seq}
            state["activity"] = d.get("summary") or d.get("title") or "Browser observed"
        elif event.type == "question":
            key = d.get("question_id", f"q{event.seq}")
            questions[key] = {**d, "question_id": key, "ts": event.ts.isoformat()}
            state["activity"] = "Waiting for an answer"
        elif event.type == "answer":
            key = d.get("question_id")
            if key:
                questions.pop(key, None)
            elif questions:
                questions.pop(next(reversed(questions)), None)
            state["activity"] = (
                "Answer received" if d.get("by") == "human" else "Question unavailable"
            )
        elif event.type == "check":
            state["checks"] = [
                c for c in state["checks"] if c.get("condition_id") != d.get("condition_id")
            ]
            state["checks"].append(d)
            state["activity"] = "Fresh verification: " + d.get("text", "check recorded")
        elif event.type == "receipt":
            state["receipt"] = d
            checked = {c.get("condition_id") for c in state["checks"]}
            state["checks"].extend(
                c
                for c in d.get("checks", [])
                if c.get("result") == "unknown" and c.get("condition_id") not in checked
            )
        elif event.type == "run_finished":
            state["screen"] = None  # the live stream ends with the run; captures remain
            state["finished"] = d
            error = d.get("error") or ""
            capacity = any(term in error.lower() for term in ("429", "quota", "capacity", "503"))
            state["status"] = (
                "Interrupted · model capacity"
                if capacity
                else "Stopped · model timeout"
                if "Goal preparation timed out" in error
                else "Failed · outcome unknown"
                if error
                else "Finished · " + d.get("outcome", "unknown")
            )
        elif event.type == "note":
            state["notes"].append(d)
            if d.get("kind") == "model_wait":
                state["wait"] = {
                    "started_at": event.ts.isoformat(),
                    **(state["wait"] or {}),
                    **d,
                }
            if d.get("kind") == "company":
                state["company"] = d.get("company")
            if d.get("kind") == "screen":
                state["screen"] = d.get("url")
            if d.get("kind") == "thinking":
                state["thinking"] = {"level": d.get("level"), "reason": d.get("reason")}
            if d.get("kind") == "app_effect":
                state["effects"].append(d)
            if d.get("kind") in ("phase", "model_wait", "stopped", "error"):
                state["activity"] = d.get("text") or d.get("reason") or "Waiting for model"
        if event.type in ("action", "failure", "decision_record", "note", "check", "answer"):
            state["history"].append(
                {"seq": event.seq, "type": event.type, "ts": event.ts.isoformat(), "data": d}
            )
    state["question"] = next(reversed(questions.values()), None) if questions else None
    if active and not state["finished"]:
        state["status"] = (
            "Waiting for answer"
            if state["question"]
            else "Waiting for model"
            if state["wait"]
            else "Working"
        )
    state["notice"] = None
    if state["finished"] and state["finished"].get("error"):
        capacity = "model capacity" in state["status"]
        timeout = "model timeout" in state["status"]
        no_actions = not any(e["type"] == "action" for e in state["history"])
        state["notice"] = {
            "title": "Model unavailable"
            if capacity
            else "Model response timed out"
            if timeout
            else "Run interrupted",
            "text": (
                "The configured models could not answer because of capacity or quota limits. "
                if capacity
                else "The model did not return a goal within the preparation time limit. "
                if timeout
                else "The run stopped because of an execution error. "
            )
            + ("No browser work began. " if no_actions else "Review the recorded work below. ")
            + (
                "You can submit the task again when model service is available."
                if capacity or timeout
                else "The activity log contains the error details."
            ),
        }
    state["can_answer"] = bool(active and state["question"] and not state["finished"])
    if state.get("validation"):
        state["mode"] += " · Scripted validation"
    # A run claim cannot mark any goal condition verified.
    checks = {c.get("condition_id"): c for c in state["checks"]}
    progress = {
        n.get("condition_id"): n for n in state["notes"] if n.get("kind") == "goal_progress"
    }
    state["conditions"] = []
    for condition in (state["goal"] or {}).get("conditions", []):
        check = checks.get(condition["id"])
        reported = progress.get(condition["id"], {})
        state["conditions"].append(
            {
                **condition,
                "state": (
                    "Verified"
                    if check and check.get("result") == "pass"
                    else "Failed"
                    if check and check.get("result") == "fail"
                    else "Unknown"
                    if check
                    else {"inferred": "Inferred", "written": "Written"}.get(
                        reported.get("status"), "Pending"
                    )
                ),
                "evidence": (check or reported).get("evidence"),
            }
        )
    verified = bool(state["conditions"]) and all(
        c["state"] == "Verified" for c in state["conditions"]
    )
    reported = (state["receipt"] or state["finished"] or {}).get("outcome", "unknown")
    state["display_outcome"] = "unknown" if reported == "pass" and not verified else reported
    if state["finished"] and state["finished"].get("outcome") == "pass" and not verified:
        state["status"] = "Finished · unverified claim"
    return state
