# WS5: Verifier, receipt, grader and evaluation

> Paste this into a fresh Claude Code session in the repo root. Do part A on day 1 and parts B and C on days 2–3.

## Read first

`docs/01_architecture.md` (D8–D10), `contracts.py` (`CheckResult`, `Receipt`, `HiddenTruth`), `docs/03_contracts.md`.

## Part A: Grader (outside the worker) — day 1

`src/precedent/grader/grade.py`: `grade(seed, task_id, run_id) -> GradeResult`.
- It reads `world.db` and `hidden.json` directly.
- It checks every `expected` and `must_not` item. It uses `audit_log` to detect duplicates, bank-detail changes and overwrites of colleagues' edits, comparing the actor with the before/after values.
- Output: pass or fail per item, plus overall. `make grade SEED=7 TASK_ID=T1_figma RUN=<id>`.
- Tests: hand-build a correct world state and an incorrect one, and assert that the grader tells them apart.

## Part B: Verifier and receipt (inside the worker) — day 2

`src/precedent/worker/verify.py`.
- **Check primitives**, run through the *browser*, never the DB:
  - `count_bills(invoice_no)`
  - `bill_field(bill_id, field)`
  - `approval_status(bill_id)`
  - `vendor_field(vendor_id, field)`
  - `attachment_name(bill_id)`
  - `field_unchanged(entity, id, field, baseline_value)` (baseline values are captured at goal time)
- **Compiling:** a strong-model call maps each goal-contract condition to one or more primitives with arguments. A condition that cannot be mapped becomes `unknown`, never `pass`.
- **Run** the primitives on freshly loaded pages and emit `check` events.
- **Receipt:**
  - outcome is `pass` only if every check passes; `fail` if any fails; `blocked` if the runner stopped on a business contradiction or missing authority; `unknown` if any check is unknown or a write is unresolved
  - fill `summary`, `pending`, `decisions` (from the decision records), `left_unchanged` (from the must-not checks), `sources` and `cost`
  - render `runs/<id>/receipt.md` and emit a `receipt` event

## Part C: Evaluation harness — day 3

`src/precedent/eval/run.py`: `precedent eval --template northwind --seeds 7,8,9,11 --tasks T1_figma,T2_zenith --workers precedent,baseline --repeats 3`.
- For each combination: generate a fresh world, start the apps, run the worker, grade, and collect cost and time.
- Output `eval/results/<date>.csv` and a Markdown table. The table shows verified success (pass on all k repeats), wrong silent writes (graded fail but the receipt says pass), duplicate side effects, context value (Precedent minus baseline), and tokens, USD and seconds per verified outcome.
- Keep every run directory. Failures are listed, not hidden.
- **Do not hard-code targets.** The only fixed expectations are zero wrong silent writes and zero duplicates.

## Acceptance

- After an Act 1 run, `receipt.md` reads like the vision's receipt and agrees with the grader.
- Deliberately break the account (set 6120): the verifier reports a check fail *and* the grader fails the run.
- The eval command produces a table over at least 2 seeds × 2 workers by day 3.
