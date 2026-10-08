# Delivered workspace redesign — 8 October 2026

## Result and scope

Mail, Books, Drive and Chat now share a compact neutral application shell, system sans-serif typography, company identity, selected navigation, native controls and visible keyboard focus. The company entry identifies Ava and reads the real assignment state from the console. Books provides grouped invoice forms, protected amounts/dates/IDs, readable history and an actual supporting-document preview. Drive offers actual PDF rendering, extracted text, download and secondary file details. Chat retains the seeded colleague messages and posting semantics.

The new operator console launches the existing ADK worker, supports one active run, validates the connected company's seed, reconstructs retained events on reload, and shows the actual isolated MCP browser. It presents saved captures, decisions and source links, self-reported plan progress, application acknowledgements, goal checks, questions and separate independent grades. No invented typing, cursor, learned precedents or completion percentages appear.

The initial inspection found a missing console, `screenshot=None`, and missing WS4 context induction and WS5 worker verification/evaluation. Earlier Gemini interruptions were capacity errors. The ADK runtime and model selections remain intact; authentication now uses Vertex AI + ADC as described in [Cloud authentication](google_cloud_auth.md). Context induction, a fresh worker verifier, eval orchestration and a meaningful baseline comparison remain substantial unfinished work. A completion claim alone remains unknown.

## Launch and entries

From `precedent`, use two terminals with the existing generated company:

```sh
UV_CACHE_DIR=/tmp/precedent-uv-cache PRECEDENT_PDFTOPPM=/absolute/path/to/pdftoppm uv run precedent apps --seed 7 --port 8101
```

```sh
UV_CACHE_DIR=/tmp/precedent-uv-cache PRECEDENT_APPS_URL=http://localhost:8101 uv run precedent console --port 8000
```

These commands do not regenerate company data. The delivered preview uses 8101 and 8000; the disposable demo company uses 8103.

- [Company workspace](http://localhost:8101/)
- [Ava's task inbox](http://localhost:8000/)
- [Scripted browser replay](http://localhost:8000/runs/scripted-20261007-213033-ed38)
- [Disposable routed bill](http://localhost:8103/books/bills/INV-921)
- [Disposable invoice preview](http://localhost:8103/drive/f/f-0004)

The last two URLs require the disposable server already running on 8103; the persisted replay still works without it, although source links then cannot resolve. To restart that preserved disposable company:

```sh
UV_CACHE_DIR=/tmp/precedent-uv-cache PRECEDENT_PDFTOPPM=/absolute/path/to/pdftoppm uv run python -c 'from dotenv import load_dotenv; load_dotenv(); from pathlib import Path; import uvicorn; from precedent.apps.server import create_app; uvicorn.run(create_app(7, Path("/tmp/precedent-v2-demo")), host="127.0.0.1", port=8103)'
```

PDF preview uses Poppler's `pdftoppm` on PATH, or `PRECEDENT_PDFTOPPM=/absolute/path/to/pdftoppm`. This desktop preview was launched with the bundled executable at `/absolute/path/to/pdftoppm`. If unavailable, the document shows extracted text and download instead. Adding that environment variable to the apps/disposable commands reproduces visual preview on this machine. Preview images are cached outside the world and keyed by the actual PDF bytes.

Starting a task invokes the configured model and can consume quota. No new live model run was started by the implementation work. The user-started Sigma task (`20261007-210338-0cf0`) ended after approximately 171 seconds with Gemini 503 capacity errors before producing a goal or browser action. The historical run used the prior authentication configuration. A later billed Cloud-key validation is recorded in `docs/cloud_key_validation.md`; see that report for live results. No credentials are exposed in the console.

## Validation and evidence

`UV_CACHE_DIR=/tmp/precedent-uv-cache make test`: **133 passed**. `UV_CACHE_DIR=/tmp/precedent-uv-cache make lint`: **passed**. ADK emits existing experimental/deprecation warnings. Tests include actual scripted ADK + MCP execution, concurrent tool/action capture association, bounded capture failure, shutdown/reaping, event reconstruction/reconnect, safe run/capture serving, origin checks, seed mismatch, run-specific answers, actual generated PDFs, static-request reconciliation exclusions and all original accounting/stale-write safeguards. Accessibility fixtures were refreshed through real MCP snapshots without relaxing compaction assertions.

`scripts/validate_workspace.py` drove real Playwright MCP against a generated company under `/tmp/precedent-v2-demo`, through the existing gateway and decision guard. It searched, entered one bill, requested approval and navigated back to read the pending state, saving **22 real captures**. Its choices are explicit seed-7 fixture inputs, not model reasoning or learned context. The receipt is **unknown** because the worker verifier is missing. No independent grade was produced for this scripted run. Existing runs and active company files were preserved.

Current rendered evidence lives in [`output/workspace-v2`](../output/workspace-v2/). The machine-readable [review](../output/workspace-v2/review.json) records **92 responsive screens** across 23 routes at 1440×900, 1280×800, 840×900 and 671×823. It covers all company apps, task inbox, actual failed and scripted runs, empty results, and clearly labelled temporary state fixtures. No page-level overflow, visible broken images or JavaScript errors occurred. Tables and narrow browser panels intentionally scroll internally. Checks exercised task search/filtering, modal autofocus and Escape, inline submission failure with input preservation, replay play/pause, historical evidence, expansion, human answers, invalid bill input, advanced filters and keyboard skip navigation. Temporary fixtures are not successful agent runs.

| Surface | Current evidence |
|---|---|
| Task inbox | [Tasks](../output/workspace-v2/console-1440.png), [new task](../output/workspace-v2/new-task-1440.png) |
| Operator | [Recorded workflow](../output/workspace-v2/run-1440.png), [expanded browser](../output/workspace-v2/run-expanded-1440.png) |
| Invoice entry | [Form with source document](../output/workspace-v2/form-1440.png) |
| Company apps | [Mail](../output/workspace-v2/mail-1440.png), [Books](../output/workspace-v2/books-1440.png), [Drive](../output/workspace-v2/drive-1440.png), [Chat](../output/workspace-v2/chat-1440.png) |
| Capacity failure | [Narrow layout](../output/workspace-v2/failed-671.png) |

The previous iteration and original before screenshots remain in `output/workspace-redesign`; its 100-screen review is historical. The v2 directory includes before-console and before-run images for comparison. Redesigned invoice and routed-bill screenshots use the disposable company. Generator improvements apply to newly generated worlds; existing PDFs retain their original bytes and business content.

## Interaction and wait improvements

The task inbox is a searchable list with real run-type filters and a focused New task dialog. Company apps use consistent navigation, compact tables and subtle separators. Books places attachment selection first and advanced filters behind an expandable control. The operator prioritizes the actual browser, with concise decision evidence and expandable supporting detail.

“Play recorded views” advances through actual captures every 2.5 seconds and can be paused. The selected capture reconstructs evidence only through that observation; future decisions, outcomes and grades do not appear early. Playback is explicitly recorded, and the demonstration is explicitly scripted.

Model failures and retries are logged as they happen. Goal preparation has a configurable 120-second deadline (`PRECEDENT_GOAL_TIMEOUT_SECONDS`), capped by the remaining run budget. Capacity failures and timeout messages explain whether browser work began. This fixes silent waiting. The later Cloud-key run is historical evidence; current model authentication is strictly Vertex AI + ADC. Configure `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`, and restart the console after changing `.env`. See `docs/google_cloud_auth.md` for current setup.

## Accurate Act 1 walkthrough

1. Open the company workspace, then the task inbox. Explain Ava's accounts-payable role and the connected seed.
2. Open the scripted replay to demonstrate the delivered observation mechanism without spending model quota. Click **Play recorded views**, then pause or select an early saved view to see the actual invoice and company records opened through MCP.
3. Expand the recorded draft-entry view: the invoice is beside native accounting fields. The fixture uses annual prepaid treatment. Explain that the current generic worker can read this evidence, but ranked context induction has not been implemented.
4. Expand the decision evidence before routing. The script records fixture authority explicitly; it does not prove that an AI reconciled the stale SOP with current approval authority.
5. Select the latest view: the application shows **pending approval**, not approved or paid. Separate the confirmed application change and browser read-back from the unknown fresh-verification receipt. Independent grading has its own panel.
6. For a live demonstration when model service is available, enter the actual natural-language assignment and observe the model's real decisions. Until WS4/WS5 are implemented and tested, do not present this as the completed learning-and-verification story.

## Implementation choices and limits

The shared visual system follows the inspected Linear, Ramp and Magentic-UI application compositions, with mail/channel refinements from the other supplied references. It uses the existing Jinja/FastAPI stack and focused JavaScript. No framework migration or unsupported business controls were added.

Same-session screenshots use the installed MCP tool's public `get_tools()` / `run_async()` API, with the screenshot tool hidden from the model. Calls are serialized across action and capture; captures are bounded to six seconds, 200 images, 80 MB per run and 12 MB per image. Capture failures do not fail business execution, and screenshots do not count as business actions or enter model requests. Serving requires a matching run observation and safe PNG filename.

Run-specific question answers use exclusive answer files, are rejected for inactive/stale/already-answered questions, and are polled asynchronously. There is no live-worker pause, takeover, retry, reset or comparison control; replay playback can be paused. A console restart interrupts its managed worker and keeps the log as an incomplete replay; automatic resumable session recovery is not implemented. Browser observations are discrete saved views, not streaming video.

Company metadata is public manifest/template data; fresh manifests contain company metadata. A second seed is tested. No additional company template was introduced. No worker reads hidden truth or SQLite. Static/font/preview/download/status requests cannot unlock the search requirement after an uncertain write. Existing routes, IDs, native labels, `was__` inputs, audits, pagination and scenario isolation are retained.
