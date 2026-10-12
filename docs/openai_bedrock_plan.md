# OpenAI models through Amazon Bedrock: plan

Status: proposed on 10 Oct 2026. Deadline: 12 Oct 2026, 11:59 PM IST.

> **Update, same evening: measured on the real key.** GPT-5.x/6.x and Claude are listed but denied for this account ("not available for this account"; AWS grants access separately). The roles below are filled by models that work today: **Qwen3-VL 235B** (juror and reviewer: structured answers and screenshots, about 1 s), **Grok 4.3** (planner and disputes: structured answers and screenshots, about 4 s) and **gpt-oss-safeguard-120b** (policy screening, about 0.6 s). Read GPT-6 Luna as Qwen3-VL and GPT-6 Sol as Grok 4.3 below. If AWS later grants GPT-6 access, it is a one-line `.env` change.

Gemini on Vertex AI stays Ava's primary brain for every routine turn. OpenAI models, reached through the user's Amazon Bedrock key, are brought in only where a stronger planner, a second opinion or a different model family adds something we can show.

## What Bedrock gives us (researched 10 Oct)

| Item | Finding | Source |
|---|---|---|
| Models | GPT-6 Sol and GPT-6 Luna (Mantle `us-east-1`; Runtime profiles `us.`/`global.openai.gpt-6-*`); GPT-6 Astra (Mantle `us-west-2`, generally available Sep 2026); the GPT-5.6 Sol/Terra/Luna family | OpenAI Bedrock guide, AWS what's-new |
| Auth | A Bedrock API key sent as a bearer token, read from `AWS_BEARER_TOKEN_BEDROCK`; SigV4 also works | OpenAI Bedrock guide |
| Endpoint | OpenAI-compatible Mantle base URL `https://bedrock-mantle.<region>.api.aws/openai/v1` | OpenAI Bedrock guide, AWS docs |
| APIs | Responses and Chat Completions | same |
| Features available | Image input, structured outputs, function calling, reasoning effort, streaming, prompt caching, **computer use (we execute the actions)**, hosted web search (Mantle only) | same |
| Not available | **The Decisions API is not listed**; no remote MCP servers, no hosted multi-agent, no shell tool | same |
| Price | Same rates as OpenAI first-party, with no AWS markup | AWS blog |

Consequences:
- The Tribunal judge runs on the Responses API with structured output. Confidence comes from agreement across k independent samples, not from token probabilities. If a direct OpenAI key turns up later, the Decisions API becomes a drop-in, calibrated alternative behind the same `Judge` interface.
- Which of Sol and Astra is stronger for planning is settled empirically on day 1: list `/models`, then run 5 planning prompts on each and compare.

## How it plugs in

- **ADK agents:** ADK 2.11's `LiteLlm` wrapper (already in the venv) with `model="openai/<bedrock model id>"`, `api_base=<Mantle URL>` and `api_key=` the bearer token. This needs the `litellm` package, a new dependency awaiting approval.
- **One-shot calls** (judge, planner, distiller): the `structured()` helper in `worker/goal.py` gains a provider switch.
- **Routing** lives in one module, `worker/models.py`:
  - a role-to-model table (`plan`, `act`, `escalate`, `judge`, `review`, `distil`, `triage`)
  - set by env vars such as `PRECEDENT_MODEL_PLAN=bedrock:openai.gpt-6-sol`
  - every call emits a `model_call` event (role, provider, model, seconds, tokens)
- The existing `Fallback` class already swaps models mid-run, so escalation reuses the same mechanism.

## Where OpenAI earns its place (ranked by value for the demo)

1. **The Tribunal: an independent judge (GPT-6 Luna for cheap per-claim calls, Sol for disputes).**
   - Its own read-only browser captures a screenshot and page text of the target records.
   - It never reads Ava's claims, receipt or event log.
   - It asks one typed question per atomic claim. k=3 samples give a vote share, which becomes the confidence.
   - Its verdict sits beside Ava's own checks and the ground-truth grader.
   - It is calibrated against ~45 saved runs plus deliberately broken fixtures, and reported as a confusion matrix.
   - A different model family from Ava is what makes the independence claim credible.
2. **Four-eyes check before every consequential write (Luna).**
   - Accounts payable already practises maker and checker.
   - Before the gateway forwards a save, a fast reviewer sees the filled form, the recorded decision and its cited sources, and answers "does this write match the decision and its sources?"
   - A "no" blocks the write and returns the reason to Ava.
   - It's visible in the UI as a second stamp on each write.
3. **The planner: goal contract and verification plan (Sol at high reasoning).**
   - This is where the compound-claim bug lives: one narrow check discharging a broad claim.
   - A stronger planner splits the goal into atomic claims and checks; code still enforces coverage.
4. **Senior-colleague escalation during computer use.**
   - Triggered when Gemini stalls: repeated failures, stall nudges, an uncertain save, a refusal loop.
   - Ava hands the next N turns to GPT-6 Sol with the same tools and run state, then hands back.
   - The UI shows the handoff ("Ava asked a senior colleague"), and the ledger records it.
5. **Skill distiller (Sol), for M3.**
   - Turns a verified run trace into a reviewed, instruction-only skill card with its sources.
   - Gemini executes the skill on later invoices; a policy change revokes it.
6. **Inbox triage and injection screening (Luna), for M4.**
   - Classifies each inbox item: new invoice, duplicate, ambiguous, or suspicious embedded instructions.
   - This is a second line of defence; the gateway's gate remains the hard control.
7. **Stretch: vision computer use** for a scanned-PDF invoice that has no DOM, using the computer-use tool on Bedrock. Only if 1–6 are done.

Rejected:
- Replacing Gemini on routine turns: slower and costlier, with no measured gain.
- Using OpenAI for the context stage's validation: that stays in code.

## WOW moments this enables

- **Three verdicts on stage:** Ava's checks, the GPT-6 judge and the grader, with confidence bars; a disagreement is flagged in red.
- **The four-eyes stamp** on every write. One broken fixture is built so that the checker catches a wrong approver before it's saved.
- **"Ava called a senior colleague":** a visible handoff to GPT-6 Sol on a stuck step, and back to Gemini.
- **The model ledger:** a per-run breakdown of which model did what, with seconds, tokens and dollars ("Ava's team").
- **Learning gain:** invoice 2 with a Sol-distilled skill runs faster, timed live.
- **The poisoned invoice** caught twice: by the triage model and by the write gate.

## Phases

| When | Phase | Done when |
|---|---|---|
| 10 Oct evening | **0. Connect:** key in `.env`, `/models` listed, one call per model, `worker/models.py` routing plus the `model_call` ledger; Sol vs Astra planning bake-off | `precedent check-model --provider bedrock` passes; tests green |
| 10–11 Oct | **1. Tribunal and four-eyes:** judge evidence capture, per-claim questions, k-vote confidence, the three-verdict UI, the pre-write reviewer in the gateway, broken fixtures, calibration report; grader and verifier bugs fixed | Confusion matrix in `docs/`; 3 consecutive fresh runs where all three verdicts agree |
| 11 Oct | **2. Planner and escalation:** Sol writes the goal contract and check plan; stall-triggered escalation with handoff events and UI | Compound-claim regression green; one recorded escalation that recovers |
| 11 Oct evening | **3. Ava learns:** Sol distils a skill, you approve it on the Mind page, invoice 2 runs with it, a policy change revokes it | Before/after timing on the same seed |
| 12 Oct morning | **4. Inbox zero:** Luna triage, a 5–6 invoice mission-control grid, a Chat question to the CFO, the poisoned invoice refused | One end-to-end recorded run |
| 12 Oct afternoon | **5. Submission:** README, evaluation tables, model ledger, recording | Fresh-clone run works |

## Rules kept

- The company-data boundary is unchanged: no model reads `world.db` or `hidden.json`. The judge reads pages only.
- Keys stay in `.env` and are never printed or committed. CLAUDE.md's "Vertex AI with ADC only" rule gets amended for this one Bedrock key, with the user's approval.
- An unreachable or failed OpenAI call degrades to today's behaviour: Gemini keeps working, and the judge's verdict becomes unknown.
