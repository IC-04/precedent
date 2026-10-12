"""Stage 1: the request becomes a GoalContract before the first action.

Every check at the end comes from this contract, so it must say what must be true
and what must not happen.
"""

from __future__ import annotations

import json
import re

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from precedent.contracts import Condition, GoalContract, MeetingIntent

INSTRUCTION = """You turn a work request into a goal contract for an accounts-payable worker.
Write the outcome as one sentence describing the intended end state.
List conditions that must be true at the end (kind must_be_true, ids c1, c2, ...) and things
that must not happen (kind must_not_happen, ids n1, n2, ...). Always include must_not_happen
conditions for duplicates and for changes nobody asked for (for example bank details).
For each condition, add a check_hint saying how it could be checked by reading the apps.
Each condition must cover one independently checkable fact. Separate amount, invoice
number, dates, attachment, coding and approval routing into their own conditions when
the request needs them; never bundle all invoice details into one condition.
The app stores one account code per bill; it has no separate line-item ledger.
Express coding as the bill account field.
List assumptions you are making and what is out of scope (for example approving the bill).
For each condition set claims to the exact proof keys it requires: bill_count,
Vendor, Invoice number, Amount, Invoice date, Due date, Account, Approver, Status,
Attachment, approval_status, vendor_unchanged, latest_invoice. Use unsupported for
other claims that these keys do not express. Separate routing status from approver.
A vendor settings invariant needs vendor_unchanged, not just a bank-account check.
Express end states: an existing correct bill satisfies entry without creating a duplicate.
Do not assert that this run newly created a record before checking its business key.
Do not invent company-specific facts you have not been given."""


def complete_invoice_contract(goal: GoalContract) -> GoalContract:
    """Invoice entry has a minimum proof surface, even when the goal model omits a field."""
    if not re.search(r"\binvoice\b", goal.request, re.I) or not re.search(
        r"\b(enter|record|create)\b", goal.request, re.I
    ):
        return goal
    required = {
        "Vendor": "The saved bill belongs to the invoice vendor.",
        "Invoice number": "The saved invoice number matches the source document.",
        "Amount": "The saved amount and currency match the source invoice.",
        "Invoice date": "The saved invoice date matches the source document.",
        "Due date": "The saved due date matches the source document.",
        "Account": "The saved account code follows current authoritative accounting rules.",
        "Attachment": "The attached document is the selected source invoice.",
    }
    if re.search(r"latest|most recent", goal.request, re.I):
        required["latest_invoice"] = (
            "The selected invoice is the latest dated invoice in the accessible vendor mailbox."
        )
    if re.search(r"route|approval", goal.request, re.I):
        required.update(
            {
                "Approver": (
                    "The bill is assigned to the correct approver under current routing rules."
                ),
                "Status": "The bill status is pending approval.",
                "approval_status": "The current approval request has pending status.",
            }
        )
    covered = {claim for condition in goal.conditions for claim in condition.claims}
    for key, text in required.items():
        if key not in covered:
            identifier = "proof-" + key.lower().replace(" ", "-")
            if any(c.id == identifier for c in goal.conditions):
                continue
            goal.conditions.append(
                Condition(id=identifier, text=text, kind="must_be_true", claims=[key])
            )
    return goal


def _config(thinking: str | None) -> types.GenerateContentConfig | None:
    """A thinking level for one stage; None keeps the model's own default."""
    if not thinking:
        return None
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=thinking.upper())
    )


async def structured(
    instruction: str,
    prompt: str,
    schema,
    model,
    on_model_error=None,
    after_model=None,
    name: str = "structured",
    thinking: str | None = None,
):
    """One model call that must return `schema` (a Pydantic model) as JSON."""
    agent = LlmAgent(
        name=name,
        model=model,
        instruction=instruction,
        output_schema=schema,
        on_model_error_callback=on_model_error,
        after_model_callback=after_model,
        generate_content_config=_config(thinking),
    )
    runner = InMemoryRunner(agent=agent, app_name=name)
    session = await runner.session_service.create_session(app_name=name, user_id="ava")
    text = ""
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(user_id="ava", session_id=session.id, new_message=message):
        if event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts) or text
    return schema.model_validate(json.loads(text))


async def write_goal(
    request: str, model, on_model_error=None, after_model=None, thinking: str | None = "MEDIUM"
) -> GoalContract:
    """One structured call; re-asks once if the contract has no must_not_happen condition."""
    from precedent.worker import native
    from precedent.worker.meetings import is_meeting, meeting_goal

    if native.is_native(request):
        return native.native_goal(request)
    if is_meeting(request):
        intent = await structured(
            "Extract the meeting intent from the user request only. Do not infer company facts. "
            "Return participant name/query, topic, duration (default 30 minutes), date_mode "
            "next_week or explicit (ISO range_start inclusive/range_end exclusive), otherwise "
            "unresolved. local_hold is true ONLY when the user explicitly asks for a local "
            "hold/reservation. hold_option is 1 or 2 if specified, otherwise 1. "
            "Reading Mail and Chat, inspecting calendars, finding times, "
            "saving email drafts, and explicitly requested local tentative holds ARE SUPPORTED. "
            "Usually unsupported is an empty list. "
            "Put only external sending or confirmed invitations "
            "in unsupported. Draft preparation does not send. Never replace an "
            "explicit date range with next_week.",
            request,
            MeetingIntent,
            model,
            on_model_error,
            after_model,
            name="meeting_goal",
            thinking=thinking,
        )
        return meeting_goal(request, intent)
    agent = LlmAgent(
        name="goal_writer",
        model=model,
        instruction=INSTRUCTION,
        output_schema=GoalContract,
        output_key="goal",
        on_model_error_callback=on_model_error,
        after_model_callback=after_model,
        generate_content_config=_config(thinking),
    )
    runner = InMemoryRunner(agent=agent, app_name="goal")
    session = await runner.session_service.create_session(app_name="goal", user_id="ava")
    prompt = f"Request: {request}"
    for _ in range(2):
        text = ""
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for event in runner.run_async(
            user_id="ava", session_id=session.id, new_message=message
        ):
            if event.content and event.content.parts:
                text = "".join(p.text or "" for p in event.content.parts) or text
        goal = GoalContract.model_validate(json.loads(text) | {"request": request})
        if any(c.kind == "must_not_happen" for c in goal.conditions):
            return complete_invoice_contract(goal)
        prompt = f"Your contract has no must_not_happen conditions. Add them.\nRequest: {request}"
    return complete_invoice_contract(goal)
