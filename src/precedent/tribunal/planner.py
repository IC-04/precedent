"""The Tribunal's own check planner: a model from a different family than Ava's.

It sees the request, the goal's conditions and the pages the run actually visited or
changed (from the browser and write logs), never Ava's reports of what she did. It picks
pages to read, then writes typed checks over what those pages really show, and names
any requirement of the request that no condition covers.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from precedent.tribunal.checks import Check, safe_path
from precedent.worker.context import read_page
from precedent.worker.verify import record_fields

Ask = Callable[[str, str, type[BaseModel]], BaseModel]
MAX_PAGES = 8
MAX_UNCOVERED = 3


class PageChoice(BaseModel):
    pages: list[str] = Field(description="Company page paths to read, most important first")


class CheckPlan(BaseModel):
    checks: list[Check]
    uncovered: list[str] = Field(
        default_factory=list,
        description="Explicit requirements of the request that no condition covers",
    )


PAGES = """You choose which company pages an independent verifier must read to decide whether
each condition of a task holds. Choose the records the work produced or changed, list pages
that show counts (for example a search that lists every matching record), and the source
pages that define what is correct: directories and context pages (who is who, settings,
working hours), policies, emails and chats. Use only paths of the form
/books/..., /mail/..., /drive/..., /chat/..., /calendar/...; search pages may carry a query
string. At most 8 pages."""

CHECKS = f"""You write exact checks that code will run against company pages. Operations:
- field_equals(path, label, value): the labelled field on a record page equals value
- field_present(path, label) / field_absent(path, label): the field is filled / empty
- row_exists(path, cells): a table row has all these column values
- row_count(path, cells, value): exactly value rows match (use a search or list page)
- text_contains(path, value): the page contains this exact text
- quote_in_source(path, value): a source page contains this exact quote
Labels and column names must be copied exactly from the page digests. Every expected value
needs a source: "request" or "condition" if the words appear there, or a DIFFERENT page
(never the page being checked) with source_quote copied exactly from it, such as a
directory or context page, a policy, an email or a chat. A record cannot prove itself.
Never invent values. Write at least one check
per condition when the pages make it checkable; skip conditions they cannot settle.
Then, separately, look for requirements the request states that NO condition covers.
A requirement is covered if any condition addresses it, even in different words or
partially (for example "find two times" is covered by a condition about two time
options; "save a draft" is covered by a condition about a saved draft). Most tasks have
none; return an empty list unless something the request explicitly asks for is entirely
absent from every condition. At most {MAX_UNCOVERED}. Refer to them in checks as u1, u2, u3."""


def visited_pages(events: list[dict]) -> list[str]:
    """Pages the run actually observed or changed: facts from the logs, not claims."""
    seen: list[str] = []
    for event in events:
        data = event.get("data", {})
        raw = data.get("url") if event.get("type") == "observation" else None
        if data.get("kind") == "app_effect":
            raw = str(data.get("path", ""))
            for suffix in ("/request-approval", "/edit", "/retire"):
                raw = raw.removesuffix(suffix)
            if raw.endswith("/new"):
                continue
        if not raw:
            continue
        parts = urlsplit(raw)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if safe_path(path) and path not in seen:
            seen.append(path)
    return seen[-40:]


def digest(path: str, html: str) -> str:
    page = read_page(html)
    fields = record_fields(html)
    lines = [f"PAGE {path} · {page.title}"]
    if fields:
        lines.append(
            "Fields: " + "; ".join(f"{k} = {v[:120]}" for k, v in list(fields.items())[:30])
        )
    for row in [r for r in page.rows if r][:12]:
        lines.append("Row: " + " | ".join(cell[:60] for cell in row))
    text = " ".join(page.pre) or " ".join(page.chunks)
    lines.append("Text: " + text[:1200])
    return "\n".join(lines)


def choose_pages(ask: Ask, request: str, conditions: list, visited: list[str]) -> list[str]:
    prompt = (
        f"Request: {request}\n\nConditions:\n"
        + "\n".join(f"- {c.id}: {c.text}" for c in conditions)
        + "\n\nPages the run visited or changed:\n"
        + "\n".join(f"- {p}" for p in visited)
    )
    choice = ask(PAGES, prompt, PageChoice)
    return [p for p in dict.fromkeys(choice.pages) if safe_path(p)][:MAX_PAGES]


def write_checks(ask: Ask, request: str, conditions: list, digests: list[str]) -> CheckPlan:
    prompt = (
        f"Request: {request}\n\nConditions:\n"
        + "\n".join(f"- {c.id} ({c.kind}): {c.text}" for c in conditions)
        + "\n\nPage digests (read by the verifier just now):\n\n"
        + "\n\n".join(digests)
    )
    plan = ask(CHECKS, prompt, CheckPlan)
    plan.uncovered = [u for u in plan.uncovered if u.strip()][:MAX_UNCOVERED]
    allowed = {c.id for c in conditions} | {f"u{i}" for i in range(1, len(plan.uncovered) + 1)}
    plan.checks = [c for c in plan.checks if c.condition_id in allowed and safe_path(c.path)]
    return plan


# --------------------------------------------------------------------------- models


def bedrock_ask(model: str | None = None) -> tuple[str, Ask]:
    from precedent.bedrock import Bedrock, BedrockSettings

    settings = BedrockSettings.from_env()
    client = Bedrock(settings, timeout=60.0, max_retries=1)
    name = model or settings.strong_model

    def ask(instruction: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        reply = client.respond(name, instruction, prompt, schema=schema)
        if reply.parsed is None:
            raise ValueError("no structured plan")
        return reply.parsed

    return name, ask


def gemini_ask(model: str | None = None) -> tuple[str, Ask]:
    from google import genai
    from google.genai import types

    from precedent.config import VertexSettings

    settings = VertexSettings.from_env()
    client = genai.Client(vertexai=True, project=settings.project, location=settings.location,
                          http_options=types.HttpOptions(timeout=60_000))  # fmt: skip
    name = model or os.getenv("PRECEDENT_MODEL_STRONG") or "gemini-3.6-flash"

    def ask(instruction: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        response = client.models.generate_content(
            model=name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=instruction,
                response_mime_type="application/json",
                response_schema=schema,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return schema.model_validate_json(response.text or "")

    return name, ask


def default_planner() -> tuple[str, Ask] | None:
    """A different family from Ava first (Bedrock), else a fresh Gemini call."""
    if os.getenv("PRECEDENT_TRIBUNAL_PLANNER", "1") == "0":
        return None
    for make in (bedrock_ask, gemini_ask):
        try:
            return make()
        except (ValueError, ImportError):
            continue
    return None
