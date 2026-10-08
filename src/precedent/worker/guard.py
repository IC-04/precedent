"""Ava's own tools and the callbacks ADK calls around every model and tool call.

This is where our policies live as code: budgets, the event log, the write gate's
decisions, failure advice, and keeping the model's view of pages small.
It does not import ADK; it only receives ADK's objects.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from precedent.contracts import DecisionRecord, PlanStep
from precedent.worker.compact import OLD, inline_snapshot, one_line, page_of
from precedent.worker.events import EventLog
from precedent.worker.failures import ADVICE, WriteGate, classify_tool_error
from precedent.worker.gateway import Exchange

KEEP_SNAPSHOTS = 2
REPEAT_VISITS = 3  # opening the same page this many times earns a nudge
READS_WITHOUT_PROGRESS = 12  # browser steps with no decision or save earn a nudge
OLD_PREFIX = OLD.split("{", 1)[0]
OUTCOMES = ("pass", "fail", "blocked", "unknown")


@dataclass
class Budgets:
    steps: int = 60
    tokens: int = 600_000
    seconds: int = 1200


def stdin_human(question: str, options: list[str]) -> str | dict:
    if not sys.stdin.isatty():
        return {
            "text": "No human is available right now. Finish as blocked and say why.",
            "by": "system",
        }
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
        self.plan: list[dict] = []
        self.condition_ids: set[str] = set()
        self.last_url: str | None = None
        self.last_title: str | None = None
        self.last_snapshot = ""
        self.visits: Counter[str] = Counter()
        self.facts: list[str] = []
        self.since_progress = 0
        self.attention: str | None = None  # why the next turn deserves more thought
        self.last_tool: str | None = None
        self.thinking_note: str | None = None

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
        self.since_progress = 0
        with self.lock:
            result = self.gate.on_decision(sources)
        self.log.emit("decision_record", **record.model_dump(), gate=result)
        return {"result": result}

    def update_plan(self, steps: list[str], reason: str = "") -> dict:
        """Set or change your plan. Each step is 'what you will do | what you expect to see'."""
        if not steps or any(len(s.partition("|")[0].split()) < 3 for s in steps):
            return {"error": "Each step must say what you will do in at least a few words."}
        plan = []
        for i, step in enumerate(steps, 1):
            intent, _, expect = step.partition("|")
            plan.append(
                PlanStep(
                    id=f"s{i}", intent=intent.strip(), expect=expect.strip() or "not stated"
                ).model_dump()
            )
        self.plan = plan
        kind = "plan_changed" if self.plan_sent else "plan"
        self.plan_sent = True
        self.log.emit(kind, steps=plan, reason=reason)
        return {"result": f"Plan recorded with {len(plan)} steps."}

    def report_plan_step(self, step_id: str, status: str, evidence: str) -> dict:
        """Update a real plan step: doing, done or skipped. Cite the observed evidence.
        A done plan step is self-reported progress, not independent goal verification."""
        step = next((s for s in self.plan if s["id"] == step_id), None)
        if not step or status not in ("doing", "done", "skipped") or not evidence.strip():
            return {
                "error": "Choose an existing plan step, a supported status and observed evidence."
            }
        step["status"] = status
        self.log.emit("plan_changed", steps=self.plan, reason=evidence)
        return {"result": "Plan progress recorded; goal verification remains separate."}

    def report_goal_progress(self, condition_id: str, status: str, evidence: str) -> dict:
        """Report inferred or written progress for a goal condition; never report verified here.
        Written requires an acknowledged app write. Evidence explains the association."""
        if condition_id not in self.condition_ids:
            return {"error": "Choose an existing goal condition."}
        if status not in ("inferred", "written") or not evidence.strip():
            return {"error": "Use inferred or written and cite evidence. This tool cannot verify."}
        acknowledgement = next(
            (w for w in reversed(self.gate.writes) if w[2] and 200 <= w[2] < 400), None
        )
        if status == "written" and not acknowledgement:
            return {"error": "No application write acknowledgement has been observed."}
        self.log.emit(
            "note",
            kind="goal_progress",
            condition_id=condition_id,
            status=status,
            evidence=evidence,
            acknowledgement=acknowledgement if status == "written" else None,
        )
        return {"result": "Progress recorded. A fresh goal check is still required."}

    def remember(self, fact: str, source: str) -> dict:
        """Keep a fact you will need later (an amount, a due date, a record id, a rule) with
        where you read it. Remembered facts are shown to you every turn, so you need not
        reopen the page."""
        if not fact.strip() or not source.strip():
            return {"error": "Give the fact and where you read it."}
        entry = f"{fact.strip()} (from {source.strip()})"
        if entry not in self.facts:
            self.facts.append(entry)
            self.log.emit("note", kind="fact", fact=fact.strip(), source=source.strip())
        return {"result": f"Remembered. {len(self.facts)} facts kept."}

    async def ask_human(self, question: str, options: list[str]) -> dict:
        """Ask one specific question when no source governs a choice. Name the options."""
        self.questions += 1
        key = f"q{self.log.seq + 1}"
        self.log.emit("question", text=question, options=options, question_id=key)
        if inspect.iscoroutinefunction(self.human) or inspect.iscoroutinefunction(
            self.human.__call__
        ):
            answer = await self.human(question, options)
        else:
            answer = await asyncio.to_thread(self.human, question, options)
        data = answer if isinstance(answer, dict) else {"text": answer, "by": "human"}
        self.log.emit("answer", **data, question_id=key)
        return {"answer": data["text"]}

    def finish(self, outcome: str, summary: str) -> dict:
        """End the task. outcome is pass, fail, blocked or unknown; summary says what was done,
        what is pending and why. Your claim is checked independently afterwards."""
        claimed = outcome if outcome in OUTCOMES else "unknown"
        self.finished = {"claimed": claimed, "summary": summary}
        self.log.emit("note", kind="finish_claimed", outcome=claimed, summary=summary)
        return {"result": "Finished. Stop now."}

    def tools(self) -> list[Callable[..., dict]]:
        return [
            self.record_decision,
            self.update_plan,
            self.remember,
            self.report_plan_step,
            self.report_goal_progress,
            self.ask_human,
            self.finish,
        ]

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
        if not tool.name.startswith("browser_"):
            self.last_tool = tool.name
        if tool.name == "finish":
            return None
        self.steps += 1
        self.stop_reason = self.stop_reason or self._over_budget()
        if self.stop_reason:
            return {"error": f"Stopped: {self.stop_reason}. Call finish now with outcome unknown."}
        if tool.name.startswith("browser_"):
            normalize_targets(args)
            self.log.emit("action", tool=tool.name, args=args, step_id=f"t{self.steps}")
        return None

    def after_tool(
        self, tool, args: dict, tool_context, tool_response, capture: dict | None = None
    ) -> dict | None:
        if not tool.name.startswith("browser_"):
            return None
        if isinstance(tool_response, dict) and "error" in tool_response:
            return None  # our own refusal from before_tool: pass it to the model unchanged
        text, is_error = _text(tool_response)
        notes = []
        self.last_tool = tool.name
        if is_error:
            self.attention = self.attention or "an action failed"
            kind = classify_tool_error(text)
            self.log.emit("failure", kind=kind.value, detail=text[:300], response=ADVICE[kind])
            notes.append(ADVICE[kind])
        if is_error and "does not match any elements" in text:
            notes.append(
                "A target is the element's ref from the snapshot, written as the bare "
                "id (for example f8e73): no brackets, no 'ref=', no CSS selector."
            )
        if is_error and tool.name == "browser_select_option":
            notes.append(exact_options(self.last_snapshot, args.get("target", "")))
        notes += self._drain_exchanges()
        text = inline_snapshot(text, self.mcp_dir)
        if "```yaml" in text:
            self.last_snapshot = text
        url, title = page_of(text)
        notes += self._stall_notes(url)
        url_current = url is not None
        self.last_url = url or self.last_url
        self.last_title = title or self.last_title
        self.log.emit(
            "observation",
            url=self.last_url,
            url_current=url_current,
            title=self.last_title,
            summary=(notes[0] if notes else title),
            screenshot=(capture or {}).get("screenshot"),
            captured_at=(capture or {}).get("captured_at"),
            action_step_id=f"t{self.steps}",
        )
        if notes:
            text += "\n### Notes from Ava's safety checks\n" + "\n".join(f"- {n}" for n in notes)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def _stall_notes(self, url: str | None) -> list[str]:
        """Code-side nudges when the worker reads in circles; they never block anything."""
        notes = []
        self.since_progress += 1
        if url:
            self.visits[url] += 1
            if self.visits[url] == REPEAT_VISITS:
                notes.append(
                    "You have opened this page three times. Use what you read (or "
                    "remember it) and move to the next step of your plan."
                )
        if notes:
            self.attention = self.attention or "a stall nudge was given"
        if self.since_progress == READS_WITHOUT_PROGRESS:
            self.attention = self.attention or "a stall nudge was given"
            notes.append(
                f"{READS_WITHOUT_PROGRESS} browser steps without a decision or save. "
                "If you have the facts, record a decision and fill the form; if "
                "something is missing, say what and finish."
            )
        return notes

    def thinking_level(self) -> tuple[str, str]:
        """How hard the next turn should think, from what just happened (code, not the model).

        Measured on Act 1 (3 runs each): thinking more on forms and decisions bought no accuracy
        and cost 25-100 s, so extra thinking goes only to recovery. HIGH after a save whose
        result is unknown; MEDIUM to write the plan and after a refusal, a failure or a stall
        nudge; LOW otherwise, forms and decisions included."""
        attention, self.attention = self.attention, None
        if not self.plan_sent:
            return "MEDIUM", "writing the plan"
        if attention and attention.startswith("high:"):
            return "HIGH", attention.removeprefix("high:")
        if attention:
            return "MEDIUM", attention
        return "LOW", "reading, filling and saving"

    def run_state(self) -> str:
        """What the model is reminded of every turn, written by code from what happened."""
        used = (
            f"steps {self.steps}/{self.budgets.steps}, tokens "
            f"{self.tokens_in + self.tokens_out}/{self.budgets.tokens}, seconds "
            f"{int(time.monotonic() - self.started)}/{self.budgets.seconds}"
        )
        plan = "\n".join(f"- {s['id']} [{s['status']}] {s['intent']}" for s in self.plan)
        pages = "\n".join(f"- {u} (opened {n}x)" for u, n in self.visits.most_common(12))
        facts = "\n".join(f"- {f}" for f in self.facts[-20:])
        return (
            "[Run state, written by the system]\n"
            f"Budget used: {used}\n"
            f"Plan:\n{plan or '- (no plan yet: call update_plan first)'}\n"
            f"Pages already read (do not reopen unless something changed):\n"
            f"{pages or '- none'}\n"
            f"Facts you have remembered:\n{facts or '- none'}"
        )

    def on_tool_error(self, tool, args: dict, tool_context, error: Exception) -> dict:
        """A tool raised instead of answering: classify it and tell the model what to do."""
        kind = classify_tool_error(str(error))
        self.log.emit(
            "failure", kind=kind.value, detail=f"{tool.name}: {error}"[:300], response=ADVICE[kind]
        )
        notes = [ADVICE[kind], *self._drain_exchanges()]
        return {"error": f"{tool.name} failed: {str(error)[:300]}", "advice": notes}

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
                self.attention = "a save was refused"
            elif ex.method != "GET" and ex.status and 200 <= ex.status < 400:
                self.since_progress = 0
                self.log.emit(
                    "note",
                    kind="app_effect",
                    method=ex.method,
                    path=ex.path,
                    status=ex.status,
                    text="Application acknowledged a change. Fresh verification is still required.",
                )
            elif ex.kind is not None:
                detail = f"{ex.method} {ex.path} -> {ex.status or 'no response'}"
                self.log.emit(
                    "failure", kind=ex.kind.value, detail=detail, response=ADVICE[ex.kind]
                )
                notes.append(ADVICE[ex.kind])
                if ex.kind.value == "uncertain_write":
                    self.attention = "high:a save had an unknown result"
        if self.gate.fatal:
            self.stop_reason = "two saves had unknown results"
        return notes

    def before_model(self, callback_context, llm_request) -> None:
        """Remind the model of the run state; keep the newest snapshots, shrink older ones."""
        self.log.emit("note", kind="model_wait", text="Waiting for the model’s next action")
        config = getattr(llm_request, "config", None)
        if config is not None and isinstance(config.system_instruction, str):
            config.system_instruction += "\n\n" + self.run_state()
        seen = 0
        for content in reversed(llm_request.contents or []):
            for part in content.parts or []:
                fr = getattr(part, "function_response", None)
                if fr is None or not (fr.name or "").startswith("browser_"):
                    continue
                seen += 1
                text, _ = _text(fr.response or {})
                if seen > KEEP_SNAPSHOTS and not text.startswith(OLD_PREFIX):
                    # replace, never mutate: the part's response is also the session's history
                    short = {"content": [{"type": "text", "text": one_line(text)}]}
                    part.function_response = fr.model_copy(update={"response": short})
        return None

    def after_model(self, callback_context, llm_response) -> None:
        usage = llm_response.usage_metadata
        if usage:
            self.tokens_in += usage.prompt_token_count or 0
            self.tokens_out += usage.candidates_token_count or 0
        return None

    def seconds(self) -> float:
        return round(time.monotonic() - self.started, 1)


def exact_options(snapshot: str, target: str) -> str:
    """The exact option texts of the dropdown the model tried, from the last page it saw."""
    lines = snapshot.splitlines()
    for i, line in enumerate(lines):
        if f"[ref={target}]" in line and ("combobox" in line or "listbox" in line):
            for nxt in lines[i + 1 : i + 3]:
                m = re.search(r"options \(\d+, selected: \"[^\"]*\"\): (.*)", nxt)
                if m:
                    return (
                        "Use one of these exact option texts (or the record id inside "
                        f"them): {m.group(1)}"
                    )
    return "Take a fresh snapshot and copy the option text exactly as the list shows it."


REF_TARGET = re.compile(r"^\s*\[?\s*ref\s*=\s*([A-Za-z0-9_-]+)\s*\]?\s*$")


def normalize_targets(args: dict) -> None:
    """'[ref=f8e73]' -> 'f8e73' in place, for a target and for every form field's target.

    The snapshot shows refs as [ref=...]; models copy that wrapper. ADK passes this same dict
    to the tool, so fixing it here fixes the call."""

    def fix(value):
        m = REF_TARGET.match(value) if isinstance(value, str) else None
        return m.group(1) if m else value

    if "target" in args:
        args["target"] = fix(args["target"])
    for field in args.get("fields") or []:
        if isinstance(field, dict) and "target" in field:
            field["target"] = fix(field["target"])
