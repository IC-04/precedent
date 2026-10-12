# Immersive workspace milestone

The first milestone makes the existing invoice workflow understandable from assignment through evidence. The visual direction is a warm, quiet work surface with restrained violet accents for Ava, clear typography, and progressive disclosure. Linear and Raycast informed hierarchy and interaction density; their branding and layouts were not copied.

## Try the demo

From the repository root, after the existing setup and Vertex ADC authentication:

```sh
.venv/bin/python scripts/demo.py --port 8009 --apps-port 8116
```

The launcher creates a new disposable seed-7 company in a temporary directory and prints its location. Existing company databases and retained runs are untouched. It starts both the company apps and a headed console. Ports must be free; use different ports if another instance is running. Stop the launcher with Ctrl-C. The temporary company is retained, although the operating system may eventually remove temporary files.

1. Open http://localhost:8009/.
2. Choose **Enter & route an invoice**, then **Assign to Ava**.
3. Preparation reports the actual goal and company-context events. The initial browser page is the company overview.
4. Choose **Bring Ava’s browser forward**. Watch the actual Chrome for Testing window; keep the task page beside it for decisions and questions. Avoid editing the company while Ava works.
5. Return to the task page when the browser closes. Inspect the bill, attachment, approval routing, fresh checks and evidence receipt.

**Meet Ava** explains the workflow. Command/Ctrl-K focuses task entry; Command/Ctrl-Enter submits from it. **Focus view** hides the details panel while preserving current activity and human questions. Previous runs are behind **Previous work** and identified as historical. Saved browser images are explicitly labelled still-image evidence and are never the primary live view.

The native session belongs to the worker. Ava's purple pointer is driven by actual worker input, independently of the human pointer. Native viewing is local; this milestone does not embed a remote desktop into the console. The legacy optional image-stream routes remain available for compatibility but are not the recommended demo path.

## Real validation on October 9, 2026 IST

Run: `20261008-215737-5b6a` (run identifiers use UTC).

- Task: Find the latest Figma invoice, enter it into Books and route it for approval.
- Existing configured Gemini model and Vertex ADC; actual ADK / Playwright MCP execution.
- Fresh isolated company: `/tmp/precedent-immersive-20261009/run/7`.
- Duration: **170.4 seconds**, 37 worker steps, no human questions, no execution error.
- Saved record: `INV-921`, invoice `FIG-1842`, INR 112,000, due October 21, 2026, account 1400 Prepaid expenses, attached source PDF, pending approval with Ana Pereira.
- Independent grader: **13/13 passed**.
- Ava's fresh checks: **5/7 passed, 2 unresolved**. Latest-invoice identification lacked a supported check primitive; unchanged vendor details lacked an earlier vendor baseline. Independent grading does not promote those checks to verified.
- Viewing pace accounted for 12.6 seconds. No latency reduction claim is made from this single run; the change publishes the goal as soon as it is ready, separately from context preparation.
- 440,552 input and 5,156 output tokens recorded; monetary cost unavailable.

The completed result is available at http://localhost:8009/runs/20261008-215737-5b6a while the console and the retained company on port 8115 are running. The fresh demo company is on 8116. Links in each result use its original company address, not the current demo company.

Machine-readable evidence: `output/immersive-milestone/result.json`.
Screenshots: `entry-1440.jpg`, `preparing-1280.jpg`, `execution-1280.jpg`, `native-execution.jpg`, and `results-1440.jpg` in that directory. These are documentation screenshots, not a live-view implementation.

## Validation and limits

The full suite passed **199 tests**, including worker write controls, verification, native input, pointer separation, event reconstruction, human answers, and browser lifecycle. Python lint/format and JavaScript syntax checks passed. The workspace was visually inspected at 1440×900 and 1280×800; the 390-pixel layout had no horizontal overflow. The introduction, example selection, submission, native handoff, results and actual saved bill were inspected. Controlled fixtures/tests cover waiting, capacity failure, interrupted sessions, human answers and duplicate-answer rejection; these are not additional autonomous runs.

Goal/context preparation and verification include programmatic reads of company pages. The visible browser is the execution surface, not a claim that every read is performed by clicking. This remains an accessibility-guided browser worker, not a general pixel-based desktop agent. Model latency and availability remain external dependencies. Voice narration, Google/Slack onboarding, calendar, email drafts, additional task families and multi-seed evaluation orchestration are later work. Only this seed and workflow were independently graded in this milestone.


Subsequent evidence review found an additional coverage gap: one condition bundles invoice number, date and amount while its fresh check compares only amount. The original receipt is retained. See [the verification audit](memory_skills_research.md#verification-issue-discovered-in-the-retained-proof); repair is required before treating that entire condition as proven or activating a broad skill.

The user-confirmed submission deadline is October 12, 2026 at 11:59 PM IST.
