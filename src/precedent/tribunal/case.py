"""A finished run, read back as a case for the Tribunal."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from precedent.contracts import GoalContract
from precedent.worker.verify import CheckPlan

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Write:
    seq: int
    method: str
    path: str
    status: int | None


@dataclass
class Decision:
    seq: int
    decided: str
    sources: list[str]


@dataclass
class Case:
    run_id: str
    directory: Path
    request: str
    goal: GoalContract
    plan: CheckPlan
    company: dict
    apps_url: str | None
    writes: list[Write] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    claims: dict[str, dict] = field(default_factory=dict)  # Ava's goal_progress per condition
    finish: dict | None = None  # Ava's finish claim, with its sequence number
    grade: dict | None = None  # the independent grader's result, if one was produced
    events: list[dict] = field(default_factory=list)  # the run's own log


class CaseError(ValueError):
    """The run cannot be heard: it is unfinished, foreign or missing its contract."""


def load_case(directory: Path, require_finished: bool = True) -> Case:
    directory = Path(directory)
    path = directory / "events.jsonl"
    if not path.is_file():
        raise CaseError("the run has no event log")
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a partial last line while a run is still writing
    run_id = directory.name
    events = [e for e in events if e.get("run_id") == run_id]
    started = next((e["data"] for e in events if e["type"] == "run_started"), None)
    goal = next((e["data"] for e in events if e["type"] == "goal_contract"), None)
    if started is None or goal is None:
        raise CaseError("the run has no start or no goal contract")
    if require_finished and not any(e["type"] == "run_finished" for e in events):
        raise CaseError("the run has not finished")
    plan_path = directory / "verification-plan.json"
    plan = (
        CheckPlan.model_validate_json(plan_path.read_text())
        if plan_path.is_file()
        else CheckPlan(checks=[])
    )
    company = next((e["data"]["company"] for e in events if e["data"].get("kind") == "company"), {})
    launch = directory / "launch.json"
    apps_url = json.loads(launch.read_text()).get("apps_url") if launch.is_file() else None
    case = Case(
        run_id=run_id,
        directory=directory,
        request=started.get("request", ""),
        goal=GoalContract.model_validate(goal),
        plan=plan,
        company=company,
        apps_url=apps_url,
        events=events,
    )
    for e in events:
        data, seq = e["data"], e["seq"]
        if e["type"] == "decision_record":
            case.decisions.append(
                Decision(seq, str(data.get("decided", "")), list(data.get("sources") or []))
            )
        elif data.get("kind") == "app_effect" and str(data.get("method")) in WRITE_METHODS:
            case.writes.append(
                Write(seq, data["method"], str(data.get("path", "")), data.get("status"))
            )
        elif data.get("kind") == "goal_progress" and data.get("condition_id"):
            case.claims[data["condition_id"]] = {**data, "seq": seq}
        elif data.get("kind") == "finish_claimed":
            case.finish = {**data, "seq": seq}
    grade = directory / "grade.json"
    if grade.is_file():
        try:
            case.grade = json.loads(grade.read_text())
        except json.JSONDecodeError:
            case.grade = None
    return case
