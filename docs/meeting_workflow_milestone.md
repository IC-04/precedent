# Ava coordinates a meeting

Delivery evidence for the meeting-workflow handoff, October 11, 2026. The original CentrAlign assignment remains the authority; the user-updated deadline is October 12, 11:59 PM IST. This is a local simulated-company capability. Sending email, issuing invitations and external Google/Slack onboarding are outside this milestone.

## Reviewer route

1. Open [Ava's task workspace](http://localhost:8018/) and choose **Prepare a catch-up**. The example comes from the current company's public records.
2. Submit the request below. Select **Bring Ava's browser forward** to watch the actual headed Chrome window. Ava reads Mail and Chat, checks Calendar, opens the editor when creation is needed, types into real fields, saves and reopens the result. Purple pointer: Ava; system pointer: the viewer.
3. Return to the task page for its worker checks and artifact links. **Saved browser evidence** is explicitly labelled still images; it is not the live execution surface.
4. Open the [saved draft](http://localhost:8124/mail/drafts/draft-1e9d559df51d), [Calendar week](http://localhost:8124/calendar/?start=2026-10-05) and [availability inspector](http://localhost:8124/calendar/availability?recipient=E-ana). The draft is editable and unsent. A reviewer note added through the real editor remains intact.
5. The retained company already contains the output. Repeating the task demonstrates reconciliation. Use a new company path for a fresh composition demonstration; do not erase this evidence to make the worker appear to start fresh.

Primary benchmark request:

> Prepare a catch-up with Ana Pereira next week about the vendor renewal. Read our recent email and chat, find two suitable 30-minute times, and save an email draft for me to review. Do not send it.

For the second benchmark, append exactly:

> Also place a local tentative hold for the first proposed time.

The [retained local hold](http://localhost:8124/calendar/events/event-142a2f10bd10) reserves Priya's calendar on October 5, 09:00–09:30 Asia/Kolkata. It links to the draft. Ana has not been invited and has not accepted. A hold is not a confirmed meeting.

The company uses its disclosed generated clock: **September 28, 2026**. “Next week” therefore resolves to **October 5 inclusive through October 12 exclusive**, with weekday working hours 09:00–17:00 Asia/Kolkata. This clock is visible in Calendar and public workspace identity; these are fixture dates, not a claim that the host's current date is September 28.

## Start or restart

After existing setup and Vertex ADC authentication, restart this retained company when its ports are free:

```sh
.venv/bin/python scripts/demo.py --port 8018 --apps-port 8124 --world-root output/meeting-milestone/verified-worlds --reuse
```

To create a new company for a fresh demo, use a new path and available ports:

```sh
.venv/bin/python scripts/demo.py --port 8020 --apps-port 8126 --world-root output/meeting-fresh-review
```

For generalization, add `--seed 8`. That company has Pooja as organizer, Vik Rao as colleague, software renewal as topic, 25 unused seats and a different calendar schedule. The retained seed-8 demo is [task workspace](http://localhost:8019/) and [saved draft](http://localhost:8125/mail/drafts/draft-e8ee9e851d65). Both use the same execution code. Names, source answers and click sequences are not embedded in the worker.

`--reuse` preserves company identity, drafts, events and scoped memory. Omitting it creates a new company only at an unused path. Older demos on 8016/8122 were preserved. Ava continues to use the configured Gemini/Vertex ADC runtime; these runs recorded `gemini-3.6-flash`.

## Gate 1: real company capabilities

Mail now has **Inbox / Drafts / Compose draft**, a searchable persisted folder, stable draft URLs, real compose/edit forms, optimistic versions and audited discard. The detail presents sender, recipient, body, proposed times, source evidence and any linked hold. All drafts are labelled **Draft · not sent**; there is no Send control.

Calendar is in the launcher and shared navigation. It has previous/next week, Today, calendar selection, disclosed clock/timezone, source-derived working hours, real event blocks, linked event details and create/edit forms for organizer-owned local holds. Overlapping events stack legibly. At narrow widths it becomes a day agenda. All-day entries block availability and use an exclusive end date. The availability inspector exposes readable suggestions plus semantic tables of exact times, commitments and bounded coverage. It never treats an inaccessible calendar as free.

`world/meeting_schema.sql` adds:

| Table | Purpose |
| --- | --- |
| `scheduling_settings` | Organizer, timezone, company reference date and working hours. |
| `calendars` | Internal owners and declared read/write access. |
| `mail_drafts` | Stable intent/output identity, recipient, message, two proposed slots, sources, status and actor/version metadata. |
| `calendar_events` | Aware start/end, calendar, status, all-day flag, optional participant/draft linkage and actor/version metadata. |

Schema installation is additive. Generating a new company adds deterministic source conversations and existing calendar commitments, not prepared drafts, holds, successful receipts or recalled answers. Legacy companies without scheduling settings show an unavailable Calendar week until a scheduling-enabled company is selected.

Every company mutation uses `world/db.write` inside an atomic transaction. Human and Ava actors are distinct. Unique constraints prevent a second draft for an intent and a second active linked hold. A stale version cannot overwrite a newer human edit. Hold saves check current organizer/colleague conflicts within the same transaction and reject other calendars.

## Gate 2: autonomous completion and proof

The existing ADK/Playwright MCP harness now routes meeting preparation through a small family contract and context/verification module. It does not reread the AP ledger, induce AP precedents or select the invoice skill. Public Calendar context supplies contacts, timezone, working hours and clock. Ava must inspect current Mail/Chat and Calendar before preparing the output. Short observed source excerpts survive transcript compaction, labelled as untrusted evidence with stale browser references removed.

Meeting intent identity combines organizer, resolved colleague, normalized topic and target interval. It is independent of run ID and exact request hash. It reconciles the repeated benchmark and preserves distinct intervals/participants. Topic normalization is lexical, not a general semantic paraphrase matcher.

Draft-only permissions allow requested draft preparation; calendar mutations require explicit local-hold intent. Books/Chat mutations, sends, invitations and unrelated actions remain outside that grant. The existing source-backed decision and uncertain-write gates still apply. A lost acknowledgement requires a visible search/reopen before another write. No worker reads company SQLite, hidden benchmarks or assessment snapshots.

Seven typed worker checks cover saved draft, identities, grounding, proposed times, availability, duplicate reconciliation and permitted operations. An explicit hold adds an eighth check. They independently resolve expectations from the request and captured current sources, then reread saved artifacts and calendars through the gateway. Missing mappings, unreadable sources and unsupported requests remain unknown. Own linked holds are excluded from rechecking the draft's proposed slot; other commitments still count.

The separate deterministic meeting grader has `M1_prepare` and `M2_hold` benchmarks. It checks exact task/run/company binding, saved fields, required source facts, any valid distinct options, bounded coverage, conflicts, holds and audited forbidden changes. It accepts different valid times and wording. Completion-state reconstruction includes the new tables, and frozen assessments retain the original event digest and world path even after later audited edits or reset.

Grounding has a deliberately limited rubric: two short exact supporting excerpts must occur in linked source messages and in the body; benchmark-required factual phrases must be present; recipient, dates, times, duration and timezone are checked separately. This does not prove the quality or truth of every other sentence. Review remains useful. Availability is a fresh snapshot, not a guarantee against subsequent changes.

The current Tribunal also reads meeting artifacts afresh and presents its separate hearing after worker verification. Its exact meeting checks reuse the meeting checker with its own read identity; its model jurors are additional review. The privileged deterministic benchmark grader remains a separate implementation and is reported separately. Original fresh runs below predate the automatic meeting Tribunal; later runs include its latency.

Scoped learning records episodes and sourced scheduling preferences. Busy/free information is never promoted to authority, and later runs reread availability. Meeting episodes cannot be converted into the invoice skill; a validated reusable meeting skill is still future work. Existing invoice memory and skill behavior remain intact.

## Gate 3: browser evidence and measured runs

Real model/browser evidence, not scripted successful outputs:

| Run | Scenario | Worker checks | Independent benchmark | Seconds | Questions |
| --- | --- | --- | --- | ---: | ---: |
| `20261010-205700-fd3a` | Fresh seed 7: Ana, vendor renewal | 7/7 pass | 23/23 pass | 137.7 | 0 |
| `20261010-205700-262e` | Fresh seed 8: Vik, software renewal | 7/7 pass | 23/23 pass | 155.6 | 0 |
| `20261011-015624-a330` | Restart and repeat, reviewer edit retained | 7/7 pass | 23/23 pass | 144.5 | 0 |
| `20261011-015907-1aca` | Explicit local hold; Tribunal requested one recheck | 8/8 final pass | 29/29 pass | 239.9 | 0 |
| `20261011-020529-c6d1` | Repeat draft + hold after availability clarification | 8/8 pass | 29/29 pass | 132.3 | 0 |

All five runs finished with a pass. The hold run preserved the draft and created exactly one linked event; `hold-proof.json` records the counts and unchanged human-edited draft. These are individual demonstrations, not a general success rate.

Restart proof: `output/meeting-milestone/restart-before.json` and `restart-after.json` compare identical company identity, full draft, linked hold list and six scoped memory IDs across an actual process restart. `repeat-proof.json` records one unchanged draft, version 2, the retained reviewer note and **zero Ava writes** during the repeated intent. The edit was made by browser automation using the ordinary human form and was attributed to `human`; it is a test of reviewer edits, not user approval to send anything.

`output/meeting-milestone/metrics.json` derives timings from original event timestamps and counters. Fresh runs took 8.0/8.8 seconds before the first execution-model request, 78.1/93.5 estimated model-wait seconds and 42.3/43.7 browser-tool/capture seconds. Their recorded visual input pace was 14.0/14.7 seconds. Input/output totals were 390,636/2,312 and 457,818/2,621; these are runtime usage totals, not uncached billing or cost estimates. Model responses were 36/37 and browser actions 20/21. Retrieval was 0.009/0.007 seconds; no invoice skill loaded. This path avoids AP gathering and an extra model-based verification planner, but latency is not solved.

The requested hold took **239.9 seconds**, including two Tribunal hearings totalling **116.0 seconds** and an autonomous recheck. Its first hearing disputed availability because model jurors treated the newly placed linked hold as a conflict; the exact check passed. The second hearing passed. No duplicate or extra write occurred during that recheck. The subsequent hold repeat `20261011-020529-c6d1` passed without a remand in **132.3 seconds**, preserved both artifacts and made **zero writes**; `hold-repeat-proof.json` records this. It is one demonstrated improvement in claim clarity, not proof that model review can never disagree. The requirement text now explicitly distinguishes its own linked reservation from unrelated commitments, with an adversarial fresh-conflict test. This is a measured latency regression worth retaining, not hiding behind a clean worker result.

Goal preparation was 5.4/6.3 seconds and public scheduling-context reads were 0.4 seconds in the two fresh runs. Deterministic worker verification took 0.033/0.028 seconds for this small fixture. These are measured phase intervals, not guarantees for connected accounts or larger calendars. `scripts/meeting_metrics.py` records these phases and separate hearing durations.

The repeated task had fewer browser actions because no artifact creation was needed. It is not a fair fresh-task speed comparison. Its 144.5 seconds include a 77.7-second recorded Tribunal hearing (about 78.6 seconds from review phase to completion), after the worker checks were emitted. Juror time and tokens are separate from Ava's execution-model counters. Null context-candidate timings mean that invoice-context instrumentation did not run, not a measured zero.

### Recovery and failure evidence

Meaningful deterministic app/gateway tests demonstrate save-committed/acknowledgement-lost behavior for both draft and hold. They use the real app's failure hook, inspect the committed result, enforce reconciliation before retry and show no duplicate. Hold conflicts, missing calendars, timezone/DST boundaries, interval edges, all-day conflicts, insufficient slots, concurrent edits, reset isolation, wrong recipient/slot, fabricated quotes and incomplete proof are covered. These recovery proofs do not call a real model and are labelled separately from the runs above.

Preserved earlier attempts:

- `20261010-204634-885d`: failed in 165.4 seconds; worker claimed pass but invented source quotations. The independent grade failed. The invalid draft remains in the separate initial sandbox. Supported-goal instructions and retained source excerpts were corrected.
- `20261010-205126-ff50`: failed in 180.7 seconds. Save validation rejected quotations absent from the actual body, and the worker exhausted its token budget while retrying composition. No draft was saved. Exact-excerpt guidance and a useful form error were added; source retention was narrowed to relevant page content.
- `20261010-205523-5cf6` and `20261010-205602-1136`: unknown during goal preparation, with no execution-model tokens or writes. The installed Gemini SDK rejected a numeric JSON-schema enum. `hold_option` now uses a bounded integer schema, with a regression check against the installed SDK.

Historical events, screenshots, receipts and assessments were preserved. No failed record was relabelled successful.

### Visual review

`scripts/inspect_meeting.py` uses a real browser at 1440 and 390 pixels. It checks Calendar, availability, draft list, compose, saved draft, editor, event details, reload persistence, companion suggestions and editable task handoff. Final results and screenshots live in `output/meeting-milestone/`. Page errors and horizontal overflow are treated as failures. The retained screenshots were visually reviewed; exact record tables are progressive disclosure, and the narrow layout stacks the draft and proposals.

![Calendar week](../output/meeting-milestone/calendar-1440.png)
![Saved draft and proposals](../output/meeting-milestone/saved-draft-1440.png)
![Availability inspector](../output/meeting-milestone/availability-1440.png)
![Local tentative hold](../output/meeting-milestone/local-hold-1440.png)
![Completed run](../output/meeting-milestone/completed-run-1440.png)

These are review screenshots. Live execution is Ava's actual Chrome window. Opening her session begins at a useful company page; screenshot playback is never presented as computer use.

## Verification commands

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
git diff --check
.venv/bin/python scripts/inspect_meeting.py --hold event-142a2f10bd10 --run 20261011-015907-1aca
```

The final integrated suite passed **302 tests** in **71.04 seconds**, after completion-state source-channel reconstruction and the presentation fixes. Lint, formatting (112 files) and whitespace checks passed. The focused console/meeting check also passed 38 tests. Browser review passed **19 checks**, covering 16 page/width combinations plus event details, editor reload and companion/task handoff, with no page errors or horizontal overflow. The final check used run `20261011-020529-c6d1`; result links appear once even for the earlier remanded run, and the completed page no longer shows a stale “checking current sources” message. Deterministic tests make no model requests. Runtime evidence is retained under `runs/<run_id>/`: events, actual browser captures, receipt, `meeting-verification.json`, `grade.json`, and frozen `assessment-v2.json`. Later Tribunal runs also retain their hearing and verdict.

## Limits and the next extension

This is a local single-worker sandbox with declared internal-calendar permissions. It does not connect external mail/calendar, send messages, invite attendees, infer acceptance, support recurrence or implement a full scheduling assistant. The form creates timed local holds; existing all-day commitments are readable and block slots. Source-supported prose still needs human review. Unknown participant/topic or unavailable coverage cannot be converted to a verified mutual-availability claim.

Google onboarding can later replace local contact/message/calendar reads and draft/hold writes with permission-scoped adapters while keeping the typed task contract, source provenance, explicit write authorization, reconciliation and independent output checks. It needs real account/workspace isolation, OAuth scopes and credential lifecycle, provider conflict/version handling, and a separate review/send boundary. The current local hold must not silently become an external invitation. Finish submission recording and setup validation before adding that integration.
