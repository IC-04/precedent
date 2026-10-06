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

**D1. Python only, managed with uv.** Python 3.11+, FastAPI, Jinja2, Playwright for Python, the Anthropic SDK, Pydantic v2, SQLite through `sqlite3`, Typer for the CLI, pytest. One language keeps a one-person, few-day build moving and makes the interview walkthrough simple.

**D2. No agent framework.** The loop is about 300 lines of our own code. The interview will ask why the agent did each thing; we need to own every line of the loop. Frameworks would hide the parts we are judged on: observation, recovery and verification.

**D3. The company is a set of real web apps, not mocks.** One FastAPI server with four apps under path prefixes: Mail (inbox, search, message view, attachments), Books (vendors, bills, approvals, search, history), Drive (folders, files, PDF download) and Chat (channels, post). They use plain HTML forms with stable labels and no JavaScript frameworks. Each app should feel like a different product (header, colour, layout), so the agent cannot rely on one template.

**D4. The worker uses a real browser through an accessibility snapshot.** Each observation is a compact text snapshot of the page, with element refs (`[e14] button "Save draft"`), the URL and the title. Actions are `goto`, `click(ref)`, `fill(ref, text)`, `select(ref, option)`, `download(ref)` → local file, `read_file(path)` (PDF text) and `back`. Screenshots are taken after every action for the console and for evidence only. Why not pixel-based computer use: it is slower, costs more and is less reliable, and the JD rewards reliability. It is still real browser use. Pixel mode is listed under "next steps".

**D5. Model: Claude through the Anthropic Messages API with tool use.** The default is `claude-sonnet-5-5` for every step; set `PRECEDENT_MODEL` to change it. Goal contracts, context building and verification-check compilation may use `PRECEDENT_MODEL_STRONG` (default `claude-opus-5-5`). Use prompt caching on the system prompt and the company-context block. Both workers use the same model and budget in the ghost run.

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
| Context building costs too much | Cache precedents per seed and task family; show the cost in the receipt |
| The ghost run does as well as Precedent | Report it honestly; it is kill criterion 1. The story falls back to state reconstruction and verification |
| Time runs out | Cut in the order P2 → Globex → eval breadth. Never cut Act 1, the verifier or the console |
