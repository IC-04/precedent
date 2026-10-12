"""Summarize recorded learning-demo runs without inventing missing telemetry."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def instant(event):
    return datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp()


def union_seconds(intervals):
    total, end = 0.0, 0.0
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return round(total, 3)


def summarize(run_id):
    directory = Path("runs") / run_id
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    end = next((e["data"] for e in events if e["type"] == "run_finished"), {})
    started = instant(events[0])
    goals = [e for e in events if e["type"] == "goal_contract"]
    actions = {e["data"]["step_id"]: e for e in events if e["type"] == "action"}
    action_times = []
    for e in events:
        if e["type"] == "observation" and e["data"].get("action_step_id") in actions:
            action_times.append((instant(actions[e["data"]["action_step_id"]]), instant(e)))
    execution = next(
        (e for e in events if e["data"].get("kind") == "model_wait" and not e["data"].get("phase")),
        None,
    )
    context_start = next((e for e in events if e["data"].get("kind") == "context_gathered"), None)
    context_end = next((e for e in events if e["data"].get("kind") == "context"), None)
    verify_start = next((e for e in events if e["data"].get("kind") == "verify"), None)
    checks = [e for e in events if e["type"] == "check"]
    waits = []
    for index, event in enumerate(events[:-1]):
        if event["data"].get("kind") == "model_wait" and not event["data"].get("phase"):
            waits.append((instant(event), instant(events[index + 1])))
    for first, last in [
        (context_start, context_end),
        (verify_start, checks[0] if checks else None),
    ]:
        if first and last:
            waits.append((instant(first), instant(last)))
    goal_wait = next((e for e in events if e["data"].get("phase") == "goal"), None)
    if goal_wait and goals:
        waits.append((instant(goal_wait), instant(goals[0])))
    retrieval = [e["data"] for e in events if e["data"].get("kind") == "memory_recalled"]
    grade_path = directory / "grade.json"
    grade = json.loads(grade_path.read_text()) if grade_path.exists() else None
    return {
        "run_id": run_id,
        "outcome": end.get("outcome", "interrupted"),
        "total_seconds": end.get("seconds"),
        "preparation_seconds": round(instant(execution) - started, 3) if execution else None,
        "context_candidate_seconds": next(
            (e["data"].get("seconds") for e in events if e["data"].get("kind") == "context_timing"),
            None,
        ),
        "context_candidates_reused": any(e["data"].get("kind") == "context_reused" for e in events),
        "retrieval_seconds": sum(e.get("seconds", 0) for e in retrieval) if retrieval else None,
        "retrieved_entries": sum(len(e.get("ids", [])) for e in retrieval),
        "model_wait_estimate_seconds": union_seconds(waits),
        "browser_tool_and_capture_seconds": union_seconds(action_times),
        "visual_pacing_seconds": end.get("viewing_pace_seconds"),
        "tokens_in": end.get("tokens_in"),
        "tokens_out": end.get("tokens_out"),
        "model_responses": end.get("model_responses"),
        "browser_actions": len(actions),
        "steps": end.get("steps"),
        "questions": end.get("questions"),
        "skill_loaded": any(e["data"].get("kind") == "skill_loaded" for e in events),
        "checks": dict(Counter(e["data"]["result"] for e in checks)),
        "verified_claims": sorted(
            {
                c
                for e in checks
                if e["data"]["result"] == "pass"
                for c in e["data"].get("claims", [])
            }
        ),
        "independent_grade": {"outcome": grade["overall"], "checks": len(grade["items"])}
        if grade
        else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+")
    parser.add_argument(
        "--output", type=Path, default=Path("output/learning-milestone/metrics.json")
    )
    args = parser.parse_args()
    result = {
        "method": "Recorded event timestamps and runtime counters. Model wait is an estimate "
        "including response handling and verification; context candidate time excludes fresh "
        "page gathering and history validation. Preparation ends at the first execution-model "
        "request. Browser time includes evidence "
        "capture. Concurrent preparation intervals are unioned, not added twice. "
        "Missing counters are null. No dollar cost or general success rate inferred.",
        "runs": [summarize(run) for run in args.runs],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
