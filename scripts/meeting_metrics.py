"""Meeting telemetry from retained events, including separate Tribunal hearings."""

import argparse
import json
from pathlib import Path

from learning_metrics import instant, summarize, union_seconds


def measure(run):
    result = summarize(run)
    directory = Path("runs") / run
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    goal_start = next((e for e in events if e["data"].get("phase") == "goal"), None)
    goal_end = next((e for e in events if e["type"] == "goal_contract"), None)
    context_start = next(
        (e for e in events if e["data"].get("text") == "Reading the company scheduling context"),
        None,
    )
    context_end = next(
        (
            e
            for e in events
            if e["type"] == "precedent" and e["data"].get("task_family") == "meeting"
        ),
        None,
    )
    result["goal_preparation_seconds"] = (
        round(instant(goal_end) - instant(goal_start), 3) if goal_start and goal_end else None
    )
    result["public_scheduling_context_seconds"] = (
        round(instant(context_end) - instant(context_start), 3)
        if context_start and context_end
        else None
    )
    verify_start, intervals = None, []
    for event in events:
        if event["data"].get("kind") == "verify":
            verify_start = event
        if event["data"].get("kind") == "meeting_artifacts" and verify_start:
            intervals.append((instant(verify_start), instant(event)))
            verify_start = None
    result["worker_verification_seconds"] = union_seconds(intervals)
    result["tribunal_hearings"] = []
    for folder in ["tribunal-before-remand", "tribunal"]:
        path = directory / folder / "verdict.json"
        if path.exists():
            verdict = json.loads(path.read_text())
            result["tribunal_hearings"].append(
                {"folder": folder, "outcome": verdict["overall"], "seconds": verdict["seconds"]}
            )
    result["tribunal_seconds"] = sum(h["seconds"] for h in result["tribunal_hearings"])
    result["remands"] = sum(e["data"].get("kind") == "remand" for e in events)
    result["final_supported_conditions"] = len(result["verified_claims"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+")
    parser.add_argument(
        "--output", type=Path, default=Path("output/meeting-milestone/metrics.json")
    )
    args = parser.parse_args()
    output = {
        "method": "Recorded event timestamps and runtime counters. Preparation/gathering may "
        "overlap. Model wait is an estimate; browser intervals include captures. Verification "
        "intervals are unioned across rechecks. Tribunal seconds come from retained verdicts; "
        "Ava token/turn counters exclude juror usage. Check event counts may include a recheck; "
        "final supported conditions count distinct claim keys. No cost or success rate inferred.",
        "runs": [measure(run) for run in args.runs],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
