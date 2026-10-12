# Gmail and Slack onboarding: feasibility and recommended milestone

Researched October 11, 2026. This is a planning document; no connector, OAuth client, account consent, or live provider demonstration was created in this research turn.

## Recommendation

Proceed with a locally operated connected-workspace demo using a dedicated Gmail test account and a Slack test workspace containing synthetic conversations. Connect both through genuine OAuth, let the owner select the material Ava may read, and demonstrate one complete request:

> Read the email thread about the launch handover and the discussion in my selected Slack channel. Prepare a short context brief and save an unsent reply draft for me to review. Include sources and flag anything unresolved.

The topic is illustrative, not an implementation constant. The visible result should be a persisted brief and editable local draft, backed by actual provider messages. Gmail remains read-only, Slack remains read-only. Explicitly label the draft's destination as Precedent; it is not yet a Gmail draft.

This is a credible next step toward onboarding a personal worker. Public, unrestricted installation is a later product milestone. The deadline is October 12, 2026 at 11:59 PM IST; provider approval timelines cannot be shortened through implementation.

The JD allows APIs as well as browser execution, and explicitly requires avoiding real company credentials/confidential information and using sandbox/mock environments wherever appropriate. Test accounts on real services with synthetic content reconcile that requirement with an authentic integration demo. Recruiters can evaluate the existing generated workspace without granting access to their employer's systems.

## What is feasible

| Track | Assessment | Practical consequence |
| --- | --- | --- |
| Gmail test-account OAuth and selected-message reading | Feasible, subject to configured app and account consent | Set up a Gmail-enabled OAuth client and listed tester; display the actual account and granted access. |
| Slack test-workspace OAuth and selected-channel reading | Feasible, subject to app installation permissions | Register a Slack app and HTTPS callback; demonstrate channel history and replies with the chosen token type. |
| One source-backed autonomous preparation task | Feasible by extending the current harness | Add a genuine task family, connected browser surfaces, and provider-aware verification. |
| Gmail-hosted draft saving | Possible, but a separate scope and write boundary | Defer until read-only onboarding works. |
| Meeting availability from the connected account | Requires a separate Calendar integration | Gmail authorization does not supply Calendar access or coworkers' availability. |
| Recruiter connects any corporate workspace instantly | Not a defensible deadline promise | Organization policies, provider review, distribution limits, and hosted authentication remain external dependencies. |

These are engineering assessments, not results from a completed integration or a measured delivery-time estimate.

## Provider constraints that affect the design

Google lists `gmail.readonly` as restricted. `gmail.compose` also permits sending; it is not a draft-only permission. Initial local drafts therefore avoid an unnecessary additional Gmail grant. [Gmail scope reference](https://developers.google.com/workspace/gmail/api/auth/scopes).

Testing/personal-use exceptions can permit a limited demo without public verification. Public restricted-scope use can require verification and a security assessment, with review potentially taking weeks. [Google restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification). Google's Testing audience permits up to 100 listed users; Gmail authorizations in that mode expire after seven days, including refresh tokens. Reconnect must be an ordinary product state. [Manage app audience](https://support.google.com/cloud/answer/15549945?hl=en).

Google supports a server authorization-code flow and localhost development redirects. The existing Vertex ADC authorizes model inference; it does not authorize reading a user's inbox. [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).

Slack requires HTTPS OAuth redirects. Its OAuth response distinguishes bot grants from delegated user grants; persist and verify the actual workspace/user identities and granted capabilities. For this personal-worker milestone, prefer delegated user reading of selected public channels. [Slack OAuth installation](https://docs.slack.dev/authentication/installing-with-oauth/), [token types](https://docs.slack.dev/authentication/tokens/).

Do not treat top-level channel history as complete discussion context. Fetch relevant replies, follow pagination, and test actual token access. The current replies reference lists both bot and user scopes; older blanket claims about bot thread access should not replace a live capability check. [Slack replies reference](https://docs.slack.dev/reference/methods/conversations.replies/).

Slack applies stricter history/replies rates to certain commercially distributed non-Marketplace apps; internal customer-built apps have different limits. A successful internal demo does not prove unrestricted commercial distribution throughput. [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/).

Google permits productivity use cases such as generative summaries, with Limited Use restrictions. Its current policy also limits permanent copying/caching, requires encrypted credentials/data handling, and restricts broader model-training use. Use bounded retrieval rather than an indefinite inbox mirror; assess artifacts, screenshots, learning, and additional model providers as data flows too. [Google Workspace user-data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy).

## Codebase fit and missing work

The working product already supplies a strong execution foundation: ADK/Gemini, Playwright MCP, a real headed browser, visible typing, independent pointers, source-backed writes, reconciliation, persisted meeting drafts and Calendar, learning, and verification. Preserve these.

The missing work is more than adding two Connect buttons:

- `console/state.py` and launch metadata assume a generated company's URL and numeric seed. A connected workspace needs its own owner, provider identities, grant generations, and explicit mode.
- `workspace.py` and learning scopes currently identify local company instances. Account changes must not share local company memory or previous connected-account knowledge.
- `apps/mail.py` saves through meeting-specific validation. A contextual reply needs a typed draft that does not fabricate meeting fields, time options, or availability.
- `worker/goal.py` recognizes meetings and otherwise defaults toward invoices. The new preparation family needs proper routing, capabilities, context, proof keys, and receipts.
- `contracts.py` source references need connected provenance: provider, account/team, message/thread/channel IDs, retrieval time, and bounded coverage.
- `worker/gateway.py`, guards, and verification currently protect local app actions. Reuse them for browser-visible preparation; integration services must independently enforce provider scope and selection.
- `tribunal/`, model screening, and learning introduce additional data recipients and persistence. Connected content must follow an explicit inference/retention policy throughout these paths.
- The console is currently a local operator tool. Exposing it wholesale for Slack callbacks would expose runs and private workspace information. A limited HTTPS callback receiver or appropriately authenticated hosting is required.

## Recommended architecture

Human OAuth consent → server-held encrypted credentials → bounded provider reads → visibly connected Precedent Mail/Chat → Ava's existing browser execution → persisted preparation artifacts → separate verification.

The integration service retrieves provider data. Ava reads the rendered sources, types, saves, and reopens artifacts in the real browser. Keep those two kinds of activity distinct in the timeline. This does not claim Ava is interacting with native Gmail or Slack pages. Avoid browser login automation, password collection, copied cookies, or direct provider tokens in the worker's tools.

Selectors are application restrictions layered on top of OAuth. A Gmail label or Slack channel selection does not necessarily narrow the provider grant itself; explain both clearly. Default to a small recent window and explicit sources. Show freshness, counts, and incomplete coverage, not a fictional all-workspace sync.

Initial scope: Gmail reading; selected public Slack channels and replies; local brief and draft; no remote send, post, delete, invite, or hold. Private channels/DMs, Gmail-hosted drafts, Calendar, scheduled summaries, Events API ingestion, and public distribution follow only after this path is proven.

## Implementation order and human dependencies

1. Connections UI, owner/session binding, encrypted credentials, callbacks, connection lifecycle, and explicit workspace mode.
2. Genuine bounded reads from both providers, connected Mail/Chat, provenance, retention, and source coverage.
3. Autonomous contextual preparation, independently checked persisted artifacts, real-model browser demos, screenshots, and reproducible documentation.

Human setup is unavoidable: Google OAuth client/consent configuration and test-account consent; Slack app registration, redirect configuration, and authorized installation. An HTTPS callback address is needed for Slack. Admin restrictions cannot be solved with code. Prepare exact setup instructions and complete independent implementation while consent is pending; never count fixture tests or manually supplied tokens as successful OAuth onboarding.

The companion implementation handoff is [astra_gmail_slack_onboarding_milestone.md](prompts/astra_gmail_slack_onboarding_milestone.md). It uses an outcome-led prompt with clear boundaries and completion evidence, consistent with [OpenAI's Astra prompting guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).
