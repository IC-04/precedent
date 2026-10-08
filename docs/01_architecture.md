# Architecture and key decisions

## Shape of the system

```
                      ┌──────────────────────────── hidden from the worker ───┐
  seed + template ──► │ world generator ──► worlds/<seed>/world.db            │
                      │                 └─► worlds/<seed>/hidden.json (truth) │
                      └──────────────┬────────────────────────────────────────┘
                                     │ (db only)
                     ┌───────────────▼───────────────┐
                     │ company apps (FastAPI, :8100) │  /mail /books /drive /chat
                     │ server-rendered HTML forms    │
                     └───────────────▲───────────────┘
                                     │ real browser (Playwright, Chromium)
 request ──► console (:8000) ──► worker runner ───────────────────────────────┐
                 ▲                │ goal contract → context → plan → act ⇄ observe
                 │ SSE            │ → diagnose/replan → verify → receipt      │
                 └── runs/<id>/events.jsonl ◄──────────────────────────────────┘
                                                        grader ◄── world.db + hidden.json
```

## Decisions

**D1. Python only, managed with uv.** Python 3.11+, FastAPI, Jinja2, Playwright for Python, the Google Gen AI SDK and the OpenAI SDK (for OpenAI-compatible servers), Pydantic v2, SQLite through `sqlite3`, Typer for the CLI, pytest. One language keeps a one-person, few-day build moving and makes the interview walkthrough simple.

**D2. Proven SDKs for the plumbing; our own code for what we are judged on.** *(Revised 7 October; the first version was "no agent framework".)* The worker runs on Google ADK (`google-adk`, Apache-2.0): it owns model calls, tool-call formats (including Gemini 3 thought signatures), retries and sessions. The browser is driven through Playwright MCP (Microsoft, Apache-2.0). What stays ours is plain code that runs inside ADK's callbacks: the goal contract, company context, the decision-before-write rule, uncertain-write reconciliation, snapshot compaction, the event log and the verifier. Why the change: hand-writing provider adapters and tool plumbing is undifferentiated work that SDKs used by thousands of projects do better, and ADK's `before_tool_callback` and `on_model_error_callback` let our policies stay enforceable code rather than prompt text. What we would lose by going further (for example letting a browser-agent framework own the loop) is exactly what the reviewers judge, so we stop at the runtime.

**D3. The company is a set of real web apps, not mocks.** One FastAPI server with four apps under path prefixes: Mail (inbox, search, message view, attachments), Books (vendors, bills, approvals, search, history), Drive (folders, files, PDF download) and Chat (channels, post). They use plain HTML forms with stable labels and no JavaScript frameworks. Each app should feel like a different product (header, colour, layout), so the agent cannot rely on one template.

**D4. The worker uses a real browser through an accessibility snapshot.** Playwright MCP gives each observation as an accessibility snapshot with element refs, plus the URL and title; actions are its `browser_navigate`, `browser_click`, `browser_type`, `browser_select_option` and `browser_navigate_back` tools, filtered to that set. Our `after_tool_callback` compacts each snapshot (long dropdowns become a count, long tables are cut with a note) and older snapshots are summarised, so a step stays small. The browser can only reach the worker's gateway (`--allowed-origins`), and the gateway forwards to the company apps: every non-GET request is a consequential write and is refused unless a decision with sources was recorded first; a 5xx or a timeout marks an uncertain write. Screenshots are taken after every action for the console and for evidence only. Why not pixel-based computer use: it is slower, costs more and is less reliable, and the JD rewards reliability (ADK's own computer-use toolset is screenshot-based and needs a preview model). Pixel mode is listed under "next steps".

**D5. Gemini through ADK, authenticated with Vertex AI + ADC.** The agent model is `PRECEDENT_MODEL` (`gemini-3.8-flash`); the goal contract uses `PRECEDENT_MODEL_STRONG`. `make_model` is the shared boundary for goal, action and fallback models. It loads `VertexSettings`, discovers ADC with `google.auth.default`, and supplies explicit credentials, project, location and `vertexai=True` to the Google Gen AI SDK. API keys cannot select a different authentication path. The configured Cloud project is also the quota project. When a model keeps returning 503 or 429, `on_model_error_callback` sends the same request to the next model in `PRECEDENT_MODEL_FALLBACK`; the existing model order, retries and timeouts are preserved. Other providers remain a documented future path through ADK's LiteLLM integration, which is not installed. Tests use scripted models or mocked credentials. See [Cloud authentication](google_cloud_auth.md) for local ADC, runtime identities and IAM.

**D6. The loop is explicit and has named stages.** The runner calls stages in order, and each stage emits events:
1. `goal`: the request becomes a `GoalContract` (structured output via a tool schema), including what must not happen.
2. `context`: read policies, recent instructions and history for this kind of task; produce `Precedent` objects with source, authority level, support count, exceptions and status (usable, conflict or unresolved).
3. `plan`: an ordered list of steps, each with an expected observation.
4. `act ⇄ observe`: one tool call per turn, then a fresh snapshot. Compare against the expectation.
5. `diagnose`: classify failures as tool, interface, uncertain write, missing authority or business contradiction. Each class has a fixed response policy (see `worker/failures.py`).
6. `verify`: compile the goal contract into checks; read the state again through the browser; give each check pass, fail or unknown.
7. `receipt`: outcome (pass, fail, blocked or unknown), pending items, decisions with sources, what was left unchanged, checks.

**D7. Crash safety comes from re-reading, not from memory.** On start, the runner looks for an unfinished run with the same task ID. If it finds one, it treats its own log as intentions, not facts. It reconstructs state from the apps, using business keys (invoice number, vendor tax ID). Before retrying a write, it always searches for the record first.

**D8. Two kinds of verification.** The worker's *verifier* runs inside the worker's world: browser reads only. That is what the receipt reports. The *grader* is outside: it compares `world.db` with `hidden.json` and is the only thing the evaluation trusts.

**D9. Events are the single source of truth for the UI and the evaluation.** Each run writes `runs/<run_id>/events.jsonl` (schema in `contracts.py`) plus screenshots. The console tails this file over server-sent events. No database for runs.

**D10. Ghost baseline = same runner, different context stage.** `--worker baseline` swaps `context` for "put all policies and the SOP into the prompt", with no authority ranking and no history analysis. The model, tools, budget and verifier stay the same.

**D11. World generation is deterministic and template-driven.** `templates/northwind.yaml` and `templates/globex.yaml` define the org, accounts, policies (with dates), instructions, approval rules, vendors and planted problems. The generator uses `random.Random(seed)` to make history, current work and noise. The hidden truth holds the correct answer for every task and every planted trap.

**D12. The console is plain HTML plus a little JavaScript.** It has a task inbox, a live screenshot, the latest decision record, goal contract progress, the plan, and the receipt. It follows the "Watching Ava work" page in the vision document. No React.

## Why this will hold up in the interview

- Every claim in the demo can be traced to an event in `events.jsonl` and a row in `world.db`.
- The grader is independent of the worker, so a pass is not self-reported.
- Swapping the seed or the template shows that nothing is hard-coded.
- The loop is small enough to change live during the interview, for example adding a failure class or a check.

## Known risks and the fallback

| Risk | Fallback |
|---|---|
| The browser agent is too slow or flaky | Fewer, larger steps; deterministic "macro" tools for known form fills (D6, "automate what is known"), clearly labelled |
| A free-tier model is too weak or rate-limited | Swap provider by env var (D5); smaller snapshots; the macro tools for known form fills |
| Context building costs too much | Cache precedents per seed and task family; show the cost in the receipt |
| The ghost run does as well as Precedent | Report it honestly; it is kill criterion 1. The story falls back to state reconstruction and verification |
| Time runs out | Cut in the order P2 → Globex → eval breadth. Never cut Act 1, the verifier or the console |
