"""Bedrock models: routes, request shapes, project header and key handling. No real model calls."""

import json

import httpx2
import pytest
from pydantic import BaseModel

from precedent.bedrock import KEY_VAR, Bedrock, BedrockSettings, check, route_for

FAKE_KEY = "test-bedrock-key-not-real"
PNG = b"\x89PNG fake"


class Verdict(BaseModel):
    holds: bool
    reason: str


def _responses_body(text: str) -> dict:
    return {
        "id": "resp_1", "object": "response", "created_at": 0, "status": "completed",
        "model": "xai.grok-4.3", "output": [{
            "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
    }  # fmt: skip


def _chat_body(text: str) -> dict:
    return {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "qwen",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
    }  # fmt: skip


LISTED = ["xai.grok-4.3", "qwen.qwen3-vl-235b-a22b-instruct", "openai.gpt-oss-safeguard-120b"]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv(KEY_VAR, FAKE_KEY)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PRECEDENT_BEDROCK_PROJECT", "proj_test123")
    monkeypatch.delenv("AWS_BEDROCK_BASE_URL", raising=False)
    for name in ("JUDGE", "STRONG", "SCREEN"):
        monkeypatch.delenv(f"PRECEDENT_BEDROCK_MODEL_{name}", raising=False)


def _bedrock(seen, answer):
    def handler(request):
        seen.append(request)
        path = request.url.path
        if path == "/v1/models":
            data = [{"id": m, "object": "model", "created": 0, "owned_by": "aws"} for m in LISTED]
            return httpx2.Response(200, json={"object": "list", "data": data})
        if path == "/openai/v1/responses":
            return httpx2.Response(200, json=_responses_body(answer))
        if path == "/v1/chat/completions":
            return httpx2.Response(200, json=_chat_body(answer))
        return httpx2.Response(404, json={"error": {"message": f"no route {path}"}})

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return Bedrock(BedrockSettings.from_env(), http_client=client)


def test_settings_require_the_key(monkeypatch):
    monkeypatch.delenv(KEY_VAR, raising=False)
    with pytest.raises(ValueError, match=KEY_VAR):
        BedrockSettings.from_env()


def test_routes_follow_the_model_family():
    assert route_for("xai.grok-4.3") == route_for("openai.gpt-6-sol") == "/openai/v1"
    assert route_for("qwen.qwen3-vl-235b-a22b-instruct") == "/v1"
    assert route_for("openai.gpt-oss-120b") == "/v1"


def test_responses_route_sends_project_reasoning_and_image(env):
    seen = []
    bedrock = _bedrock(seen, json.dumps({"holds": True, "reason": "matches"}))
    reply = bedrock.respond("xai.grok-4.3", "Judge.", "Is the approver Ana?", images=[PNG],
                            schema=Verdict, reasoning="low")  # fmt: skip
    assert reply.parsed == Verdict(holds=True, reason="matches")
    assert (reply.input_tokens, reply.output_tokens) == (12, 5)
    request = seen[0]
    assert request.url.host == "bedrock-mantle.us-east-1.api.aws"
    assert request.url.path == "/openai/v1/responses"
    assert request.headers["openai-project"] == "proj_test123"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    sent = json.loads(request.content)
    assert sent["reasoning"] == {"effort": "low"}
    image = sent["input"][0]["content"][1]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")


def test_chat_route_sends_system_instructions_and_image(env):
    seen = []
    bedrock = _bedrock(seen, json.dumps({"holds": False, "reason": "different approver"}))
    reply = bedrock.respond("qwen.qwen3-vl-235b-a22b-instruct", "Judge.", "Who approves?",
                            images=[PNG], schema=Verdict)  # fmt: skip
    assert reply.parsed == Verdict(holds=False, reason="different approver")
    assert (reply.input_tokens, reply.output_tokens) == (20, 7)
    request = seen[0]
    assert request.url.path == "/v1/chat/completions"
    sent = json.loads(request.content)
    assert sent["messages"][0] == {"role": "system", "content": "Judge."}
    parts = sent["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert sent["response_format"]["type"] == "json_schema"


def test_check_covers_every_role_and_never_prints_the_key(env):
    bedrock = _bedrock([], json.dumps({"answer": "ready"}))
    lines = check(bedrock)
    assert lines[0] == "3 models listed for this key"
    assert all("answered" in line for line in lines[1:]), lines
    assert FAKE_KEY not in "\n".join(lines) and FAKE_KEY not in repr(bedrock.settings)
