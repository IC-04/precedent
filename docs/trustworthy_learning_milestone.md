# Trustworthy learning for Ava

October 10, 2026. Implementation and real-model validation for the CentrAlign take-home.
The assignment is the source of truth; the deadline is October 12, 11:59 PM IST.

## Reviewer route

The retained demo runs at **http://localhost:8016/**, with company apps at **http://localhost:8122/**.
Open **Ava’s mind** → the successful invoice learning note → inspect its evidence.
Open **Skills** → **Enter and route a vendor invoice** → inspect the sandbox validation
and activation history. The skill is active in this disposable demo company.

The task pages distinguish worker verification from independent grading. **Bring Ava’s
browser forward** opens the actual worker-controlled Chrome window while a task runs.
Saved screenshots are explicitly labelled evidence; they are not presented as live work.
The guide, narration, shared companion and separate agent pointer remain available.

## What changed

- Typed proof coverage rejects missing, duplicate and foreign check mappings. Invoice
  identity, currency/amount, both dates, account, attachment identity, approver, bill status
  and approval-request status are separate claims. Linked checks share evidence only when
  their actual target or source document/vendor matches. Unsupported broader claims stay unknown.
- Expectations need independent captured sources. Invoice attachment checks compare file
  IDs from links; full visible vendor forms establish pre-write baselines. “Latest” is
  bounded to accessible vendor-mail invoice candidates ordered by invoice date.
- Independent assessment now rejects incomplete/foreign/malformed runs, compares aware
  timestamp instants, binds the exact benchmark request and company instance, includes
  issue date, handles ambiguous tied approvals, and checks the full vendor/invoice business key.
- ADK persistent sessions, curated lexical memory and an application-owned provenance
  registry are separate. All recalls and skills are scoped to a stable company instance.
  Restart retains scope; company regeneration changes it.
- Ava’s mind provides task learning, company knowledge, captured sources, search,
  correction/archive and a reviewed skill lifecycle. Observed and uncertain claims remain
  separate. The interface uses the existing companion and supports narrow screens.
- One constrained, instruction-only invoice procedure is drafted from a run with sufficient
  proof, tested by a real worker in an isolated generated company, then explicitly activated.
  It is a reviewed procedure template with run lineage, not arbitrary generated executable code.
  ADK exposes only `load_skill`; the procedure grants no new permissions.

## Trust boundaries

Execution and learning never read company SQLite or hidden evaluator truth. Business actions
use the existing browser gateway and source-backed decision gates. Memory owns separate local
SQLite files. The evaluator alone reads hidden expected outcomes. Its assessment cannot make
an incomplete worker check pass or authorize skill activation.

The installed ADK 2.11 SQLite service's `add_memory` method is not implemented. The adapter
uses public `add_events_to_memory` with deterministic curated entry/version events. Raw execution
transcripts are not indexed. Registry status/version is rechecked after search, so stale indexes
cannot return archived, corrected or superseded entries. Retrieval returns at most five entries.
ADK session history is persisted separately and is not reused as unchecked company knowledge.

Every execution gathers current authority and history. Matching the exact gathered authority
set/content permits reuse of prior rule candidates; code recomputes history support. Changed,
added or missing authority invalidates the cache. Corrections to company knowledge invalidate
related context caches. A memory outage visibly falls back to fresh execution; failure to save
learning is recorded rather than silently represented as success.

The grader reconstructs assessed tables at completion by reversing later audited mutations in
an isolated copy. It freezes the assessment with event digest, run/task/instance binding and
world path. A later reset cannot change a frozen result. A reset before first assessment, missing
required evidence, stopped execution or ambiguous state produces unknown. This relies on the
app's audited write path and immutable generated document blobs; it is not a tamper-proof
external audit system. Exact benchmark requests are required; unsupported task families are
not silently graded as invoice tasks.

## Recorded proof

- Cold invoice: `20261010-095247-523e`. Real Gemini/Vertex + browser. FIG-1842 was entered
  and routed, **13/13 worker conditions passed**, **14/14 independent checks passed**,
  **198.7 seconds**, **0 questions**.
- Successful isolated trial: `20261010-100253-de5e`. ADK skill loaded, **12/12 worker
  conditions passed**, **14/14 independent checks passed**, **177.1 seconds**, **0 questions**.
  Worker condition counts differ because linked atomic claims may share a condition; both
  runs verified the complete required claim set.
- UI activation: skill `6146e8919cad4288aa06eb0ec7806a76`, active revision 6. The demo
  test exercised the explicit review/activate button after inspecting the procedure and trial.
- Real service restart retained instance `5af055cebb084dc0b33b0c8d4fd73685`, **9 registry
  entries**, the active skill and **75 persisted execution-session events**.
  Evidence: `output/learning-milestone/before-restart.json` and `after-restart.json`.
- Different source invoice fixture: FIG-1843, INR 146,000, issue date October 2 and due date
  October 31. `scripts/seed_learning_invoice.py` created only its document/email/attachment,
  plus a separate evaluator benchmark. No bill, approval or worker memory was seeded.

- Different invoice after restart: `20261010-154410-fc9a`. FIG-1843 became INV-922 through
  real browser actions. Four scoped notes recalled, active skill revision 6 actually loaded,
  **12/12 worker conditions passed**, **14/14 independent checks passed**, **0 questions**.

- Repeat/reconciliation: `20261010-154858-e1eb`, **13/13 worker conditions passed**,
  **14/14 independent checks passed**, **137.8 seconds**, **0 questions**. The evaluator
  counted **zero Ava audit writes** during this run and exactly **one FIG-1843 bill**.
  Evidence: `output/learning-milestone/repeat-proof.json`. This is not a fresh-entry benchmark.

Run directories contain the original `events.jsonl`, `receipt.md`, screenshots, source captures,
verification plans, `learning.json`, separate `grade.json` and frozen `assessment-v2.json`.
The benchmark truth and assessment are not ingested into memory.

## Regression evidence and preserved failures

Original historical receipts remain untouched. In particular, `20261009-131448-21dd` had
6 worker passes, 1 failure and **2 unknowns**, separate from its older 13/13 independent grade.
The prior compound-condition false pass is retained as historical evidence, not imported as
validated learning.

During this milestone:

- `20261010-093004-5144` exposed date/status vocabulary failures.
- `20261010-093539-e4ca` reconciled the existing invoice without new writes, but could not
  establish all citation/baseline checks under that runtime version.
- `20261010-094053-c84a` unnecessarily requested clarification despite applicable authority;
  it was interrupted without supplying an answer. Its incomplete log remains ungradable.
- `20261010-094843-21b2` executed correctly with 14/14 independent checks, but worker
  verification retained four unknowns for repeated latest-invoice coverage. No historical
  receipt was rewritten to reflect the subsequent linked-proof fix.
- First skill trial `20261010-095722-becf` failed worker verification despite 14/14 independent
  checks. It exposed bill-status normalization, linked status coverage and an account-list
  citation instead of governing policy. Activation remained blocked. The later fresh sandbox
  trial passed; the failed trial is retained in the skill's revision history.

Tests cover these proof failures, complete/incomplete grader windows, timezone equivalence,
wrong fields, company reset, later edits, actor attribution, tied approvals, exact business
keys, durable recall, cross-company isolation, correction/archive, source change, missing
memory, blocked activation, procedure binding and deactivated/stale skill loading. Tests use
explicit synthetic fixtures or scripted models, never real inference.

## Reproduce

```sh
uv sync
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests
.venv/bin/python scripts/inspect_learning.py --base http://localhost:8016
```

Restart the retained company without regeneration:

```sh
.venv/bin/python scripts/demo.py --port 8016 --apps-port 8122 \
  --world-root output/learning-milestone/demo-worlds --reuse
```

For a new disposable demo, choose a new world path and omit `--reuse`. Perform one
invoice task, review the note, validate and activate the skill, stop the services when idle,
and restart with `--reuse`. Then add the labelled follow-up source once:

```sh
.venv/bin/python scripts/seed_learning_invoice.py YOUR_WORLD_ROOT/7
```

Assign `Enter the latest Figma invoice and route it for approval.` twice, waiting for each
completion. The second assignment must reconcile the existing invoice rather than create
another bill. Independent benchmark names are `T1_figma` and `T1_followup` respectively.

## Limits

This is a local single-user AP prototype, with one active worker per console. Persistent
local scope is not production authentication, external Google/Slack onboarding or a general
skill marketplace. Search is lexical; memory is bounded evidence, not automatic truth.
Natural-language proof planning can still leave unsupported claims unknown. The independent
grader covers explicitly defined benchmarks, not arbitrary requests. Current source reading
and evidence capture remain necessary costs; successful skill reuse does not establish a
general latency improvement. Voice redesign, email/calendar workflows and external connectors
remain later milestones.

## Measured cold/warm comparison

Both measured tasks create and route a fresh annual invoice for the same vendor under the
same policies. The second uses different source values and compares two latest-invoice
candidates. This is one illustrative pair, not a controlled general performance benchmark.
The isolated validation trial is separate and has no viewing pace delay.

| Measurement | Cold FIG-1842 | Skill-assisted FIG-1843 |
| --- | ---: | ---: |
| Total seconds | 198.7 | 229.0 |
| Preparation seconds | 49.652 | 22.686 |
| Context candidate analysis/reuse seconds | 47.846 | 0.002 |
| Memory retrieval seconds | 0.002 | 0.009 |
| Retrieved entries | 0 | 4 |
| Model responses | 40 | 34 |
| Input tokens | 498,545 | 461,378 |
| Output tokens | 5,690 | 4,446 |
| Browser actions | 23 | 25 |
| Model-wait estimate seconds | 150.676 | 176.355 |
| Browser tool + evidence capture seconds | 29.433 | 32.088 |
| Viewing pace seconds | 16.1 | 17.5 |
| Questions | 0 | 0 |

Preparation improved, model response count and tokens decreased, but **total latency regressed
by 30.3 seconds** in this sample. The worker revisited sources and model waits were longer.
There is no demonstrated overall speedup. Candidate reuse timing excludes fresh page gathering
and history-support validation. Model wait is estimated from recorded event intervals and
includes response handling/verification; it is not provider-side latency telemetry. Concurrent
preparation intervals are unioned. Dollar cost remains unavailable.

Reproduce the report with `scripts/learning_metrics.py RUN_ID ...`; retained machine-readable
results are in `output/learning-milestone/metrics.json`. Duplicate reconciliation is a different
workload and is not used as a speed comparison against fresh invoice entry.

## Final checks and visuals

**249 tests passed**, with lint and format checks passing. The full suite results are retained in `output/learning-milestone/test-results.txt`.
The final browser checks cover Memory and Skills at 1440px and 390px, no horizontal overflow,
search, reduced motion, and no browser errors. Explicit UI review, validation and activation
were exercised against real task-derived entries. The run-to-learning link, active skill,
source notebook and verification receipt were also inspected in the browser.

Screenshots in `output/learning-milestone/`:

- `final-learning.png`: the different-invoice task's observed/uncertain learning note.
- `final-skill.png`: active procedure, trial result and revision history.
- `final-run.png`: successful different-invoice execution and fresh checks.
- `memory-390.png` and `skills-390.png`: narrow-layout checks.

All four delivered proof runs (cold, successful sandbox, different invoice, repeat) used the
configured Gemini model through Vertex ADC and real browser actions. They required no user
answers. The preserved failed/interrupted runs above remain part of the record.
