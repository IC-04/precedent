# Research: Ava as a real Google-connected worker

Researched October 11, 2026. This is an implementation decision brief, not evidence that an account is connected. No application code, OAuth configuration, account access, or live task execution was changed during this research.

## Product decision

Build **Connect Google → assign an outcome → observe actual execution → inspect the result in Gmail or Google Calendar**. Start with a real Gmail reply draft and scheduling against the owner's real calendar. Add an owner-only event only when requested. Preserve the same planning, observation, recovery, learning, and verification loop across local and connected environments.

This is a 9/10 direction for this submission: useful outcomes are independently visible in familiar applications, and composing capabilities across two providers demonstrates more than an integration screen. OAuth alone does not demonstrate autonomy. Changing a topic, resolving a conflict, reconciling an ambiguous save, and verifying the native artifact do.

The internship statement explicitly permits APIs alongside browsers, files, and simulated applications. The existing browser-only implementation boundary is a project design choice. The user has now requested genuine OAuth/API execution; record that hybrid boundary when implementing. Preserve browser work and accurately identify API work.

The governing problem statement is `../JD CentrAlign AI_Engineering Hiring.docx`. The user's corrected deadline is October 12, 2026, 11:59 PM IST.

## Observed implementation gaps

| Current code | Consequence | Necessary correction |
|---|---|---|
| `connected/web.py:33` reads absent developer OAuth settings; current UI offers setup instructions | The account owner encounters a guide instead of account connection | Configure the application once; make normal onboarding Google consent |
| `worker/connected.py:15` expressly prohibits Calendar and Gmail draft export | Most requested useful Google work is unsupported | Introduce guarded native provider operations |
| `connected/service.py:186` requires Gmail and Slack evidence for every save | Gmail-only and Gmail + Calendar tasks cannot compose capabilities | Determine prerequisites from task intent |
| `connected/service.py:209` stores a local artifact | No result appears in Gmail Drafts | Save to Gmail and retain its stable draft ID |
| `worker/connected.py:73` constructs one fixed preparation goal | Different requests receive essentially the same outcome | Build goals from requests and available capabilities |
| `worker/runner.py:723` returns into a separate connected path before ordinary recall; `:1448` excludes connected learning | Existing memory/skills do not generalize to connected work | Share runtime stages and scope learning to stable account identity |
| `worker/connected.py:213` records no independent grader; failures can collapse to unknown | Current connected checks cannot establish native task completion | Separate fresh provider verification from worker claims; preserve fail/unknown semantics |
| `worker/gateway.py` treats non-GET as writes | A read-only Calendar free/busy POST does not fit its assumptions | Classify registered operations by semantics, not HTTP verb |
| `tests/test_connected.py:285` uses fake providers and a scripted model, expects unknown | Passing tests do not prove real-account completion | Retain fixtures, add actual model/account acceptance evidence |

There is no current `instructions.py`. Instructions live in worker modules. The future extension contract should isolate provider knowledge and tools, rather than adding another runner branch for every app. The existing encrypted vault, source/version tracking, live browser, guards, scheduling functions, event stream, and learning service are useful assets.

## OAuth: one-time developer setup versus user onboarding

For this local FastAPI product, prefer a confidential **Web application OAuth client** with an exactly registered localhost callback. Google documents localhost HTTP redirects for local testing. One client can request Gmail and Calendar permissions. Offline access supports subsequent task execution, and incremental authorization supports requesting event-writing permission when the feature is enabled. This recommendation avoids a Google-specific tunnel and preserves the existing server-side credential boundary. [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).

A packaged native application could instead use a Desktop client with loopback redirection. Installed apps do not support incremental authorization; do not combine the Desktop-client proposal with promises of the web-client incremental flow. That packaging change is unnecessary for the deadline. [Google native-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).

Existing Vertex ADC authenticates inference, not delegated mailbox access. Enabling APIs, configuring the consent audience/test users, and registering the OAuth client remain application-owner setup. Astra should perform supported setup with the user's existing authorized project access and request intervention only for actions the provider requires the human to perform. Repeated users of a configured application should not create clients or edit environment files.

Use state bound to the initiating owner/session, granular granted-scope handling, protected token storage, and explicit reconnect states. Persisted grants must survive application restart without pretending refresh tokens never expire. [Google OAuth best practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices).

Testing authorizations, including offline refresh tokens, expire after seven days for these scopes. Personal/development exceptions make a small authorized prototype plausible; they do not establish public onboarding readiness. Public distribution of restricted Gmail scopes can require additional review and assessment. These are distribution limits, not reasons to replace this user's live connection with a mock. [Testing audience](https://support.google.com/cloud/answer/15549945?hl=en), [restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

## Permissions and task capabilities

| Feature | Candidate scope | Application restriction |
|---|---|---|
| Read relevant Gmail context | `gmail.readonly` | Enforce selected label/search bounds; do not ingest the inbox wholesale |
| Create/update Gmail drafts | `gmail.compose` | The scope also permits sending; expose and enforce draft operations only |
| Choose calendars/timezone | `calendar.calendarlist.readonly` | Only selected, accessible calendars; distinguish owner from shared calendars |
| Read owner's availability | `calendar.freebusy` | Selected owned calendars and bounded date range |
| Read owner's events | `calendar.events.owned.readonly` | Useful for Calendar UI, concrete event proof, and detecting conflicts |
| Reserve time when requested | `calendar.events.owned` | Selected owned calendar; no attendees, invites, unrelated edits/deletions |

Add `openid email` for verified stable account identity if required by the chosen owner flow. Event write permission already includes owned-event reading: request the read-only or write variant as appropriate, not redundant scopes by habit. Verify every endpoint's accepted scopes, especially free/busy, before implementation. Source selection narrows application behavior, not Google's OAuth grant itself. [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth), [free/busy endpoint](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query).

Calendar access does not reveal arbitrary colleagues' availability. Propose the owner's free times and request recipient confirmation unless shared access is genuinely available.

## Integration choices

| Approach | Fit for Precedent |
|---|---|
| Narrow typed provider adapters using official endpoints and supported Google auth libraries | Recommended. They fit existing HTTPX/vault services and make capabilities, operation journaling, and exact proof explicit |
| Existing ADK `GmailToolset` / `CalendarToolset` | Useful option, already installed. Apply the same guards; do not expose a whole generated API surface |
| Managed connection broker such as Composio | Can manage connected accounts, but adds a service and credential/data-processing boundary. No demonstrated need to add it for two Google services |
| Native Gmail/Calendar browser automation | Preserves literal browser interaction, but OAuth API tokens do not establish browser login sessions. Keep the real browser for appropriate app interactions and native outcome inspection |

The installed ADK source exposes both Google toolsets and filtering. Its OAuth configuration also derives a default discovery scope; filtering tools is not proof of minimal OAuth grants. Audit and explicitly control requested scopes if using it. No agent framework replacement is justified. [Official ADK implementation](https://github.com/google/adk-python/blob/main/src/google/adk/tools/google_api_tool/google_api_toolsets.py), [ADK authentication](https://adk.dev/tools-custom/authentication/), [Composio connected-account authentication](https://docs.composio.dev/docs/tools-direct/authenticating-tools).

## Provider details that affect reliability

Gmail drafts have stable draft IDs even though replacement changes the underlying message ID. Build standards-compliant MIME and base64url encoding. A real reply must preserve thread association, matching subject, and appropriate `References` / `In-Reply-To`; copying a subject alone is insufficient. [Draft lifecycle](https://developers.google.com/workspace/gmail/api/guides/drafts), [threading](https://developers.google.com/workspace/gmail/api/guides/threads).

No assumption of a generic Gmail idempotency key is justified. Keep a durable intent/operation journal, serialize conflicting writes, and reconcile an ambiguous create by listing and reading matching drafts. Gmail supports `rfc822msgid` search, but live-test whether the chosen marker is retained and searchable on created drafts. An empty search immediately after timeout is insufficient proof of no write. If reconciliation remains ambiguous, stop rather than duplicate. [Draft listing](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/list), [draft readback](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/get).

Calendar accepts client-supplied event IDs with defined encoding/length rules. Persist an intent-bound ID before creation; after timeout or duplicate-ID response, GET and compare the existing event. Omit attendees for an owner-only hold: `sendUpdates=none` alone is not an adequate invitation boundary. Availability checks are not atomic reservations; check immediately before writing and verify afterward, disclosing concurrent-change limitations. [Event creation](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert), [event readback](https://developers.google.com/workspace/calendar/api/v3/reference/events/get).

Handle recurrence, all-day events, transparency/cancellation, timezone boundaries, and pagination through provider-supported representations. Reuse local scheduling logic only after confirming its assumptions. Bounded reads may retry with backoff; uncertain writes require reconciliation first. [Event listing](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), [Gmail errors](https://developers.google.com/workspace/gmail/api/guides/handle-errors), [Calendar errors](https://developers.google.com/workspace/calendar/api/guides/errors).

## Honest observation, memory, and proof

Use the shared run view and Ava companion. Live API actions should have actual start/end events, source observations, and result identifiers; browser typing/cursor animation should occur only for browser actions. Provider-backed Mail/Calendar views can be real working surfaces, clearly identified as Precedent's views of Google data. Do not depict an API operation as typing in native Gmail. Native links must resolve to the intended signed-in account; OAuth consent does not sign in Ava's isolated browser.

Independent provider checks should reconstruct expectations from request/source evidence and use fresh GETs through a read-only capability path, not the worker's saved claim or cache. Deterministic field checks and bounded semantic assessment should remain distinct. A local generated-world hidden oracle cannot grade a real Google account.

Keep stable account identity separate from grant/selection revision. Preferences and approved procedure lessons can persist in that account's memory; a reconnection or new selection must still invalidate stale access and revalidate cited facts. Do not turn the inbox into a permanent copied database. Disclose actual inference recipients, apply bounded retention to sensitive observations and captures, and publish only sanitized synthetic demonstration evidence. [Workspace user-data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy).

## Recommended acceptance demonstration

1. Connect the user's authorized personal Google account with a synthetic demo thread and chosen owned calendar.
2. Ask for a thread-grounded Gmail reply containing two free 30-minute options next week. Verify the real unsent draft, then inspect it in Gmail.
3. Explicitly request reserving one option. Create an owner-only Calendar event, read it back, and inspect it in Google Calendar.
4. Repeat the original intent; preserve the existing artifact and avoid duplicates. Try another recipient/topic without changing runtime code.
5. Introduce a real controlled conflict or an explicitly labelled injected lost-acknowledgement fault. Show replanning/reconciliation and record the result honestly.

Implement Google first, preserve existing Slack groundwork, and add Slack through the same capability contract afterward. Measure preparation, model, provider, browser, and verification latency separately. Do not substitute broader UI features or additional integrations for completing this loop.
