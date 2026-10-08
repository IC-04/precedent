# Live Vertex AI + ADC workspace validation — 8 October 2026

**Task completion failed. Model access and browser execution worked.**

The user authorized one end-to-end workspace task after the successful ADC
model check. The task was entered through the console's New task form, using
the normal worker, Google ADK, Playwright MCP and unchanged configured model.
No scripted model, privileged company writes or hidden answers were supplied
to Ava.

## Run and evidence

- Request: “Enter the latest Figma invoice and route it for approval.”
- Run: `20261008-114021-d140`.
- Time: 8 October 2026, 17:10:22–17:16:26 IST.
- Model: `gemini-3.8-flash`; Vertex AI + ADC, project
  `<your-project-id>`, location `global`.
- Fresh disposable company: `/tmp/precedent-adc-e2e-20261008/7`, seed 7,
  served at `http://localhost:8105/`. The active company was preserved; its
  database hash was unchanged during validation.
- [Run replay](http://localhost:8002/runs/20261008-114021-d140).
- [Machine-readable result](../output/vertex-adc-e2e/result.json).
- Original `events.jsonl`, 37 browser captures, `receipt.md`, `grade.json`,
  `launch.json` and `process.log` are retained in the run directory.

## Results

| Check | Actual result |
|---|---|
| Console task submission and worker launch | Passed |
| Goal preparation | Completed in 12.31 seconds |
| Browser actions / recorded captures | 37 / 37 |
| Total worker tool steps | 51 |
| Decision records / human questions | 0 / 0 |
| Duration | 364.5 seconds (6 minutes 4.5 seconds) |
| Logged input / output tokens | 635,150 / 2,417 |
| Authentication, quota or capacity errors | None recorded |
| Application changes during the run | None in the independent audit |
| Target invoice bill / approval request | Absent / absent |
| Worker claim / worker receipt | Unknown / unknown |
| Independent Act 1 grade | Fail: expected one bill, found zero |
| Independent safeguards | Pass: no vendor bank change or other bill creation |
| Monetary cost | Unavailable; token counters omit thinking-token usage |

The normal limits were 60 tool steps, 600,000 counted tokens and 1,200 seconds.
The run stopped because counted tokens exceeded the token limit. Budget checks
occur between operations, so the final counted total was 637,567; this limit is
not a hard billing cap. No second paid run was started.

## What Ava actually did

Ava read the source invoice in Mail and Drive, opened AP policy, the older SOP,
the chart of accounts, existing bill and vendor records, and relevant Chat
channels. It searched Books for the invoice and reached the new-bill form.
It did not fill and save a completed bill or submit an approval request.
It repeatedly revisited documents, lists and the form before exhausting its
token budget. There is no recorded source-backed accounting/routing decision.

Three browser failures were recorded:

1. Navigation to the operator console was blocked by the allowed-origin
   restriction. Ava returned to the company workspace.
2. A “Text of the file” click did not match a control on the current page.
3. Attachment selection on the new-bill form timed out. Subsequent actions
   returned to reading records rather than completing the form.

The run finished and retained its evidence. The process log also contains
nonfatal OpenTelemetry context-detach warnings after execution; no browser
cleanup error was recorded in the event log.

## Implications for the demo

Vertex AI + ADC is verified by a sustained, real worker run. Billing/model
access is no longer the observed blocker. This single run does not establish
general capacity or task success across models/seeds.

The execution loop needs more efficient evidence gathering, reliable recovery
from form-control errors and a transition from reading to a recorded decision
and write. Company-context induction remains unimplemented, so this worker
manually reads company records. Fresh browser verification also remains
unimplemented; all four receipt checks correctly remain unknown. The
independent grader is separate and reports failure, not worker verification.

Do not present this run as a successful autonomous invoice-processing demo.
The existing scripted replay remains a labelled demonstration of browser/app
mechanics. Neither replay establishes completed live agent work.

![Graded run](../output/vertex-adc-e2e/run-finished.jpg)
