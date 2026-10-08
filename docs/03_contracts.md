# Contracts between workstreams

The code version is `src/precedent/contracts.py`. This page explains it and adds the parts that are not Python: the database schema, the URLs and the worker's tools.

## 1. World on disk

```
worlds/<seed>/
  world.db        SQLite; the apps read and write it; the grader reads it
  hidden.json     HiddenTruth; only the grader and eval read it
  files/          blobs for Drive and mail attachments (PDFs)
  manifest.json   template, seed, generated_at, counts
```

## 2. Database schema (SQLite)

| Table | Columns |
|---|---|
| employees | id `E-ana`, name, role, email, manager_id |
| accounts | code `1400`, name, type |
| vendors | id `V-112`, name, legal_name, tax_id, email, phone, address, bank_account, status `active/draft/retired`, created_by, created_at |
| bills | id `INV-921`, vendor_id, invoice_no `FIG-1842`, amount_minor, currency, issue_date, due_date, account_code, approver_id, status `draft/pending_approval/approved/paid`, attachment_file_id, created_by, created_at, notes |
| approvals | id, bill_id, approver_id, status `pending/approved/rejected`, requested_by, requested_at, decided_at |
| mail_messages | id `m-0412`, thread_id, folder, from_name, from_addr, to_addr, subject, body, sent_at |
| mail_attachments | message_id, file_id |
| files | id `f-…`, folder, name, mime, path, uploaded_by, uploaded_at, sha256 |
| chat_channels | id, name |
| chat_messages | id, channel_id, author_id, body, posted_at |
| audit_log | id, ts, actor (`E-…` or `ava`), app, action, entity, entity_id, before_json, after_json |

Money is stored in minor units (paise or cents) as integers. Every write by any actor goes through one helper that appends to `audit_log`. The grader uses it to find duplicates, bank changes and colleagues' edits.

## 3. App URLs (server on :8100)

| App | Pages | Writes (POST) |
|---|---|---|
| Mail | `/mail/` inbox; `/mail/?q=` search; `/mail/m/{id}` message | none (read only for the worker); `/mail/compose` optional |
| Books | `/books/vendors?q=`, `/books/vendors/{id}`, `/books/vendors/{id}/edit`, `/books/vendors/new`; `/books/bills?q=`, `/books/bills/{id}`, `/books/bills/new`; `/books/history?account=&from=` | vendor create/update/retire; bill create/update; `/books/bills/{id}/request-approval` |
| Drive | `/drive/`, `/drive/{folder}`, `/drive/f/{id}` (viewer with extracted text), `/drive/f/{id}/download` | upload (optional) |
| Chat | `/chat/{channel}` | post a message |

Rules for app pages:
- Every input has a visible `<label>`. Buttons carry text. There is no client-side-only state.
- After a successful write, redirect to the record page and show a short confirmation. Never show a confirmation without a redirect.
- The apps never show anything from `hidden.json`.

Scenario hooks, used only by the demo and eval harness, live under `/__scenario/*` and need the `X-Scenario-Token` header. They exist to inject a colleague's edit, delay or drop a response, or relabel a field. The worker's browser never sends that header.

## 4. Worker tools (what the model can call)

| Tool | Arguments | Returns |
|---|---|---|
| `goto` | url | snapshot |
| `click` | ref | snapshot |
| `fill` | ref, text | snapshot |
| `select` | ref, option | snapshot |
| `back` | — | snapshot |
| `download` | ref | local path and extracted text (PDF) |
| `ask_human` | question, options[] | answer (from the console, or scripted in eval) |
| `record_decision` | DecisionRecord | ok |
| `update_plan` | steps[] | ok |
| `finish` | claimed outcome | starts verification |

A snapshot is the URL, the title, and an accessibility-style list of interactive and text elements with refs such as `[e7] textbox "Amount" value=""`. It is kept under 2,500 tokens: long tables are truncated, with a note saying so. A screenshot is saved for every snapshot, but the model does not see it by default.

## 5. Events

See `Event` in `contracts.py`. The required `data` keys by type:

| type | data |
|---|---|
| run_started | request, worker (`precedent` or `baseline`), seed, model |
| goal_contract | GoalContract |
| precedent | Precedent |
| plan / plan_changed | steps[], reason |
| action | tool, args, step_id |
| observation | url, title, summary, screenshot (path) |
| decision_record | DecisionRecord |
| failure | kind (FailureKind), detail, response |
| question / answer | text, options / text, by |
| check | CheckResult |
| receipt | Receipt |
| run_finished | outcome, tokens_in, tokens_out, usd, seconds |

## 6. Implemented workspace/console extensions (8 October 2026)

The worker still exposes installed Playwright MCP `browser_*` tools, rather than the
conceptual `goto/fill` aliases above. Viewer capture calls are internal, bounded and
not model/business actions. `finish` currently records a claim and an **unknown**
receipt; a fresh WS5 browser verifier is not implemented.

- `GET /workspace.json`: public company `name`, `seed`, `template`, `world_id`
  (manifest SHA-256) and document `{id, name}` catalogue. No hidden truth.
- `GET /work-status`: bounded, read-only company entry lookup of the console's
  `GET /workspace-status?seed=`. Scripted validations are excluded from real assignments.
- `GET /drive/f/{id}/preview/{page}.png`: actual PDF raster, pages 1–20 at most;
  cache outside the world, keyed by source bytes; 503 falls back to extracted text.
- Console `POST /runs` accepts `request` and the connected `seed`, validates company
  identity and supports one managed run. Its subprocess receives `PRECEDENT_APPS_URL`,
  `PRECEDENT_RUN_ID`, `PRECEDENT_RUNS_ROOT`, `PRECEDENT_HUMAN_CHANNEL=console`.
- Run state is reconstructed at `/runs/{id}/state` and sent as complete SSE `state`
  events at `/runs/{id}/events`. A reconnect gets a full reconstruction. Discrete
  captures are served only if referenced by that run's own observation.
- `observation` may add `captured_at`, `action_step`, `url_current`, and a relative
  `shots/*.png` screenshot. Missing/failed captures remain nullable. Captures are
  serialized with their associated browser action, never placed in model prompts.
- `question`/`answer` add `question_id`. `POST /runs/{id}/answer` accepts this ID and
  either `choice` or `answer`. Run-specific exclusive files are consumed by an
  asynchronous `FileHuman`; timeouts/system unavailability cannot masquerade as humans.
- `report_plan_step(step_id, status, evidence)` records progress against existing
  plan IDs (`doing/done/skipped`). `report_goal_progress(condition_id, status,
  evidence)` accepts existing goal IDs and only `inferred/written`. Written progress
  requires a recorded application acknowledgement; neither tool verifies a goal.
- `note` kinds include `company`, `app_effect` (HTTP method/path/status),
  `goal_progress`, capture failures and runtime phases. App acknowledgement,
  `check`, completion claim and independently saved `grade.json` remain separate.
- `run_started.validation` labels scripted/model-free fixtures. No canned fixture
  decision is presented as AI learning. Unknown cost is `null`/unavailable.

Automatic static/font/preview/download/status requests do not count as searches
that reconcile an uncertain write. Native business reads and audited writes retain
existing gateway/stale-edit behavior. Console shutdown terminates/reaps its managed
process group and preserves logs; an incomplete run reopens as interrupted replay.

### Replay and model-wait additions

`GET /runs/{id}/state?at=<observation_seq>` reconstructs evidence through a valid
recorded observation, retaining the capture catalogue for navigation. Historical
views cannot accept human answers and do not expose future receipts or independent
grades. Invalid observation selections return 400. Playback uses these states at
2.5-second intervals; this is recorded capture playback, not a live video feed.

`note` also records `model_wait`, immediate model failures and fallback attempts.
Goal preparation is bounded by `PRECEDENT_GOAL_TIMEOUT_SECONDS` (default 120) and
the remaining run budget. Its model usage is included through the existing ADK
callback. Timeout produces a terminal error/unknown receipt; it never fabricates
a goal or browser action. Existing configured fallback models remain unchanged.

### Gemini authentication boundary

`VertexSettings.from_env()` requires `GOOGLE_CLOUD_PROJECT` and defaults
`GOOGLE_CLOUD_LOCATION` to `global`, supported by the configured models.
`make_model` discovers ADC with the Cloud Platform scope and configured quota
project, then supplies explicit credentials to the Gen AI SDK in Vertex mode.
Goal, action and fallback models share this factory. Model API keys are not part
of the contract. Missing configuration/ADC is reported with setup guidance;
Google inference errors retain their original details. `precedent check-model`
uses the same factory for one explicit small inference, without company actions.
