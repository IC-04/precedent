"""Models on Amazon Bedrock: the second model family, beside Gemini.

Gemini on Vertex AI does Ava's routine work. Bedrock models are used only where a
different family or a stronger model earns its place: the Tribunal's jurors, the
pre-write reviewer, the planner and policy screening. Authentication is a Bedrock API
key read by the OpenAI SDK's Bedrock provider from `AWS_BEARER_TOKEN_BEDROCK`; this
module never reads, stores or prints the key itself.

Bedrock Mantle serves models on two routes. OpenAI's own models and xAI's sit under
`/openai/v1` and use the Responses API; most other families sit under `/v1` and use
Chat Completions. Model listing exists only under `/v1`.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

KEY_VAR = "AWS_BEARER_TOKEN_BEDROCK"
RESPONSES_ROUTE = "/openai/v1"
CHAT_ROUTE = "/v1"
_RESPONSES_PREFIXES = ("openai.gpt-5", "openai.gpt-6", "xai.")


def route_for(model: str) -> str:
    return RESPONSES_ROUTE if model.startswith(_RESPONSES_PREFIXES) else CHAT_ROUTE


@dataclass(frozen=True)
class BedrockSettings:
    region: str
    project: str | None  # a Bedrock Mantle project id (proj_...); None uses the default project
    judge_model: str  # a juror from another family: structured answers over text and screenshots
    strong_model: str  # disputes and planning
    screen_model: str  # policy classifier for untrusted text (e.g. instructions hidden in invoices)

    @classmethod
    def from_env(cls) -> BedrockSettings:
        if not os.getenv(KEY_VAR, "").strip():
            raise ValueError(f"Set {KEY_VAR} to your Amazon Bedrock API key in .env.")
        env = lambda name, default: os.getenv(name, "").strip() or default  # noqa: E731
        return cls(
            region=env("AWS_REGION", "") or env("AWS_DEFAULT_REGION", "us-east-1"),
            project=env("PRECEDENT_BEDROCK_PROJECT", None),
            judge_model=env("PRECEDENT_BEDROCK_MODEL_JUDGE", "qwen.qwen3-vl-235b-a22b-instruct"),
            strong_model=env("PRECEDENT_BEDROCK_MODEL_STRONG", "xai.grok-4.3"),
            screen_model=env("PRECEDENT_BEDROCK_MODEL_SCREEN", "openai.gpt-oss-safeguard-120b"),
        )


@dataclass
class Reply:
    model: str
    text: str
    parsed: BaseModel | None
    seconds: float
    input_tokens: int | None
    output_tokens: int | None


@dataclass
class Bedrock:
    """One OpenAI client per Mantle route, created on first use."""

    settings: BedrockSettings
    http_client: Any = None
    timeout: float = 60.0
    max_retries: int = 2
    _clients: dict[str, Any] = field(default_factory=dict)

    def client(self, route: str):
        if route not in self._clients:
            from openai import OpenAI
            from openai.providers import bedrock

            region = self.settings.region
            base = f"https://bedrock-mantle.{region}.api.aws{route}"
            self._clients[route] = OpenAI(
                provider=bedrock(region=region, base_url=base),
                project=self.settings.project,
                timeout=self.timeout,
                max_retries=self.max_retries,
                http_client=self.http_client,
            )
        return self._clients[route]

    def models(self) -> list[str]:
        return sorted(m.id for m in self.client(CHAT_ROUTE).models.list())

    def respond(
        self,
        model: str,
        instructions: str,
        text: str,
        images: list[bytes] | None = None,
        schema: type[BaseModel] | None = None,
        reasoning: str | None = None,
    ) -> Reply:
        """One call; structured when `schema` is given. Images are PNG or JPEG bytes."""
        urls = [_data_url(image) for image in images or []]
        started = time.monotonic()
        if route_for(model) == RESPONSES_ROUTE:
            text_out, parsed, usage = self._responses(model, instructions, text, urls, schema,
                                                      reasoning)  # fmt: skip
            tokens_in, tokens_out = (
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
            )
        else:
            text_out, parsed, usage = self._chat(model, instructions, text, urls, schema)
            tokens_in, tokens_out = (
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
        return Reply(model, text_out, parsed, round(time.monotonic() - started, 2), tokens_in,
                     tokens_out)  # fmt: skip

    def _responses(self, model, instructions, text, urls, schema, reasoning):
        content = [{"type": "input_text", "text": text}]
        content += [{"type": "input_image", "image_url": url} for url in urls]
        request: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
        }
        if reasoning:
            request["reasoning"] = {"effort": reasoning}
        api = self.client(RESPONSES_ROUTE).responses
        if schema is not None:
            response = api.parse(text_format=schema, **request)
            return response.output_text or "", response.output_parsed, response.usage
        response = api.create(**request)
        return response.output_text or "", None, response.usage

    def _chat(self, model, instructions, text, urls, schema):
        content: list[dict] = [{"type": "text", "text": text}]
        content += [{"type": "image_url", "image_url": {"url": url}} for url in urls]
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": content if urls else text},
        ]
        api = self.client(CHAT_ROUTE).chat.completions
        if schema is not None:
            response = api.parse(model=model, messages=messages, response_format=schema)
            message = response.choices[0].message
            return message.content or "", message.parsed, response.usage
        response = api.create(model=model, messages=messages)
        return response.choices[0].message.content or "", None, response.usage


def _data_url(image: bytes) -> str:
    kind = "png" if image[:4] == b"\x89PNG" else "jpeg"
    return f"data:image/{kind};base64,{base64.b64encode(image).decode()}"


class _Ping(BaseModel):
    answer: str


def check(bedrock: Bedrock) -> list[str]:
    """List reachable models, then one small call to each configured role."""
    s = bedrock.settings
    available = bedrock.models()
    lines = [f"{len(available)} models listed for this key"]
    roles = (("judge", s.judge_model, _Ping), ("strong", s.strong_model, _Ping),
             ("screen", s.screen_model, None))  # fmt: skip
    for role, model, schema in roles:
        if model not in available:
            lines.append(f"{role}: {model} is not listed for this key")
            continue
        try:
            reply = bedrock.respond(model, "Answer in one word.", "Reply with the word ready.",
                                    schema=schema)  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - report each role separately
            lines.append(f"{role}: {model} failed: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        answer = reply.parsed.answer if reply.parsed else reply.text.strip()[:30]
        lines.append(f"{role}: {model} answered {answer!r} in {reply.seconds} s")
    return lines
