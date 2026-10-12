# Precedent

An autonomous company workspace: Ava reads company records and operates real applications through Google ADK and Playwright MCP. She supports invoice entry/routing and meeting preparation with persisted email drafts and local calendar holds, and she works in the owner's own Gmail and Google Calendar in a browser the owner signed into. Ava retains run evidence, gates writes, and checks the resulting state. Unsupported checks remain unknown.

> Focused browser prototype for the CentrAlign internship take-home. The original problem statement governs requirements.

## Ava in your own Gmail and Calendar

Ava reads the generated company in one tab, then opens real **gmail.com** and
**calendar.google.com** in others, in a Chrome profile you signed into yourself. She leaves
a draft in your Gmail and a hold on your calendar. She cannot send, invite, delete or discard.

Example request, run live on 2026-10-12 (run `20261011-210344-d343`, 158 s):

> Draft a mail to (your address) informing about the latest bill and vendor details and
> summarising the chat messages inside #design, and put a 30 minute hold on my Google
> Calendar next week to review it.

Ava's own read-back from Google passed 13 of 13 checks, and so did the Tribunal reading
Google itself. Other retained runs: Gmail only (`20261011-204107-0722`, 7 of 7), Calendar
only (`20261011-205136-04cf`, 6 of 6), combined (`20261011-205309-0816`, 13 of 13).

**One-time setup**

1. Connect your Google account for read-only proof (Gmail read and drafts, Calendar),
   as described in [the connected worker milestone](docs/google_connected_worker_milestone.md):

   ```sh
   uv run precedent connected
   ```

2. Sign into Google in Ava's own Chrome profile, by hand, then quit that window (Cmd+Q).
   Neither Ava nor any tool sees your password:

   ```sh
   open -na "Google Chrome" --args --user-data-dir="$HOME/.local/share/precedent/ava-chrome" --no-first-run "https://accounts.google.com/ServiceLogin?continue=https://mail.google.com/mail/"
   ```

   Both must be the same Google account: Ava writes in the browser account and the checks
   read the connected one.

**Run it**

```sh
PRECEDENT_NATIVE_GOOGLE=1 .venv/bin/python scripts/demo.py --port 8041 --apps-port 8141 --world-root output/native-demo --reuse
```

Open http://localhost:8041/, paste a request like the one above and press **Assign to
Ava**. Her Chrome window opens on your screen. For the first run at a new path, omit
`--reuse`. Keep reusing the same path afterwards: a regenerated company is a different
company, and the Tribunal refuses to judge a run against another company.

**What keeps it safe.** Google's traffic does not pass through Ava's gateway, so the rules
are code on her browser actions (`src/precedent/worker/native.py`):
- **Sites:** she may visit only the company apps, Gmail and Google Calendar. Sign-in and
  account pages are refused.
- **Controls:** Send, Forward, Delete, Discard, Archive and Invite are refused, and so are
  keyboard shortcuts.
- **Decisions:** a decision citing sources is required before her first keystroke.
- **Recipients:** only addresses named in the request, including addresses prefilled
  through a link. No guests can be added to events.
- **Company apps:** read-only for the task.

In the live run, Ava reached for **Discard draft** after writing; the rule refused it and
the draft was kept.

**How it is proven.** Nothing is taken from Ava's report. The draft, the Sent folder and
every calendar change during the run are read back through the read-only connection,
bounded to the run's own time window:
- **Draft:** exactly one new draft to the named recipient, with a subject.
- **Content:** the latest bill's facts and the vendor details match Books, and the #design
  messages are covered.
- **Nothing sent:** the Sent folder has nothing new, and no other recipient appears.
- **Hold:** exactly one new event, of the requested length, inside the requested window and
  working hours, with no overlap, a title and no guests.
- **Nothing else changed:** no other calendar event was created, changed or deleted.

The Tribunal repeats these checks with its own reads, and its jury reads the draft and the
calendar changes as exhibits.

**Limits.**
- The #design check confirms coverage of the messages, not the faithfulness of the summary;
  the jury can still flag an unfaithful one.
- Ava reads Google's pages through their accessibility tree.
- Running Chrome with remote debugging on a signed-in profile is a local prototype choice,
  not a deployment design.
- Ava cannot delete her drafts or holds; you remove them yourself.

The [meeting workflow milestone](docs/meeting_workflow_milestone.md) adds a Calendar app,
editable unsent email drafts, fresh availability checks, and explicit local tentative holds.
Its delivery report records real browser runs, restart/repeat evidence, independent grades,
screenshots and the limitations of this local sandbox.

The retained meeting demo is [Ava's task workspace](http://localhost:8018/) with
[company Calendar](http://localhost:8124/calendar/?start=2026-10-05) and
[the saved draft](http://localhost:8124/mail/drafts/draft-1e9d559df51d).
Choose **Prepare a catch-up**, then **Assign to Ava**, and bring her browser forward.
The generated company clock is September 28, 2026; “next week” is October 5–11.
Restart that company without regenerating it:

```sh
.venv/bin/python scripts/demo.py --port 8018 --apps-port 8124 --world-root output/meeting-milestone/verified-worlds --reuse
```

For a fresh company at a new path, omit `--reuse`; `--seed 8` also changes the participant,
topic and calendar fixtures. Choose available ports. Draft preparation sends nothing;
a requested local hold reserves the organizer's time only.

The current [trustworthy learning milestone](docs/trustworthy_learning_milestone.md) adds
persistent scoped memory, Ava’s mind, reviewed invoice skills, and stricter verification.
Its cold task and post-restart different-invoice task both passed worker verification and
14/14 independent checks. The measured warm task was slower overall; memory reuse is
proven, a general speedup is not. Earlier milestone figures below are historical evidence.

The [immersive workspace milestone](docs/immersive_milestone.md) adds focused task assignment, a guided introduction, truthful preparation phases, native-browser handoff, decisions with sources, and inspectable results. Its real invoice run completed in **170.4 seconds**, passing **13/13 independent grading checks**. Ava's own fresh verification passed **5/7 checks**, with two explicitly unresolved.

Start a fresh isolated demo after setup and ADC authentication:

```sh
.venv/bin/python scripts/demo.py --port 8009 --apps-port 8116
```

Open http://localhost:8009/, select **Enter & route an invoice**, then **Assign to Ava**. Use **Bring Ava’s browser forward** to watch actual execution. Return for the saved bill and checks. Existing companies are preserved. See the milestone guide for evidence and limitations; the [earlier observable demo](docs/observable_browser_demo.md) remains historical evidence.

## Meet Ava: the landing page

Open **Start here** in the workspace, or `/guide` on any console. It is the project in eight
chapters, built from recorded evidence: Ava's own browser frames from a real run, the rules
she induced from the company's history (and the stale procedure she caught), the loop as
recorded events, the write gate, the Tribunal, memory and taught skills, Ava in your own
Gmail and Calendar (with personal details blurred), and a wall of real runs, failures
included. **Let Ava show you around** plays a three-minute narrated tour; in
the Tribunal chapter Loki joins her for a voiced scene scripted from run `dd3f`, where the
exhibit, the branches and the pruning follow the dialogue. Without the tour, Ava hops to the
chapter you are reading. Reduced motion shows everything still.

The numbers and images come from `src/precedent/console/guide_evidence.json`. After new runs:

```sh
.venv/bin/python scripts/build_guide_evidence.py
```

Narration (Ava: Sulafat, Loki: Algieba, Gemini-TTS through ADC) is versioned by script; after
editing `guide.json`, regenerate and activate it:

```sh
.venv/bin/python scripts/generate_guide_audio.py
```

```sh
.venv/bin/python scripts/generate_guide_audio.py --activate
```

The same Ava appears across the product: a dock in every company app, the task home, the run
page and her own worker browser. Select her for suggestions from the record you are looking
at; they only prefill the task composer. See [the companion milestone](docs/companion_milestone.md).

## Ava’s mind and persistent learning

Open **Ava’s mind** in the header, or `/mind`. Completed tasks produce learning notes
with observed checks, reusable guidance, uncertain claims and captured sources. Search,
correct or archive those notes. In **Skills**, review an invoice procedure draft, run its
real isolated sandbox validation, then explicitly activate it. Subsequent invoice tasks
show which skill and memories were used and still check current company sources.

`uv sync` installs the ADK database extras. Local learning is stored in `learning/` beside
`runs/` (override with `PRECEDENT_MEMORY_ROOT`). These files are gitignored and separate
from the company's database. Session history, curated recall and skill provenance use
separate SQLite stores. This is local single-user persistence, not cloud onboarding.

To retain the same demo company across a restart:

```sh
.venv/bin/python scripts/demo.py --port 8016 --apps-port 8122 --world-root output/learning-milestone/demo-worlds --reuse
```

Omit `--reuse` only for first creation at a new path. Regenerating a company intentionally
creates a new memory scope. Never use world regeneration to restart a retained demo.
The labelled `scripts/seed_learning_invoice.py WORLD_DIRECTORY` fixture adds a different
source invoice for demonstration, without creating a bill or a learned answer. See
[the learning milestone](docs/trustworthy_learning_milestone.md) for the reviewer route,
actual run evidence, independent assessments and limitations.

## Google Cloud authentication

Gemini is accessed through Vertex AI using Application Default Credentials (ADC).
A Gemini API key is not required. Goal preparation, actions and fallbacks all use
the same ADC model factory. The configured model names are unchanged.

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then run:

```sh
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Set these values in `.env` (or export them in your environment):

```sh
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
```

The runtime identity needs Vertex AI inference access, normally `roles/aiplatform.user`,
and permission to use the configured project for quota/billing
(`serviceusage.services.use`, normally `roles/serviceusage.serviceUsageConsumer`).
An administrator can enable the API and grant these permissions; runtime identities
do not need Owner or Editor.

Verify with one small model request:

```sh
uv run precedent check-model
```

Expected response: `Vertex ADC works`. No company records are accessed or changed.
Restart the console after changing `.env`. Production should use an attached
service identity or Workload Identity, rather than a developer's local ADC file.
See the [authentication guide](docs/google_cloud_auth.md) for Docker, CI, model
compatibility, IAM and the migration validation results.

## Open the delivered workspace

With the existing seed-7 company, use two terminals:

```sh
uv run precedent apps --seed 7 --port 8101
```

```sh
PRECEDENT_APPS_URL=http://localhost:8101 uv run precedent console --port 8000
```

Open [the company workspace](http://localhost:8101/) or [Ava's task inbox](http://localhost:8000/).
For a local demo showing the actual browser rather than a streamed image, start
the console with `--headed`. Assign a task in the inbox, then switch to Ava's
Chromium window. Playwright controls that same visible browser session. The
browser starts on the company overview during preparation. Text entry uses actual character-by-character keystrokes. Ava's purple cursor
moves to the control selected by the model and pulses on clicks; your mouse
movement does not drive it. Native dropdowns and segmented date controls use
Playwright's format-aware input after the pointer reaches the control. This is
an accessibility-guided browser agent; it does not infer actions from pixels. The window closes when the run finishes; its recorded
evidence remains in Tasks.
The legacy optional image-stream viewer is separate from native viewing. For that viewer, open `/watch` on the same console in a second tab before
starting a task. It follows that console's active task automatically and shows
the run's dedicated continuous browser stream. This viewer reconnects after
interruptions and never substitutes saved captures. After completion, open Task
details for the outcome and recorded evidence; return to `/watch` for the next task.
The console supports one active worker and actual isolated-browser captures. Starting a task
uses the configured model. Context induction and fresh verification are implemented; coverage is bounded by the supported check primitives. Multi-seed eval orchestration remains unfinished. The [live ADC workspace validation](docs/vertex_adc_e2e_validation.md)
confirmed model access and browser execution, but the task failed to complete
before its token limit. The scripted replay is labelled separately.

See [the delivery guide](docs/workspace_implementation.md) for exact desktop launch
settings, the labelled scripted replay, before/after screenshots, 133 passing tests,
lint results, the Act 1 walkthrough and remaining limits.

## First installation

```
make setup            # uv sync, npm ci (Playwright MCP; needs Node 18+), Chromium, .env
make world SEED=7     # first generation only; overwrites that world's existing data
make apps SEED=7      # Mail, Books, Drive, Chat on http://localhost:8100
make console          # product screen on http://localhost:8000
```

The original [CentrAlign problem statement](../JD%20CentrAlign%20AI_Engineering%20Hiring.docx)
is the source of truth for assignment requirements. Earlier kickoff briefs are
historical guidance. See `docs/01_architecture.md` for the design.

## Real Google workspace

`uv run precedent connected` opens the owner-private Google workspace on port 8250, with an OAuth callback-only listener on 8251. A configured Web OAuth client lives outside the repository; normal users connect through Google consent and choose Mail/calendar access in the app. Ava operates real Precedent views backed by official Gmail/Calendar APIs, saves unsent Gmail drafts, and creates only explicitly requested owner-only calendar holds. Native outputs have independent fresh provider checks and account-scoped learning.

Actual consent, restart, autonomous Calendar creation, repeat reuse and lost-acknowledgement recovery have live evidence. Gmail and composed meeting acceptance are awaiting the synthetic incoming demo email; this milestone is not yet fully accepted. See [the current Google milestone results](docs/google_connected_worker_milestone.md) for exact gate status, launch details, real run IDs, recordings, tests and remaining work.
