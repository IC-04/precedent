# WS2: Company apps (Mail, Books, Drive, Chat)

> Paste this into a fresh Claude Code session in the repo root.

## Goal

Write `src/precedent/apps/`: one FastAPI server on port 8100 that serves four small but real web applications over `worlds/<seed>/world.db`. A browser agent will operate them the way an employee would, so they must behave like real software. Real forms, real redirects and real search; no hidden shortcuts.

## Read first

`CLAUDE.md`, `docs/03_contracts.md` §2–3, `src/precedent/world/db.py` (from WS1; if it does not exist yet, write against the schema and call `db.write()` for every write).

## Deliverables

1. `apps/server.py`: `create_app(seed)`, mounting `/mail`, `/books`, `/drive` and `/chat`. Start it with `precedent apps --seed 7`.
2. Jinja templates per app, each with its own header, colour and layout so they look like different products. Keep them plain and readable. No JS frameworks; a few lines of vanilla JS at most.
3. **Mail:** inbox list (sender, subject, date), `?q=` search over subject, body and sender, a message page with attachments that link to Drive download.
4. **Books:**
   - vendors: list, search, view, edit, create, retire
   - bills: list with filters (vendor, account, approver, date range), view, create, edit while draft, and **Request approval** (choose an approver from employees)
   - a history report: bills by account, approver and date
   - a confirmation banner after each write, shown after a redirect
5. **Drive:** folders, file list, a file viewer that shows the PDF's extracted text with a download link.
6. **Chat:** channel list, channel view, post a message.
7. Scenario hooks under `/__scenario/` that need the `X-Scenario-Token` header, used by WS5 and the demo:
   - `POST /__scenario/edit` applies a colleague's edit to a record and writes it to the audit log with that colleague as the actor
   - `POST /__scenario/drop-next-response?path=` makes the next POST to that path commit its write and then return a 502
   - `POST /__scenario/relabel?field=due_date&label=Payment due` changes one form label
8. Tests with FastAPI `TestClient` for each write path, including the audit log entries.

## Requirements that matter for the agent

- Every input has a `<label for>`. Every button has visible text. Use stable `name` attributes.
- Bill IDs are created by the server (`INV-921`, …). The invoice number is a separate field. Duplicate invoice numbers are **allowed** (real systems often allow them); the worker has to prevent them.
- Amounts are entered as human text (`1,12,000` or `112000`) and parsed on the server.
- Lists paginate at 25 rows, with a visible "next" link. Search is case-insensitive.
- Never expose `hidden.json` or anything derived from it.

## Acceptance

- `uv run precedent apps --seed 7`, then open `http://localhost:8100/books/bills?q=FIG` and you can create a bill for FIG-1842 by hand, request approval from Ana, and see it in the audit log.
- `uv run pytest tests/test_apps.py` passes.
- The drop-response hook leaves the bill committed even though the browser sees an error. Act 2 depends on this.

## Out of scope

Authentication (assume a single logged-in user, "Ava (AP)"), email sending, file upload (optional).
