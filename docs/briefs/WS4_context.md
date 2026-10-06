# WS4: Company context (Act 0): precedents ranked by authority

> Paste this into a fresh Claude Code session in the repo root.

## Goal

Write `src/precedent/worker/context.py`. Before a task, the worker reads the company, through the browser like everything else, and produces a small set of cited `Precedent` objects for that kind of task. This is the product's differentiator. A precedent with no citation is a bug.

## Read first

`docs/01_architecture.md` (D6 stage 2, D10), `contracts.py` (`Precedent`, `SourceRef`, `Authority`), and the vision PDF pages for Act 0 (the CFO email, the SOP and the history example).

## Design

Three phases, and the code keeps them separate:

1. **Gather (browser, read only).** For the task family (`enter_invoice`, `vendor_setup`, …):
   - Drive: open policies and SOPs and extract the relevant clauses with their section numbers and effective dates.
   - Mail: search for instructions about approvals, accounts, thresholds and the SOP ("approval", "from <date>", "SOP", "route to").
   - Books history: pull the report filtered by the relevant account or approver over the last 6 to 12 months.
   - Store the raw evidence in `runs/<id>/evidence/*.json`, each item carrying the ref it came from.
2. **Reason (LLM, strong model).** Input: the evidence items and an authority rubric:
   - policy and authoritative instruction > current state > precedent > inference > external input
   - a later authoritative instruction supersedes an older policy for the same rule from its effective date
   - history confirms or questions a rule but never creates one when an authoritative source exists
   - split history with no governing source → `unresolved`
   - authority and practice disagree → `conflict`; follow the authority and flag it
   Output: a list of `Precedent`, each citing evidence refs.
3. **Validate (code, not LLM).** Drop or downgrade any precedent whose cited refs were not seen in phase 1. Recompute support counts such as "8 of 9" from the gathered rows, never from model text. Emit one `precedent` event per item.

Cache the result per (seed, task family) in `runs/_context_cache/`, and report its cost separately.

## Baseline mode (the ghost run)

`build_context(mode="baseline")` returns the policy and SOP text, with no ranking, no history and no validation. Same token budget. This is what makes the ghost run fair.

## Acceptance (seed 7)

- Three precedents are produced:
  - "Design spend above ₹50,000 → Ana Pereira": `usable`; governing is the CFO email of 2 July, effective 14 July; support "8 of 9"; exception INV-894; flag "SOP §3.2 stale".
  - "Annual software plans → 1400 Prepaid": `usable`; governing is AP-Policy-2025 §4; support "2 of 2"; monthly plans go to 6120.
  - "Linear licences: 6120 or 6340": `unresolved`; split 5 to 4.
- Act 1 with context now picks 1400 and Ana. Grader: pass.
- The ghost run on the same seed is recorded, whatever its result.
- Change seed 7 to seed 8 and the precedents change along with the generated rules. Nothing is hard-coded to Northwind names.
