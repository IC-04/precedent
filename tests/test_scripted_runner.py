"""No model API calls: ADK + real isolated MCP + captures + cleanup, with a scripted model."""

import asyncio
import json
import re

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from precedent.worker import runner
from precedent.worker.events import read_events


class ScriptedModel(BaseLlm):
    _turn: int = PrivateAttr(default=0)
    parallel: bool = False

    async def generate_content_async(self, llm_request, stream=False):
        if llm_request.config.response_schema:
            data = {
                "request": "Read company overview",
                "outcome": "Company overview read",
                "conditions": [
                    {"id": "c1", "text": "Company overview is read", "kind": "must_be_true"},
                    {"id": "n1", "text": "No company records changed", "kind": "must_not_happen"},
                ],
                "assumptions": [],
                "out_of_scope": ["Writes"],
            }
            part = types.Part(text=json.dumps(data))
        else:
            if self._turn == 0:
                name, args = (
                    "update_plan",
                    {"steps": ["Read the overview | Company identity appears"]},
                )
            elif self._turn == 1:
                text = str(llm_request.config.system_instruction)
                base = re.search(r"http://localhost:\d+", text)[0]
                name, args = "browser_navigate", {"url": base + "/"}
            else:
                name, args = (
                    "finish",
                    {"outcome": "unknown", "summary": "Scripted read-only validation"},
                )
            self._turn += 1
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        parts = [part]
        if self.parallel and self._turn == 2:
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        name="browser_navigate", args={"url": base + "/mail/"}
                    )
                )
            )
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def test_scripted_adk_run_captures_the_worker_session_and_finishes_unknown(
    tmp_path, live_apps, monkeypatch
):
    monkeypatch.setattr(runner, "make_model", lambda name: ScriptedModel(model="scripted"))
    cfg = runner.RunConfig(
        request="Read company overview", apps_url=live_apps[0], runs_root=tmp_path
    )
    result = asyncio.run(runner.run(cfg))
    assert result["error"] is None
    assert result["outcome"] == "unknown"
    events = read_events(tmp_path / result["run_id"] / "events.jsonl")
    captures = [e for e in events if e.type == "observation" and e.data.get("screenshot")]
    assert len(captures) == 1
    assert (
        (tmp_path / result["run_id"] / captures[0].data["screenshot"])
        .read_bytes()
        .startswith(b"\x89PNG")
    )
    actions = [e for e in events if e.type == "action"]
    assert [e.data["tool"] for e in actions] == ["browser_navigate"]
    assert captures[0].data["action_step_id"] == actions[0].data["step_id"]
    assert events[-1].type == "run_finished"
    receipt = next(e for e in events if e.type == "receipt")
    assert receipt.data["outcome"] == "unknown"
    assert all(c["result"] == "unknown" for c in receipt.data["checks"])


def test_parallel_model_calls_are_serialized_with_their_own_capture(
    tmp_path, live_apps, monkeypatch
):
    monkeypatch.setattr(
        runner, "make_model", lambda name: ScriptedModel(model="scripted", parallel=True)
    )
    result = asyncio.run(
        runner.run(
            runner.RunConfig(
                request="Read the overview and mail", apps_url=live_apps[0], runs_root=tmp_path
            )
        )
    )
    assert result["error"] is None
    events = read_events(tmp_path / result["run_id"] / "events.jsonl")
    work = [e for e in events if e.type in ("action", "observation")]
    assert [e.type for e in work] == ["action", "observation", "action", "observation"]
    for action, observation in zip(work[::2], work[1::2], strict=True):
        assert observation.data["url"] == action.data["args"]["url"]
        assert observation.data["action_step_id"] == action.data["step_id"]
        assert observation.data["screenshot"]
