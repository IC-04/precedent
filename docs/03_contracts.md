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
