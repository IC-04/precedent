# Milestone checkpoint — October 10, 2026

The original CentrAlign problem statement is the product authority. The deadline is October 12, 2026, 11:59 PM IST, as updated by the owner. Earlier kickoff briefs are historical implementation guidance.

This checkpoint reconciles the conversation with the current repository. It does not implement the next milestone. Existing implementation reports are distinguished from checks performed during this audit.

## October 11 delivery update

The roadmap table below is the historical October 10 audit, not the current implementation
status. [Trustworthy learning](trustworthy_learning_milestone.md) subsequently delivered
typed verification repairs, bound frozen assessments, persistent scoped memory and a
reviewed invoice skill. [The meeting workflow](meeting_workflow_milestone.md) now adds
persisted email drafts, Calendar, autonomous meeting preparation, explicit local tentative
holds, real-browser runs, restart/repeat reconciliation and seed generalization. Refer to
those delivery reports for measured results and retained failures.

The next product extension is a permission-scoped external connection, after final recording
and setup validation. Daily summaries, external sending and a reviewed meeting skill remain
future scope. Current latency is measured rather than declared solved; the newer Tribunal
adds review time and can request a further check.

## Roadmap and current position

| Milestone | Position now | Remaining work |
| --- | --- | --- |
| Agent architecture and model access | ADK, Playwright MCP, Vertex AI/ADC, source-backed decisions, write guards, recovery and receipts are implemented. | Reliability fixes, measured context/latency improvements and broader evaluation. Architecture work is not synonymous with solved latency. |
| Observable autonomous execution | Real headed Chrome for Testing, visible input, separate agent pointer, activity and fresh verification are implemented. | Preserve actual browser execution and improve proof coverage. |
| Immersive workspace | App/console presentation, task handoff and run experience are implemented. | Integrate new capabilities into the existing visual language. |
| Start-here guide and voice | Visual chapters and narrated tour are implemented. | Reviewer audition and any final presentation polish. |
| Consistent Ava companion | Shared character, contextual composer suggestions, smoother guide motion and worker-overlay states are now implemented. | Preserve them during backend work; no broad redesign needed. |
| Trustworthy verification and independent grading | Implemented but confirmed correctness problems remain. | **Next milestone, gate A:** repair false passes, false failures and run attribution. |
| Persistent memory, Ava’s mind and reusable skills | Researched and planned; not integrated into the runtime. | **Next milestone, gate B:** real persistent learning and one reviewed invoice skill. |
| More task families | Invoice entry/routing and duplicate checks exist. | Persisted email drafts, minimal calendar, meeting workflow, daily summary. Implement a complete useful family before adding another. |
| Google/Slack onboarding | Proposed product direction. | Scoped permissions, account isolation, connection management and a real integration. Prioritize one useful connection over several incomplete ones. |
| Submission readiness | Existing demo paths and documentation exist. | Fresh evaluation, failure/recovery proof, final recording, setup instructions, architecture and honest limitations. This remains mandatory before the deadline. |

The previous companion milestone report records 216 passing tests and 45 browser checks. These are historical reported results; the complete suite and visual checks were not rerun in this audit.

Recommended order: verification/grading → persistent learning with a polished Mind page and one skill → email/meeting workflow → useful onboarding → final submission. Lock a reliable submission before expanding features; do not let onboarding consume the time reserved for final proof.

## Recent retained execution evidence

Read directly from the retained `events.jsonl` files:

| Run | Worker outcome | Fresh check events | Duration | Recorded input/output token totals |
| --- | --- | --- | --- | --- |
| `20261009-131448-21dd` | fail; worker claimed pass | 6 pass, 1 fail, **2 unknown** | 182.7 s | 472,551 / 4,889 |
| `20261009-133445-e113` | unknown; worker claimed pass | 7 pass, 0 fail, 3 unknown | 244.5 s | 464,141 / 4,963 |

The first run's companion report says one unknown; its nine raw check events contain two. Preserve original run artifacts and append corrections rather than rewriting historical evidence. The first run also has a reported independent grade of 13/13 pass. An independent grade is a separate assessment, not a replacement for the worker's verification result. Recorded token totals are not a claim about uncached billing or cost.

### Worker verification defects observed in runs

1. **Attachment representation mismatch:** `20261009-131448-21dd` c6 compared visible filename `FIG-1842.pdf` with expected file ID `f-0004`, producing a false failure. The browser-visible attachment link contains the file identity; compare equivalent typed identities.
2. **Incomplete compound coverage:** `20261009-133445-e113` c7 says pending approval **and** correct approver, but passes solely on `Ana Pereira`. Earlier retained runs have similar bundled invoice/date/amount conditions. Prompting for atomic goals has not reliably eliminated the defect.
3. **Unimplemented proof and missing baseline:** latest-invoice selection remains unknown, as do unchanged vendor settings when no prior vendor view was captured. These are honest unknowns and implementation gaps, not permission to relabel them pass.

### Independent grader defects reproduced in this audit

Disposable generated worlds and the existing grader-test helpers were used. No retained company database was modified and no model calls were made.

- Control: correct completed T1 fixture → pass, 13 items.
- Delete `run_finished` → still pass, 13 items. An unfinished execution is accepted as complete.
- Change every event's `run_id` to another run → still pass, 13 items. Event identity is not validated.
- Add a vendor-bank violation during the run: UTC window → fail on `vendor_bank_changed`; express **the same instants** as `+05:30` → pass. `_ts` discards timezone information and hides the violation.
- Set invoice issue date to `1999-01-01` → still pass, 13 items. The current hidden expected contract does not include issue date, and the grader does not check it. This is a coverage gap relative to the worker's date claim, not a broken comparison for an already-declared grader field.

Further audit candidates, not yet reproduced: subsecond boundary errors, current-state contamination when grading after later runs, same-timestamp approval selection, missing T2 rows/file blobs, world/seed/task/instance mismatch, and overly broad actor attribution. Astra should reproduce relevant cases before choosing fixes.

## Next milestone: trustworthy learning

The demo outcome is: Ava completes and proves an invoice task, shows an evidence-backed learning note, survives a process restart, and uses a reviewed procedure on a subsequent invoice with fresh source checks. Repeating an already-recorded invoice creates no duplicate. Changed policy overrides memory. Failed or unverified work remains visible without being promoted to trusted skill authority.

Gate A repairs verification and grading first. Gate B builds persistent scoped sessions/memory, Ava’s mind and one instruction-only invoice skill. This is one product milestone with a correctness prerequisite, not an invitation to rewrite the harness or add more connectors.

Use the existing ADK integration and local persistence first, with a narrow adapter for future memory providers. `docs/memory_skills_research.md` contains the prior API inspection and alternatives. Its identity section predates the companion's path-bound `instance_id`; extend the existing binding to distinguish in-place resets while preserving restart identity. Company names and seeds alone are insufficient scope.

The ready-to-paste implementation handoff is `docs/prompts/astra_trustworthy_learning_milestone.md`.
