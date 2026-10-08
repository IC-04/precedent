"""Stage 1: the request becomes a GoalContract before the first action.

Every check at the end comes from this contract, so it must say what must be true
and what must not happen.
"""

from __future__ import annotations

import json

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from precedent.contracts import GoalContract

INSTRUCTION = """You turn a work request into a goal contract for an accounts-payable worker.
Write the outcome as one sentence describing the intended end state.
List conditions that must be true at the end (kind must_be_true, ids c1, c2, ...) and things
that must not happen (kind must_not_happen, ids n1, n2, ...). Always include must_not_happen
conditions for duplicates and for changes nobody asked for (for example bank details).
For each condition, add a check_hint saying how it could be checked by reading the apps.
List assumptions you are making and what is out of scope (for example approving the bill).
Do not invent company-specific facts you have not been given."""


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
            return goal
        prompt = f"Your contract has no must_not_happen conditions. Add them.\nRequest: {request}"
    return goal
