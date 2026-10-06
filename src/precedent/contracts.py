"""Shared contracts between workstreams.

Change these deliberately: every workstream builds against them.
If you change a model here, update docs/03_contracts.md in the same commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Goal contract (written before the first action)
# --------------------------------------------------------------------------
class Condition(BaseModel):
    id: str  # "c1", "n1" ...
    text: str  # human-readable condition
    kind: Literal["must_be_true", "must_not_happen"]
    check_hint: str | None = None  # how the verifier could check it


class GoalContract(BaseModel):
    request: str
    outcome: str  # one-sentence intended end state
    conditions: list[Condition]
    assumptions: list[str] = []
    out_of_scope: list[str] = []  # e.g. "approving the bill"


# --------------------------------------------------------------------------
# Company context
# --------------------------------------------------------------------------
class Authority(StrEnum):
    policy = "policy"
    instruction = "authoritative_instruction"
    current_state = "current_state"
    precedent = "precedent"
    inference = "inference"
    external = "external_input"


class SourceRef(BaseModel):
    app: Literal["mail", "books", "drive", "chat"]
    ref: str  # e.g. "mail:m-0412", "drive:AP-Policy-2025.pdf#4"
    quote: str | None = None
    authority: Authority
    dated: str | None = None  # ISO date the source took effect


class PrecedentStatus(StrEnum):
    usable = "usable"
    conflict = "conflict"  # authority and practice disagree; follow authority, report
    unresolved = "unresolved"  # no governing source, practice split: ask


class Precedent(BaseModel):
    id: str
    task_family: str  # "enter_invoice", "vendor_setup", ...
    rule: str  # "Design spend > ₹50,000 is approved by Ana Pereira"
    governing: SourceRef | None
    supporting: list[SourceRef] = []
    support: str | None = None  # "8 of 9 bills since 14 Jul"
    exceptions: list[str] = []
    flags: list[str] = []  # "SOP §3.2 stale"
    status: PrecedentStatus


# --------------------------------------------------------------------------
# Plan, decisions, failures
# --------------------------------------------------------------------------
class PlanStep(BaseModel):
    id: str
    intent: str
    expect: str  # what the worker expects to observe afterwards
    status: Literal["todo", "doing", "done", "skipped", "added"] = "todo"


class DecisionRecord(BaseModel):
    observed: str
    means: str
    decided: str
    action: str | None = None
    check: str | None = None
    sources: list[str] = []  # SourceRef.ref values


class FailureKind(StrEnum):
    tool = "tool"  # timeout, transient error -> bounded retry
    interface = "interface"  # element moved / relabelled -> re-observe
    uncertain_write = "uncertain_write"  # no ack -> search by business key first
    missing_authority = "missing_authority"  # -> ask one question
    business_contradiction = "business_contradiction"  # -> stop, BLOCKED


# --------------------------------------------------------------------------
# Verification and receipt
# --------------------------------------------------------------------------
class CheckResult(BaseModel):
    condition_id: str
    text: str
    result: Literal["pass", "fail", "unknown"]
    evidence: str | None = None


Outcome = Literal["pass", "fail", "blocked", "unknown"]


class Receipt(BaseModel):
    run_id: str
    request: str
    outcome: Outcome
    summary: str  # lead line: outcome + what is pending
    pending: list[str] = []
    questions_asked: int = 0
    decisions: list[DecisionRecord] = []
    left_unchanged: list[str] = []
    checks: list[CheckResult] = []
    sources: list[str] = []
    cost: dict[str, Any] = {}  # tokens, usd, seconds


# --------------------------------------------------------------------------
# Events: runs/<run_id>/events.jsonl, one JSON object per line
# --------------------------------------------------------------------------
EventType = Literal[
    "run_started",
    "goal_contract",
    "precedent",
    "plan",
    "plan_changed",
    "step_started",
    "action",
    "observation",
    "decision_record",
    "failure",
    "question",
    "answer",
    "check",
    "receipt",
    "run_finished",
    "note",
]


class Event(BaseModel):
    run_id: str
    seq: int
    ts: datetime = Field(default_factory=now)
    type: EventType
    task_id: str | None = None
    data: dict[str, Any] = {}


# --------------------------------------------------------------------------
# Hidden truth: worlds/<seed>/hidden.json (grader only)
# --------------------------------------------------------------------------
class ExpectedTask(BaseModel):
    task_id: str
    request: str
    expected: dict[str, Any]  # e.g. {"bill_count": 1, "account": "1400", "approver": "E-ana"}
    must_not: dict[str, Any] = {}  # e.g. {"vendor_bank_changed": ["V-112"]}
    traps: list[str] = []  # planted problems this task exercises


class HiddenTruth(BaseModel):
    seed: int
    template: str
    tasks: list[ExpectedTask]
    rules: list[dict[str, Any]] = []  # the true operating rules of this company
