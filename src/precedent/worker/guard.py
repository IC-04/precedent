"""Ava's own tools and the callbacks ADK calls around every model and tool call.

This is where our policies live as code: budgets, the event log, the write gate's
decisions, failure advice, and keeping the model's view of pages small.
It does not import ADK; it only receives ADK's objects.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from precedent.contracts import DecisionRecord, PlanStep
from precedent.worker.compact import inline_snapshot, one_line, page_of
from precedent.worker.events import EventLog
from precedent.worker.failures import ADVICE, WriteGate, classify_tool_error
from precedent.worker.gateway import Exchange

KEEP_SNAPSHOTS = 3
OUTCOMES = ("pass", "fail", "blocked", "unknown")


@dataclass
class Budgets:
    steps: int = 60
    tokens: int = 600_000
    seconds: int = 1200


def stdin_human(question: str, options: list[str]) -> str:
    if not sys.stdin.isatty():
        return "No human is available right now. Finish with outcome 'blocked' and say why."
    print(f"\nAva asks: {question}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    answer = input("Answer: ").strip()
    return (
        options[int(answer) - 1] if answer.isdigit() and 0 < int(answer) <= len(options) else answer
    )


def _text(response: Any) -> tuple[str, bool]:
    """The text inside an MCP tool result, and whether it is an error."""
    if isinstance(response, dict):
        parts = response.get("content") or []
        text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return text or str(response.get("result", "")), bool(response.get("isError"))
    return str(response), False


class Guard:
    def __init__(
        self,
        log: EventLog,
        gate: WriteGate,
        lock: threading.Lock,
        mcp_dir: Path,
        budgets: Budgets | None = None,
        human: Callable[[str, list[str]], str] = stdin_human,
    ):
        self.log, self.gate, self.lock, self.mcp_dir = log, gate, lock, mcp_dir
        self.budgets, self.human = budgets or Budgets(), human
        self.exchanges: list[Exchange] = []
        self.steps = self.tokens_in = self.tokens_out = self.questions = 0
        self.started = time.monotonic()
        self.finished: dict[str, Any] | None = None
        self.stop_reason: str | None = None
        self.plan_sent = False

    # ------------------------------------------------------------------ Ava's tools
    def record_decision(
        self,
        observed: str,
        means: str,
        decided: str,
        sources: list[str],
        action: str = "",
        check: str = "",
    ) -> dict:
        """Record why you are about to change something, citing sources (record ids, document
        sections, emails). Required before every save, submit or other change."""
        record = DecisionRecord(
            observed=observed,
            means=means,
            decided=decided,
            action=action or None,
            check=check or None,
            sources=sources,
        )
        with self.lock:
            result = self.gate.on_decision(sources)
        self.log.emit("decision_record", **record.model_dump(), gate=result)
        return {"result": result}

    def update_plan(self, steps: list[str], reason: str = "") -> dict:
        """Set or change your plan. Each step is 'what you will do | what you expect to see'."""
        plan = []
        for i, step in enumerate(steps, 1):
            intent, _, expect = step.partition("|")
            plan.append(
                PlanStep(
                    id=f"s{i}", intent=intent.strip(), expect=expect.strip() or "not stated"
                ).model_dump()
            )
        kind = "plan_changed" if self.plan_sent else "plan"
        self.plan_sent = True
        self.log.emit(kind, steps=plan, reason=reason)
        return {"result": f"Plan recorded with {len(plan)} steps."}

    def ask_human(self, question: str, options: list[str]) -> dict:
        """Ask one specific question when no source governs a choice. Name the options."""
        self.questions += 1
        self.log.emit("question", text=question, options=options)
        answer = self.human(question, options)
        self.log.emit("answer", text=answer, by="human")
        return {"answer": answer}

    def finish(self, outcome: str, summary: str) -> dict:
        """End the task. outcome is pass, fail, blocked or unknown; summary says what was done,
        what is pending and why. Your claim is checked independently afterwards."""
        claimed = outcome if outcome in OUTCOMES else "unknown"
        self.finished = {"claimed": claimed, "summary": summary}
        self.log.emit("note", kind="finish_claimed", outcome=claimed, summary=summary)
        return {"result": "Finished. Stop now."}

    def tools(self) -> list[Callable[..., dict]]:
        return [self.record_decision, self.update_plan, self.ask_human, self.finish]

    # ------------------------------------------------------------------ callbacks
    def on_exchange(self, exchange: Exchange) -> None:
        with self.lock:
            self.exchanges.append(exchange)

    def _over_budget(self) -> str | None:
        elapsed = time.monotonic() - self.started
        if self.steps > self.budgets.steps:
            return f"step budget of {self.budgets.steps} used"
        if self.tokens_in + self.tokens_out > self.budgets.tokens:
            return f"token budget of {self.budgets.tokens} used"
        if elapsed > self.budgets.seconds:
            return f"time budget of {self.budgets.seconds} s used"
        return None

    def before_tool(self, tool, args: dict, tool_context) -> dict | None:
        if tool.name == "finish":
            return None
        self.steps += 1
        self.stop_reason = self.stop_reason or self._over_budget()
        if self.stop_reason:
            return {"error": f"Stopped: {self.stop_reason}. Call finish now with outcome unknown."}
        if tool.name.startswith("browser_"):
            self.log.emit("action", tool=tool.name, args=args, step_id=f"t{self.steps}")
        return None

    def after_tool(self, tool, args: dict, tool_context, tool_response) -> dict | None:
        if not tool.name.startswith("browser_"):
            return None
        text, is_error = _text(tool_response)
        notes = []
        if is_error:
            kind = classify_tool_error(text)
            self.log.emit("failure", kind=kind.value, detail=text[:300], response=ADVICE[kind])
            notes.append(ADVICE[kind])
        notes += self._drain_exchanges()
        text = inline_snapshot(text, self.mcp_dir)
        url, title = page_of(text)
        self.log.emit(
            "observation",
            url=url,
            title=title,
            summary=(notes[0] if notes else title),
            screenshot=None,
        )
        if notes:
            text += "\n### Notes from Ava's safety checks\n" + "\n".join(f"- {n}" for n in notes)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def _drain_exchanges(self) -> list[str]:
        with self.lock:
            exchanges, self.exchanges = self.exchanges, []
        notes = []
        for ex in exchanges:
            if ex.refused:
                self.log.emit(
                    "note", kind="write_refused", method=ex.method, path=ex.path, reason=ex.refused
                )
                notes.append(f"Your save was refused before it reached the app: {ex.refused}")
            elif ex.kind is not None:
                detail = f"{ex.method} {ex.path} -> {ex.status or 'no response'}"
                self.log.emit(
                    "failure", kind=ex.kind.value, detail=detail, response=ADVICE[ex.kind]
                )
                notes.append(ADVICE[ex.kind])
        if self.gate.fatal:
            self.stop_reason = "two saves had unknown results"
        return notes

    def before_model(self, callback_context, llm_request) -> None:
        """Keep the last few page snapshots in full; older ones become one line."""
        seen = 0
        for content in reversed(llm_request.contents or []):
            for part in content.parts or []:
                fr = getattr(part, "function_response", None)
                if fr is None or not (fr.name or "").startswith("browser_"):
                    continue
                seen += 1
                if seen > KEEP_SNAPSHOTS:
                    text, _ = _text(fr.response or {})
                    fr.response = {"content": [{"type": "text", "text": one_line(text)}]}
        return None

    def after_model(self, callback_context, llm_response) -> None:
        usage = llm_response.usage_metadata
        if usage:
            self.tokens_in += usage.prompt_token_count or 0
            self.tokens_out += usage.candidates_token_count or 0
        return None

    def seconds(self) -> float:
        return round(time.monotonic() - self.started, 1)
