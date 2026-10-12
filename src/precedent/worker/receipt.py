"""Evidence receipts from recorded goal checks, with unsupported checks left unknown."""

from __future__ import annotations

from precedent.contracts import CheckResult, DecisionRecord, Receipt
from precedent.worker.events import EventLog, read_events
from precedent.worker.verify import outcome as checked_outcome


def write_receipt(log: EventLog, request: str, claimed: dict | None, cost: dict) -> Receipt:
    events = read_events(log.path)
    goal = next((e.data for e in events if e.type == "goal_contract"), {})
    decisions = [
        DecisionRecord.model_validate(e.data) for e in events if e.type == "decision_record"
    ]
    # Rechecks are append-only. The receipt reports the latest evidence per
    # condition; superseded results remain in the event log for review.
    latest = {
        e.data["condition_id"]: CheckResult.model_validate(e.data)
        for e in events
        if e.type == "check"
    }
    checks = list(latest.values())
    checked = {c.condition_id for c in checks}
    for condition in goal.get("conditions", []):
        if condition["id"] not in checked:
            checks.append(
                CheckResult(
                    condition_id=condition["id"],
                    text=condition["text"],
                    result="unknown",
                    evidence="No fresh check was recorded for this condition",
                )
            )
    result = checked_outcome(checks, cost.get("error"), (claimed or {}).get("claimed") == "blocked")
    if result == "pass" and cost.get("outcome", "unknown") != "pass":
        result = "unknown"
    pending = [f"Check unresolved: {c.text}" for c in checks if c.result == "unknown"]
    if result == "unknown" and not pending:
        pending = ["The run did not establish a complete verified outcome."]
    verified = sum(c.result == "pass" for c in checks)
    prefix = (
        f"Fresh checks passed for {verified} of {len(checks)} conditions. "
        if checks
        else "No fresh goal checks were recorded. "
    )
    receipt = Receipt(
        run_id=log.run_id,
        request=request,
        outcome=result,
        summary=prefix
        + "Worker report: "
        + ((claimed or {}).get("summary") or cost.get("error") or "No completion claim recorded."),
        pending=pending,
        questions_asked=cost.get("questions", 0),
        decisions=decisions,
        checks=checks,
        sources=list(dict.fromkeys(s for d in decisions for s in d.sources)),
        cost={k: cost.get(k) for k in ("tokens_in", "tokens_out", "usd", "seconds", "steps")},
    )
    lines = [
        "# Evidence receipt",
        "",
        f"Run: {log.run_id}",
        f"Request: {request}",
        f"Outcome: {receipt.outcome}",
        "",
        receipt.summary,
        "",
        "## Checks",
        "",
    ]
    lines += [f"- {c.result}: {c.text} ({c.evidence or 'No evidence'})" for c in checks]
    lines += ["", "## Decisions and sources", ""]
    lines += [f"- {d.decided} Sources: {', '.join(d.sources)}" for d in decisions]
    lines += [
        "",
        "USD: unavailable" if cost.get("usd") is None else f"USD: {cost['usd']}",
        "",
        "Independent grading is separate from this worker receipt.",
    ]
    (log.dir / "receipt.md").write_text("\n".join(lines) + "\n")
    log.emit("receipt", **receipt.model_dump())
    return receipt
