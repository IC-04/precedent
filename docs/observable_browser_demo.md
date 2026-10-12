# Observable autonomous browser demo

The original CentrAlign internship JD governs the assignment. The user explicitly
superseded earlier kickoff constraints. The JD permits a focused browser prototype;
this implementation provides real autonomous execution in company applications.
It uses accessibility snapshots to understand pages, rather than pixel perception.

## Try the live execution

An untouched seed-7 company is running at http://localhost:8114/. The console at
http://localhost:8007/ is configured to use it with a visible browser.

1. Open the task inbox, click **New task**, and enter
   **Enter the latest Figma invoice and route it for approval.**
2. Click **Start task**, then switch to **Google Chrome for Testing**.
3. Watch preparation on the company overview, followed by navigation, visible
   inputs, scrolling, saving and the approval request. Ava's purple pointer is
   independent of the human mouse. Observe without clicking into her form.
4. Return to the task screen for decisions, checks and the evidence receipt.

The browser window closes when execution and verification finish. The task screen
then explicitly shows recorded evidence. Preparation and model response times
depend on the model service. The initial page is the company overview, not blank.
The untouched company is for one fresh invoice-entry demonstration; repeating the
task after completion should adopt the existing bill rather than create another.

## Validated result

- Real Gemini/Vertex ADC run: `20261008-162241-da16`.
- [Completed task](http://localhost:8007/runs/20261008-162241-da16).
- [Saved bill](http://localhost:8113/books/bills/INV-921).
- Separate validation company: `/tmp/precedent-visible-execution-r3-20261008/7`.
- Independent grade: **13/13 pass**.
- Duration: **199.2 seconds**; **38 worker tool steps**; **460,882 counted tokens**.
- Browser actions: 8 clicks, 5 selections, 4 field entries and 1 initial navigation.
- No browser input failure, execution error or human question in this final run.
- No scripted model, manual business-record edits or hidden answers supplied to Ava.

Ava entered FIG-1842 for INR 112,000, due 21 October 2026, attached its actual PDF,
selected account 1400 Prepaid expenses, and requested approval from Ana Pereira.
The independent grader checked invoice uniqueness, vendor, amount, currency, due
date, account, approver, bill status, attachment identity/hash, approval status,
and the absence of bank changes or unrelated bills.

Two earlier validation attempts saved the bill but failed to finish approval.
Their logs, records and failed grades are retained. They exposed missing fresh
observations, navigation timing, history references and decision-state reminders;
those paths were corrected before the final successful execution.

## How the visible execution works

The model chooses actions, current element refs and values through Playwright MCP.
The fixed executor contains no accounting workflow or company-specific answers.
It resolves the selected control in the same browser session, scrolls into view,
moves the actual browser mouse and the Ava pointer together, clicks, and enters
ordinary text with character-by-character keyboard events. The model receives a
fresh snapshot after each input. Native dropdowns and segmented date controls use
Playwright's format-aware input after the pointer reaches the control.

Only executor commands move Ava's arrow or trigger its click pulse. Human mouse
and focus events have no listeners that can move it. Captions come from real tool
callbacks. Live native tasks hide image-viewer and replay controls entirely;
recorded evidence remains available after the session ends.

Writes still pass through the existing decision gate. Saving a bill and requesting
approval are separate submissions, each requiring a decision with sources. The
worker sees its current write permission and a reminder when a decision is consumed.
The isolated browser disables history caching to avoid restored stale frame refs.

Company-context preparation and final checking also use fresh HTTP reads through
the gateway. Those stages are announced in the browser; they are not presented as
visible mouse work. The agent does not control other desktop applications.

## Verification limits and correction

The final worker receipt reports **6/9 checks passing**, with **3 unknown**, separately
from the independent **13/13 pass**. The unresolved checks cover bundled date fields,
a vendor-baseline check with an invalid model-selected identifier, and a broad
no-unrelated-changes condition unsupported by the current check primitives.

The original worker result falsely failed its amount check because it compared
`112000 INR` with `INR 1,12,000.00` as text. The general amount comparator now accepts
currency before or after the number while retaining sign and currency mismatch
checks. The amount was reread through a new read-only gateway and a correction was
appended. Original check, finish event and receipt are preserved; the current
receipt uses the latest check per condition and remains unknown. Corrected evidence
does not cause a closed run to be resumed. Independent grading does not promote
unknown worker checks to verified.

The previous company database's before/after hashes match. USD cost is unavailable;
token counts are not a billing statement.

## Evidence and validation

- [Result data and all three grades](../output/visible-execution-demo/result.json).
- [Original worker receipt](../output/visible-execution-demo/final-original-receipt.md).
- [Actual browser during entry](../output/visible-execution-demo/final-form.png).
- [Actual browser after approval](../output/visible-execution-demo/final-approval.png).

The full suite checked 196 tests: 195 passed on its first run; one SDK-boundary
test caught the adapter being placed outside the established runner boundary.
The adapter was moved into that boundary, and all seven relevant guardrail and
real-browser tests passed on rerun. Visible and headless tests cover character
arrival, pointer separation, native controls, scrolling, navigation, and return
from a refused submission. Verifier, receipt, closed-run and grading-separation
tests pass. Repository lint, JavaScript syntax and diff checks pass.
