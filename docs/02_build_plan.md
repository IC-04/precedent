# Build plan

Each day ends with something that runs. If a day slips, cut from the bottom of that day; never skip the gate.

## Start here: the first hour today

1. Open a terminal in the repo: `make setup`, then configure the billed Cloud project and ADC as described in [Google Cloud authentication](google_cloud_auth.md). `make test` should pass without Cloud credentials; model runs require ADC.
2. Start Claude Code in the repo root (`claude`). It reads `CLAUDE.md` automatically.
3. Session A: `/ws WS1` (world generator). When `contracts.py` needs no change, open a second terminal.
4. Session B: `/ws WS2` (apps). It can write against the schema before WS1 finishes.
5. When the apps serve seed 7, Session C: `/ws WS3` (worker loop).
6. Before each commit, ask Claude Code to "use the reviewer agent on this change". Use `/status` whenever you lose track.

## Day 1: 7 October. Gate: Act 1 runs end to end, even if it is naive

| Order | Workstream | Output | Brief |
|---|---|---|---|
| 1 | Setup (30 min) | Repo installs; `make test` is green; API key works; Playwright runs | this repo |
| 2 | WS1 World | Northwind template; deterministic generator; `world.db`, `hidden.json`, PDFs for seed 7 | `briefs/WS1_world.md` |
| 3 | WS2 Apps | Mail, Books and Drive pages and writes on :8100, with the audit log | `briefs/WS2_apps.md` |
| 4 | WS3 Worker loop | Browser snapshot tools; the act-and-observe loop; goal contract; events log | `briefs/WS3_worker_loop.md` |
| 5 | WS5 Grader (minimal) | `make grade` checks Act 1 against `hidden.json` | `briefs/WS5_verify_eval.md` (part A) |

WS1 and WS2 can run in parallel Claude Code sessions once `contracts.py` is fixed (it is). WS3 can start on any HTML page and point at the real apps when they are up.

**End-of-day check:** `make world SEED=7 && make apps &` then `make run TASK="Enter the latest Figma invoice and route it for approval."` writes a bill. `make grade` prints a result, pass or fail.

## Day 2: 8 October. Gate: a submittable demo

| Order | Workstream | Output |
|---|---|---|
| 1 | WS4 Context | Act 0: precedents with authority ranking; Act 1 now picks 1400 and Ana |
| 2 | WS5 Verifier and receipt | Goal contract compiled into checks, read fresh through the browser; receipt |
| 3 | WS6 Console | Main screen: tasks, live screenshot, decision record, goal contract, plan, receipt |
| 4 | WS3 + WS5 | Ghost-run baseline (`--worker baseline`) on the same seed |
| 5 | WS7 Submission | README draft, architecture note, first demo recording |

**End-of-day check:** a 3-minute recording of Act 0, Act 1 and the ghost run, with the receipt on screen. If the deadline really is 9 October at 5:30 PM, we polish and submit tomorrow morning.

## Day 3: 9 October. Gate: reality (Act 2) and generalisation (Act 5)

- Act 2: the Zenith half-done setup; crash and restart through a scenario hook; the colleague's edit; uncertain-write reconciliation.
- Globex template. The same request gives different correct behaviour.
- Evaluation harness: seeds × workers × repeats, producing a results table in Markdown.

## Days 4–5: 10–11 October. Hardening

- Acts 3 and 4 (Chat question, PDF injection).
- More seeds, held-out seeds, repeated runs, cost table.
- Failure injection (relabelled field, slow page, dropped response).
- Final video, README, limitations, next steps.

## 12 October. Buffer and submit. No new features.

## Rules for every session

- Start each Claude Code session by pasting a brief. Finish it by running `make test` and committing.
- Commit small and often, with conventional messages (`feat(world): …`).
- If a workstream changes a contract, say so in its commit message and update `docs/03_contracts.md`.
- Keep a running list of decisions in `docs/decisions_log.md`, one line each. The README's design-decisions section is built from it.
