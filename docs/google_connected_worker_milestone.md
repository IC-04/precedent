# Google connected worker milestone — 2026-10-11

## Acceptance status

This is a partial live acceptance result, not a claim that all three gates are complete.

| Gate | Status | Evidence and remaining work |
| --- | --- | --- |
| 1 — Actual account and workspace | Passed for the connected account | Human Google consent completed; userinfo identity verified; live Gmail search, owned-calendar metadata, free/busy and events reads succeed. Restart restores encrypted access and selected boundaries. |
| 2 — Autonomous native work | Calendar portion passed; Gmail portion pending | Real Vertex/ADK/Playwright runs created owner-only Google Calendar events, adopted an existing event on repeat, and recovered a suppressed acknowledgement without a duplicate. Incoming synthetic email is pending, so autonomous Gmail reply and the composed meeting workflow are not yet evidenced. |
| 3 — Independent proof, learning and demonstration | Calendar portion passed; combined acceptance pending | Fresh read-only provider checks and bounded Vertex semantic review passed for the Calendar outcomes. A repeated task actually recalled scoped learning. Continuous actual-browser recordings and desktop/narrow screenshots are retained. Gmail proof, native Gmail inspection, linked second-option reservation and live draft-edit preservation still need the incoming email. |

The authorized owner selected the Google account in the actual consent flow. Account identity is visible in the private app; no replacement test account was used. Public documentation omits the account address and provider links containing that address.

## Open the current product

- Owner workspace: http://localhost:8250/workspace
- Connections: http://localhost:8250/connections
- Mail: http://localhost:8250/mail
- Calendar: http://localhost:8250/calendar
- Ava’s mind: http://localhost:8250/mind
- Normal Calendar result: http://localhost:8250/native/a53922729b7034f76e273dae415e01af
- Recovery run: http://localhost:8250/runs/20261011-121408-28c8

Owner pages require the local session cookie. `uv run precedent connected` opens a fresh one-use owner opening link without printing it. Existing authenticated setup Chrome can also open these URLs. Ava uses a separate headed Chromium context and never sees Google consent pages, client credentials, owner cookies or account sign-in.

Launch from the repository:

```sh
PRECEDENT_PROJECT_GUIDE_URL=http://localhost:8018/guide uv run precedent connected
```

This uses the retained, verified project guide at port 8018. Omit that variable to leave the optional guide link out. The workspace defaults to 8250 and the callback-only listener to 8251. Previously retained local demo services were preserved.

## Account setup completed

Gmail and Calendar APIs were enabled in the existing authorized Cloud project using its working ADC access. The Cloud Console’s authenticated setup window was used to create Precedent’s branding, External/Testing audience, authorized tester and Web application OAuth client. The exactly registered callback is `http://localhost:8251/oauth/gmail/callback`.

The client JSON is stored outside the repository at `~/.local/share/precedent/google-oauth.json` with mode 0600. The encryption key is separate, at `~/.local/share/precedent/connected.key`, also 0600. `.connected` is owner-private and ignored by Git. No secret values were printed or committed. The unfinished CLI sign-in callback was not needed: ADC and the user-authenticated Cloud Console provided the necessary setup access.

Supported configuration names are `PRECEDENT_GOOGLE_CLIENT_FILE`, `PRECEDENT_GOOGLE_REDIRECT_URI`, optional `PRECEDENT_GOOGLE_CLIENT_ID` / `PRECEDENT_GOOGLE_CLIENT_SECRET`, `PRECEDENT_CONNECTED_ROOT`, `PRECEDENT_CONNECTED_KEY_FILE`, and optional `PRECEDENT_PROJECT_GUIDE_URL`. Vertex inference separately uses `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` and the configured model variables with ADC. OAuth does not replace inference authentication.

The owner consent granted identity/email, `gmail.readonly`, `gmail.compose`, `calendar.calendarlist.readonly`, `calendar.freebusy` and `calendar.events.owned`. The account’s enabled capabilities accurately include Mail reading/drafts, Calendar list/events/free time and explicit reservations. Feature selection supports Mail only or read-only Calendar; previously granted Google scopes can remain during incremental authorization, so application feature restrictions also enforce disabled features. Reduced-scope and disabled-feature behavior have fixture coverage; live reduced consent/revocation was not staged.

The selected calendar is the owner’s primary calendar, timezone Asia/Kolkata. Working hours are explicitly disclosed as the weekday 09:00–17:00 default until the owner saves a preference. Mail selection is Inbox, last 30 days, restricted to the synthetic conversation subject `Precedent demo: prototype review`. No unrelated inbox content was supplied to the model.

## Live runs and measured results

| Real run | Task | Outcome | Runtime | Steps | Native write calls |
| --- | --- | --- | ---: | ---: | ---: |
| `20261011-120049-5a97` | Reserve a 30-minute owner-only demo event on Oct 12, 14:30–15:00 Asia/Kolkata | Pass | 78.4 s | 14 | 1 |
| `20261011-120451-e096` | Repeat exactly the same task | Pass | 97.1 s | 19 | 0 |
| `20261011-121118-da1d` | Recovery test before permission-parser correction | Fail/blocked; no event created | 62.1 s | 12 | 0 |
| `20261011-121408-28c8` | Reserve Oct 13, 14:30–15:00 with a labelled suppressed acknowledgement after real commit | Pass | 87.9 s | 20 | 1 |

These are real configured Gemini/Vertex runs using ADK and Playwright MCP, not scripted completion. All have zero human questions and zero artificial viewing delay. Provider call counts were 18, 25, 11 and 20; cumulative provider time was 17.750, 17.790, 9.472 and 17.749 seconds respectively. These timings overlap browser operation, so they must not be added to total runtime. Browser action timings are represented by action/observation timestamps; model phase timings are recorded separately in newer runs. Earlier token counters omitted preparation/review usage; the newer callback path includes those calls. Do not compare those old and new counters as identical cost measurements.

The repeat retained the same native event ID and made no native write. It retrieved one account-scoped learning note in 0.005 seconds. The recovery event’s journal explicitly records `Acknowledgement suppressed after actual provider commit`. Google was not deliberately made unavailable: the server discarded the successful acknowledgement once, then Ava used the real UI to inspect/reconcile the pending operation. Fresh event-ID reads repaired the journal without a second native create. The actual provider event is present once with no guests or conference data.

Both events passed another fresh inspection after execution, including fresh Google userinfo, account binding, owned-calendar identity, title, start/end, no guests, expanded current conflict listing and intent-scoped duplicate checks. Private native IDs and Google-returned inspection links are retained in `output/google-connected-worker-milestone/live-results.json` and the per-artifact fresh proof files.

The failed recovery attempt is retained. Its task said “do not create a duplicate”; a broad negative-word pattern mistakenly withdrew explicit reservation authorization, and the negative verifier check treated the refused attempt as an event that occurred. The app correctly blocked that request before a provider write. The parser now recognizes negative event/reservation commands specifically, and permission verification distinguishes blocked requests from potentially committed writes. Regression tests cover both the duplicate warning and explicit bans.

## Implemented execution and reliability boundaries

One shared worker performs context recall, goal preparation, planning, real browser actions, source-backed decisions, provider readback, bounded semantic assessment, receipts and learning. Google environment instructions supply capabilities instead of requiring Slack or borrowing the generated company’s dates, policies or hidden truth.

Mail/Calendar pages are Precedent working surfaces backed by live official Google APIs. This is hybrid browser/API execution, not a claim that Ava is signed into native Gmail. Native outcome inspection belongs in the owner’s signed-in browser. Actual browser entry uses the existing real typing and separate Ava cursor; initial navigation opens the productive workspace instead of about:blank. The existing colored companion stylesheet and recorded-state poses are used consistently.

The server exposes native draft create/update and explicit owner-only reservation forms. No worker send, invite, delete or settings operation exists. Reply recipients come from the current source’s Reply-To/sender; owner replies are rejected. MIME threading, stable draft IDs, current source fingerprints and editor versions are checked. A human-edited draft is preserved. Successful repeats reuse existing native work; different trusted tasks can have distinct intents. Gmail write keys use the server-bound trusted task rather than model wording alone.

Native writes are serialized by the single connected service, with a single active worker. Operation metadata is durable and encrypted. Calendar uses a predetermined hex event ID. Gmail uncertainty uses recorded intent, marker-scoped native draft searches and full readback; an empty or ambiguous query stops safely. Live Gmail marker retention/searchability remains unvalidated until the first actual draft save. Do not claim Gmail exactly-once behavior from fixtures alone.

Reconciliation uses fresh reads only. Calendar free/busy is treated as a read despite its HTTP POST. Bounded read retries do not retry native writes. The independent verifier receives a read-only facade; it cannot obtain native write methods or provider transport. Fail dominates unknown; missing/inaccessible/incomplete proof cannot become pass. Verification establishes application-mediated operations and checked provider coverage, not every action taken by other Google clients.

Source bodies are bounded at 20,000 characters; truncation is displayed and creates unknown coverage. Attachments and remote active content are not automatically opened. Source text cannot authorize mutations. Current-source and selected-access checks apply again during saving and native inspection.

## Learning, retention and privacy

Memory follows stable owner + Google subject identity; grant and selection revisions separately invalidate access. Successful Calendar work produced real scoped episodes and subsequent recall. Ava’s mind offers owner-approved working hours and an instruction-only skill candidate from verified work. Candidates remain drafts: independent candidate validation and owner activation are required by the existing skill rules. No Google skill was labelled validated or activated in this acceptance run.

Google learning persists procedural proof metadata, not copied inbox bodies or model-generated email summaries. Current sources and permissions govern every new execution. Preferences, procedure notes and operation references remain until forget-data. Raw model/run logs, captures and browser evidence expire after 24 hours; the app purges expired private run directories on startup and within five minutes while running. This is a prototype retention choice, not a blanket compliance claim. Manually retained synthetic acceptance evidence in ignored `output/` is separate from automatic raw-run retention.

Disconnect removes usable local access; forget-data removes the owner’s registered account-scoped learning/preferences, worker grants, local operation references and raw run directories. Neither action silently deletes native Gmail drafts or Calendar events. Stop prevents subsequent work but cannot promise that a provider write already in flight did not commit; the journal must be reconciled.

Only Google Vertex AI processes personal task context in this connected flow. The owner explicitly approved that recipient. Bedrock Tribunal and other-family reviewers are disabled for these runs; no unrun jury is presented as a passing independent grader.

## Evidence and checks

The ignored, private `output/google-connected-worker-milestone/` folder holds live summaries, fresh proofs, per-run verification, actual browser action captures, continuous browser videos and desktop/narrow screenshots for Connections, Calendar, Mail, Ava’s mind, result cards and the recovery timeline. The Mail screenshot is truthfully empty and named `mail-awaiting-demo-input`, not presented as completed Gmail execution. OAuth/sign-in windows were excluded from recording. Native Gmail screenshots remain pending. Native Calendar was opened through the actual returned Google link; its real event title was verified visually and an outcome screenshot was retained after dismissing Google’s welcome overlay. This human-side inspection is separate from Ava’s autonomous execution.

The recordings capture the live browser’s frame stream and encode it at 15 frames per second, capped at 90 seconds. Resampling/container duration is not the runtime clock; timings come from actual run events. They are evidence recordings, not a playback substituted for autonomous execution. The run workspace itself is real headed Chromium controlled by the model.

The final integrated suite passed 334 tests, with 204 existing library warnings, in 72.99 seconds. The retained test output records the full run. Repository lint and format checks pass. Fixtures cover OAuth replay/denial, partial grants, access/account changes, native MIME/threading, version-preserving draft updates, lost acknowledgements, unresolved uncertainty, conflict refusal, task-only mutation permission, source changes, duplicate warnings, verdict aggregation, read-only verification, scoped candidate status and forget-data preserving native objects. Fixture evidence is not live Google evidence.

## Exact remaining acceptance dependency

The user authorized one synthetic input email to the specified personal recipient. It was sent once, separately from Ava, from the connected account. Its subject is `Precedent demo: prototype review`; it requests a nonconfidential reply about reviewing the onboarding prototype and finding 30 minutes next week. As of this report, the selected Inbox query has no incoming reply.

Once that reply arrives, run the email-only acknowledgement task, then the two-options meeting draft task (no reservation), then “Reserve the second option without inviting anyone.” Verify each real native artifact, repeat the completed Gmail intent, preserve a controlled human draft edit, vary the topic without code changes, inspect native Gmail/Calendar and document results. These steps are ready to exercise but remain acceptance work. All three gates cannot truthfully be declared complete before those results exist.

## Provider references

Google documents stable draft containers and replacement message IDs in the [draft lifecycle](https://developers.google.com/workspace/gmail/api/guides/drafts), and supports marker queries in [draft listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/list). Calendar’s client-supplied IDs and owner-only payload behavior follow [events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert). Local prototype OAuth uses the [web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server); Testing expiry/public-distribution limits remain relevant for later recruiter onboarding.
