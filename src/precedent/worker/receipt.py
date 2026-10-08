"""An honest partial receipt until the fresh browser verifier is implemented."""

from __future__ import annotations

from precedent.contracts import CheckResult, DecisionRecord, Receipt
from precedent.worker.events import EventLog, read_events


def write_receipt(log: EventLog, request: str, claimed: dict | None, cost: dict) -> Receipt:
    events = read_events(log.path)
    goal = next((e.data for e in events if e.type == "goal_contract"), {})
    decisions = [
        DecisionRecord.model_validate(e.data) for e in events if e.type == "decision_record"
    ]
    checks = [CheckResult.model_validate(e.data) for e in events if e.type == "check"]
    checked = {c.condition_id for c in checks}
    for condition in goal.get("conditions", []):
        if condition["id"] not in checked:
            checks.append(
                CheckResult(
                    condition_id=condition["id"],
                    text=condition["text"],
                    result="unknown",
                    evidence="Fresh browser verifier unavailable",
                )
            )
    receipt = Receipt(
        run_id=log.run_id,
        request=request,
        outcome="unknown",
        summary="The run ended without fresh goal verification. "
        + ((claimed or {}).get("summary") or cost.get("error") or "No completion claim recorded."),
        pending=["Fresh browser verification is not implemented; outcome remains unknown."],
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
        "Outcome: unknown",
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
