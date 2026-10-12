# Real visible-browser demo — 8 October 2026

The autonomous invoice task completed in the actual visible browser. The
independent evaluation passed all 13 checks. No scripted model or manual company
edits were used. Existing records in the earlier company were preserved.

- Task: Enter the latest Figma invoice and route it for approval.
- Run: `20261008-153153-1fed`.
- [Task and evaluation](http://localhost:8007/runs/20261008-153153-1fed).
- [Completed bill](http://localhost:8110/books/bills/INV-921).
- [Result data](../output/native-browser-demo/result.json).
- Fresh company: `/tmp/precedent-native-demo-20261008/7`, seed 7.
- Configured model: `gemini-3.6-flash`, Vertex AI with ADC.
- Duration: 145.7 seconds; 26 worker tool steps; 276,834 counted tokens.
- No model-capacity, authentication or execution error was recorded. USD cost
  is unavailable; these token counts are not a billing statement.

Ava read the source invoice and company rules, checked for a duplicate, recorded
her accounting/routing decisions, saved bill INV-921 and requested approval.
The final invoice is FIG-1842 for INR 112,000, due 21 October 2026, with its source
PDF attached, assigned to account 1400 Prepaid expenses and Ana Pereira.

The independent checks verified exactly one bill, vendor, amount, currency,
due date, account, approver, bill status, attachment ID, approval status and
attachment hash, plus no bank changes and no unrelated bill creation.

The worker independently checked amount, approval status and duplication on
fresh pages. Its overall result remains `unknown` because two broader safeguards
could not be mapped to supported checks. This is distinct from the independent
evaluation's `pass`; neither result has been overwritten. The original receipt
contained obsolete text saying verification is unimplemented. Receipt
generation now reports actual check coverage and unresolved conditions. A
correction note and corrected receipt were appended to this run; original
events were preserved, and the original receipt file was archived under
`output/native-browser-demo/original-receipt.md`. Actions, checks, finish data
and independent grade remain unchanged.

## Demo presentation fixes

Chromium now opens directly on the company overview through Ava's gateway while
goal/context preparation runs. Its caption names that preparation state, so
the audience does not wait on `about:blank`.

The Ava arrow, mouse listeners and focus highlight were removed. Human pointer
movement and focus no longer imply an agent action. The remaining caption is
driven by worker tool callbacks; it cannot intercept input or appear in Ava's
accessibility snapshots. Human input can still interact with the real browser:
during recording, use the browser as an observation window while Ava works.

Real-browser tests verified the starting URL, unchanged caption state after
mouse/focus activity, continuous frames and cleanup. Together with worker,
console, receipt and scripted-run regressions, 36 focused tests passed. Lint,
JavaScript syntax and diff checks passed.

The visible browser closes with worker cleanup after completion. The bill and
task evidence stay available at the links above. The original demo company
database's before/after content hashes match.

![Actual browser during preparation](../output/native-browser-demo/preparing.jpg)

![Actual browser after approval request](../output/native-browser-demo/approval-requested.jpg)
