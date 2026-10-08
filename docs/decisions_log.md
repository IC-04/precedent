# Decisions log

One line per decision. The README's design-decisions section is built from this file.

- 2026-10-07: Python only, with uv, because a one-person, few-day build needs one language and a simple interview walkthrough.
- 2026-10-07: no agent framework, because the loop, recovery and verification are what we are judged on and must be fully ours.
- 2026-10-07: browser accessibility snapshots instead of pixel computer use, because they are faster, cheaper and more reliable, and still real browser operation.
- 2026-10-07: a grader independent of the worker reads world.db and hidden.json, because a pass must not be self-reported.
- 2026-10-07: the ghost baseline uses the same runner and only swaps the context stage, so the comparison isolates company context.
- 2026-10-07: Gemini by default behind a provider-agnostic LLM interface, with open-weight models through an OpenAI-compatible adapter, so no paid key is needed to build, run or review.
- 2026-10-07: the world generator applies the same rule functions to write history and to compute hidden.json, so the hidden truth agrees with its seed by construction.
- 2026-10-07: the canonical seed (7) pins every story value from the brief; other seeds sample the same specs from Random(seed), so a pinned demo and varied evaluation share one code path.
- 2026-10-07: items for later acts (Act 3, Act 4) are generated into worlds/<seed>/held/ and delivered by a scenario hook, so they cannot interfere with earlier acts.
- 2026-10-07: a fallback model chain (PRECEDENT_MODEL_FALLBACK, Flash models only) because gemini-3.8-flash returned repeated 503s and Pro models have no free-tier quota.
- 2026-10-07: the worker runs on Google ADK with Playwright MCP instead of a hand-written loop, because SDKs used by thousands of projects handle model and browser plumbing better; our policies stay as code in ADK callbacks and a gateway.
- 2026-10-07: consequential writes are detected and gated at a worker-side HTTP gateway (any non-GET request), because an accessibility snapshot cannot say which button submits a POST, and the network boundary cannot be talked around by the model.
- 2026-10-07: the specs are a guide, not the ground truth; when evidence disagrees with a spec, the spec changes and the reason is logged here.
- 2026-10-07: the WS3 spike passed (ADK drove our apps through Playwright MCP; a POST without a decision was refused at the gateway; fallback switched models), so the SDK route is adopted; gemini-3.8-flash was too overloaded to finish the spike, so development runs use gemini-3.6-flash via PRECEDENT_MODEL.
- 2026-10-07: the worker's browser is pointed at its gateway with Playwright MCP's --allowed-origins; that keeps it on the gateway in practice but is not a security boundary (the apps on :8100 are still reachable from the machine), so the guarantee rests on the worker only being given the gateway URL.
- 2026-10-07: requests the browser makes by itself (favicon, static files) bypass the write gate's bookkeeping, so they cannot count as Ava's "search" after an uncertain write.
- 2026-10-08: retain the ADK + Playwright MCP runtime and existing model configuration; the older no-framework decision was superseded by the proven WS3 spike, not reopened for UI work.
- 2026-10-08: use shared Jinja shell/CSS and local Source Sans 3, with restrained app accents and actual PDF beside grouped Books fields; preserve native controls, business routes and audit/stale-value semantics.
- 2026-10-08: capture the worker's isolated browser using MCP's public screenshot tool and serialize action/capture callbacks; hide that tool from model requests, bound storage/time and authorize serving only from matching run observations.
- 2026-10-08: exclude fonts, PDF previews, downloads and status polling from gateway reconciliation bookkeeping; viewer traffic cannot satisfy an uncertain write's required search.
- 2026-10-08: validate company identity before launching a single console-managed worker; answers are asynchronous, exclusive and run/question-specific. Preserve incomplete logs when the console stops.
- 2026-10-08: keep application acknowledgements, self-reported plan/goal progress, fresh checks and independent grades distinct; missing WS4 context induction and WS5 verifier/eval remain exposed rather than replaced with canned behavior.
- 2026-10-08: use temporary companies and explicitly labelled scripted ADK/MCP runs for local validation, preserving the active company and prior runs; no paid model calls were needed. Updated invoice generation never overwrites existing PDFs.

- 2026-10-08: refine the shared shell to neutral surfaces, system typography, compact navigation and table-led task/app views; replace the always-visible task composer with a focused native dialog.
- 2026-10-08: replay real saved captures with evidence reconstructed at each observation; hide future outcomes, grades and answer controls while inspecting history.
- 2026-10-08: bound goal preparation to 120 seconds by default and log fallback attempts immediately; distinguish external model unavailability from browser work without changing provider configuration.

- 2026-10-08: use the Vertex AI endpoint for the supplied billed Cloud API key after the Developer API returned API_KEY_SERVICE_BLOCKED; a live structured goal succeeded with the same configured model.

- 2026-10-08: supersede model API-key authentication with Vertex AI + ADC at the existing make_model boundary; centralize project/location, explicitly pass discovered credentials and bind quota to the configured project. Preserve ADK prompts, model IDs, fallbacks, retries and timeouts.
- 2026-10-08: after the run that spent 635k tokens without saving, the worker is reminded every turn (by code, in the system instruction) of its budget, plan, pages read and remembered facts, and gets non-blocking nudges when it reopens a page or reads without progress; forms are filled in one browser_fill_form call.
- 2026-10-08: the company apps leave out links to the product console when the request comes from Ava's gateway (X-Precedent-Agent), and /work-status is not served to her; the console describes the worker and must not steer it.
- 2026-10-08: the action agent runs on gemini-3.6-flash with LOW thinking: on a realistic worker turn it took 2.6 s median against 8.5 s for gemini-3.8-flash (which also timed out under load), and chose the better next action; 3.7 and 3.8 remain fallbacks. The goal contract and the company context run in parallel before the first action.
- 2026-10-08: company context is gathered with plain GET requests through the worker's gateway (the same web pages a browser would load), not by browsing step by step, because a model-driven tour of 20+ pages costs minutes and tokens without adding judgment; the judgment is the one reasoning call and the code validation after it.
- 2026-10-08: Drive shows a document's extracted text open by default, under the visual preview, so that neither people nor Ava have to expand it to read the file.
- 2026-10-08: thinking is adaptive, decided by code per turn: HIGH only when writing the plan or after a save with an unknown result (HIGH measured 17.3 s per turn on gemini-3.6-flash, about 3x slower), MEDIUM on forms, decisions, refusals, failures and nudges (5.3 s, about the cost of LOW), LOW for reading. The goal contract and the single company-context call think at MEDIUM (at HIGH the context call timed out after 120 s on an 8k-token prompt).
