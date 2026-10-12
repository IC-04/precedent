# Ava as the workspace companion

Implemented October 9, 2026. The CentrAlign problem statement governs scope; the
deadline is October 12, 2026, 11:59 PM IST. This milestone changes presentation, task
entry and narration. Planning, decisions, verification and grading are unchanged.

## Try it

- Guide and tour: http://localhost:8012/guide (console), company apps on http://localhost:8118.
- Shortest reviewer route:
  1. On the guide, press **Let Ava show you around**. Change chapters, scroll yourself, press **Follow Ava**.
  2. Open Mail in the company apps, open the latest invoice message, select Ava (bottom right), choose a suggestion, **Review in task composer**.
  3. Review the prefilled composer and **Assign to Ava**. Watch her Chrome for Testing window and the run page.

Start another isolated demo with `.venv/bin/python scripts/demo.py --port 8012 --apps-port 8118`.

## What changed

### One Ava, eleven poses

`src/precedent/apps/static/ava/ava.svg` is the only drawing and `ava.css` the only pose
vocabulary. The console, the company apps and the worker overlay all use them;
`precedent/companion.py` server-renders her (so pages show her without JavaScript) and
owns the mapping from recorded run state to a pose.

| Pose | Drawn as | Shown when (recorded evidence) |
| --- | --- | --- |
| idle | breathing, blinking, an occasional ear twitch | nothing is running |
| greet | a small wave, four beats, then a smile | a person opens her panel |
| listen | head tilt, ears up, sound arcs | her panel is open, or an answer was submitted |
| speak | moving mouth | guide narration is actually playing |
| read | holding a page | preparation reads, or a `browser_snapshot` action |
| think | hand to chin, thought dots | a model turn is pending (`model_wait`) or an action has been observed and the next is not chosen yet |
| work | typing at a little laptop | a browser action has been recorded and not yet observed |
| check | a page under a lens | the run is in fresh verification |
| ask | hand up, question bubble | an unanswered question event |
| deliver | holds up a sealed page | finished, and every goal condition freshly verified |
| away | ears down, eyes closed, colour lowered | stopped, interrupted or unreachable |

Delivery is never shown for an unknown or failed result: a worker's pass claim that is
not freshly verified maps to idle with "Work returned · some checks remain open".
Personality lines ("A little less busywork.", "One tab at a time.") are fixed copy shown
only when nothing operational needs saying. No model call produces companion text.

### A continuous tour

Before: `guide.js` measured each perch with `getBoundingClientRect` on every scroll
event, wrote fixed `left/top`, and started a separate SVG hop alongside a native smooth
`scrollIntoView`. A per-frame trace showed why it felt rough: on every chapter change
Ava teleported 567–590 px in a single frame (the perch was measured before the scroll
moved it), and she vanished for 12–48 frames when crossing the viewport edge.

After: one cancellable transition drives both the viewport and Ava from one clock.

- Between moves she sits in-flow inside the chapter's perch. Scrolling, resizing, zoom
  and font loading move her with the layout; there is no scroll listener.
- A move lifts her into a fixed layer exactly where she is, then: anticipation squash
  (14%), an arc that leans toward the destination, a small landing squash, a calm
  speaking pose. She travels in screen space to where the perch will be when the scroll
  ends, so she stays on screen even across a 2,000 px move.
- Layout is read once per frame and then written; transforms only.
- A new chapter mid-flight retargets from her current position. Wheel, touch or
  scrolling keys stop auto-scroll on that frame and re-base her flight to land where the
  page now is. **Follow Ava** flies her back; if she is off screen she enters from the
  nearest edge, above the tour player, never behind it.
- The next clip starts at 70% of the move, when the landing is visible.
- Stop, hidden pages, navigation and active work cancel transitions. Scrubbing never
  moves the viewport. Reduced motion places her without travel; auto-scroll starts off.

Measured with the same trace (`output/companion-milestone/{before,after}/motion-profile.json`,
and `validation/validation.json`): chapter changes now move at most 4 px per frame with
no hidden frames; the departure from the large hero peaks at 22 px per frame while she
shrinks to perch size.

### Ava in every human-facing page

- Company apps: a dock (74 px, 54 px on phones) in the shared shell, so overview, Mail,
  Books, Drive, Chat and every record and form page have exactly one Ava. Pages reserve
  space below their content so she never covers controls; the validation checks every
  page at 1440 and 390 px for overlap with links, buttons and fields.
- Console: a dock on the task home; inline on the run page (beside the activity line)
  and in the guide hero. One Ava per page.
- She is a real link to the composer without JavaScript, a button with `aria-expanded`
  with it. Escape closes her panel and returns focus. **Tuck Ava away** shrinks her to a
  small round tab and is remembered per origin (browser storage; the console and company
  apps are separate origins and are not synchronized).

### Starting the right task

Selecting Ava waves, then opens a compact panel: a draft field, two suggestions from the
record on screen, and **Review in task composer**. Suggestions use visible identity only:

| Surface | Context | Suggestions |
| --- | --- | --- |
| Mail message | sender address exactly matching an active vendor | enter and route that vendor's latest invoice; read-only duplicate check |
| Books bill | vendor and invoice number | is this invoice recorded more than once (read-only); enter the vendor's latest invoice |
| Books vendor | vendor name | enter and route; duplicate check |
| Drive file | PDF that arrived as a mail attachment | enter the invoice in this file and route it; is it already recorded (read-only) |
| Chat, overview, lists | none | the same two families with a `[vendor]` placeholder that must be replaced |

Only the validated families (invoice entry and routing, read-only duplicate checks) are
offered. Email sending, scheduling, Gmail or Slack access and skills are not offered.

Nothing starts from the panel. On the console, the draft goes straight into the composer
(same origin). From the company apps, the browser never posts across origins:

1. A same-origin `POST /ava/handoff` stores the bounded draft and context in the company
   apps process under a random one-time token (10 minutes, at most 50). Requests carrying
   the worker's agent header, a foreign `Origin` or `Sec-Fetch-Site: same-site/cross-site` are refused.
2. The browser navigates to `{console}/compose?handoff=<token>`.
3. The console fetches the draft server-to-server from **its own configured** company URL,
   checks that it came from the company instance it serves, and renders the composer
   prefilled with a note "Drafted with Ava from Drive · FIG-1842.pdf. Nothing has started."
   The URL is then replaced with `/#request`.

A reused, expired or foreign draft shows an honest message and assigns nothing. With an
active task, the panel offers **Return to Ava’s task** instead; one active worker and the
console's duplicate refusal are unchanged. If the console is unreachable, the panel says
so, disables handoff and keeps the draft.

Binding fix: a company's `world_id` is a hash of its seed manifest, identical for every
fresh seed-7 company, so the fresh demo's dock showed a retained run from another company.
`instance_id` adds the company directory; run status and drafts bind to it.

### Ava in her working browser

`worker/screen.py` inlines the shared drawing into the existing overlay: an aria-hidden
host, a closed shadow root, no pointer events, and no listeners for human input. Trusted
runner callbacks send ordered states: preparing (read), each model turn (think), each
browser action with its caption from the tool's own arguments (work, or read for a
snapshot), record decision (think), question (ask), verification (check), and the
outcome (deliver only for a fresh pass; idle; or away when stopped). Each update is a
single bounded evaluate (1.5 s cap) and adds no model calls. A late, older state is
ignored. The human panel, task buttons and run summaries never render for the worker: the
company apps omit them whenever the agent header is present.

`tests/test_ava_overlay.py` runs real Chromium with Playwright MCP: every state renders;
an older state cannot overwrite a newer one; human pointer and focus cannot move her
pointer or pose; the model's snapshot contains the business controls and none of the
companion text; MCP clicks and typing still reach the form; the state survives reloads
with one host.

### A warmer narration

The five chapters were rewritten as conversation (same facts) and performed by Google
Cloud **Gemini-TTS** (`gemini-2.5-pro-tts`, voice **Sulafat**) with a written delivery
direction and a few `[short pause]` tags, through the existing ADC path. The direction:

> You are Ava, a friendly colleague welcoming one person into a shared workspace. Speak
> warmly and relaxed, with a slight smile you can hear. Use a natural, conversational
> rhythm and vary your emphasis; let short pauses separate ideas. Be confident and clear,
> gently playful, and sincere when you explain limits. Not a sales announcer and not a
> cartoon. Keep the same character throughout.

Selection. Three short samples of the same introduction were generated before the full
tour (`output/companion-milestone/voice/`, with the current Chirp clip for comparison).
No audio-listening tool was available, so the choice used measurements, not listening:

| Sample | Pitch spread, p10–p90 | Pitch std | Pauses > 180 ms | Length |
| --- | --- | --- | --- | --- |
| Current Chirp 3 HD Aoede (older, shorter script) | 10.3 st | 3.96 st | 8 | 12.3 s |
| Gemini Pro + direction, Aoede | 8.7 st | 3.27 st | 10 | 16.6 s |
| Gemini Pro + direction, Sulafat | 12.7 st | 4.80 st | 9 | 18.5 s |
| Gemini Pro + direction, Achird | 14.4 st | 5.74 st | 9 | 16.7 s |

Sulafat varied the most among female voices, keeping Ava's established voice identity
(Achird is a male voice). Autocorrelation pitch tracking can over-count octave errors;
treat these as proxies. **Please audition the samples**; switching voice is a one-line
change in `guide.json` followed by regeneration.

Versioning. `guide.json` holds the voice (provider, model, voice, language, direction)
and each chapter's `narration` (the transcript) and optional `performance` (the same
words plus pause tags; a test enforces identical words). Each chapter's cache key covers
all of these. `scripts/generate_guide_audio.py` writes a new `v-<hash>/` folder and
`manifest.next.json`; `--activate` checks every chapter and switches with one rename. The
page serves narration only when every chapter matches: all or none. Durations come from
the MP3 frames (79 s in total) and the page still uses the media element's real duration
for progress. The previous Chirp clips are kept in `legacy-chirp3-aoede/`.

```sh
.venv/bin/python scripts/generate_guide_audio.py --check
.venv/bin/python scripts/generate_guide_audio.py --sample output/voice --candidate candidate.json
.venv/bin/python scripts/generate_guide_audio.py            # pending version, may incur charges
.venv/bin/python scripts/generate_guide_audio.py --activate
```

## Validation

- `pytest`: 216 passed (203 before this milestone). Ruff check and format pass. New: `tests/test_companion.py`
  (poses, context bounds, script-safe JSON, one Ava per page, no Ava for the worker,
  handoff origin rules and one-time use, composer prefill without launch, foreign
  company refusal, instance binding) and `tests/test_ava_overlay.py`; guide tests now
  cover all-or-nothing versioning, invalidation by voice/model/direction, transcript
  integrity and manifest path safety.
- `scripts/inspect_companion.py` (real Chromium, 45 checks, no browser errors, no task
  POSTs): continuous travel for start and five chapter changes; narration resumes after
  each move; scrubbing never scrolls; pause; wheel interruption mid-move; Follow Ava;
  resize mid-move; hidden page; natural chapter end; stop; active work (fixture);
  keyboard open and Escape; audio failure; 390 px; reduced motion; every company page at
  1440 and 390 px with one Ava clear of controls; suggestions send no POST and change no
  records; navigation and history keep one Ava; tucking persists; unreachable console
  (fixture) keeps the draft; active task (fixture) returns to the task; handoff prefills
  the composer with exactly one same-origin POST.
- Fixtures are routed responses for active, unreachable and failed-audio states. They are
  labelled in `validation.json` and never presented as live agent work.

## End-to-end run in a fresh company

Run `20261009-131448-21dd`, a freshly generated company (seed 7, its own instance), the
configured Gemini model through Vertex AI and ADC, headed Chrome for Testing. Driven by
`scripts/e2e_companion_run.py`; evidence in `output/companion-milestone/e2e/`.

- Started from Ava in Mail: on the latest invoice message she offered "Enter & route
  Figma’s latest invoice" (the vendor came from the sender address). The suggestion and
  handoff sent one same-origin draft POST and no task; the composer showed the draft;
  one explicit **Assign to Ava** started exactly one run.
- While active, a second submission was refused (HTTP 409), and the company apps' dock
  offered **Return to Ava’s task** with the run's link.
- The run page's companion followed the recorded events: read (preparation), think
  (each model turn), work with the action's own caption ("Clicking Figma Billing Invoice
  FIG-1842 link", "Typing into Amount textbox", "Clicking Request approval button"),
  check (verification), then idle. 54 pose changes in 184 s; none came from elapsed time.
  Ava's own browser showed the same states (14 frames in the e2e folder).
- Duration 182.7 s. Ava created bill INV-921 for FIG-1842, attached the invoice, chose
  account 1400 and requested approval from the CFO.
- **Ava's own fresh verification:** 6 verified, 1 failed, 1 unknown. The failed check
  compared the attachment's file id (`f-0004`) with the link text on the bill page
  (`FIG-1842.pdf`): a verifier false failure. "Vendor settings unchanged" stayed unknown
  because the vendor page was not read earlier in the run. The companion therefore ended
  on "Work returned · a check failed", not delivery.
- **Independent grade (separate, privileged):** 13/13 pass, including the attachment
  file id and checksum, the approver, pending approval, no other bills and no vendor bank
  change.
- Found and fixed during this run: on a 390 px screen, bills created at run time (longer
  timestamps) made the Books record page overflow sideways; the grid column can now shrink.

## References

- Official: Google Cloud [Gemini-TTS](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts),
  [Chirp 3 HD](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd) and the
  [synthesize API](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize):
  request fields `input.prompt`, `voice.modelName`, pause tags, MP3, ADC with a quota project.
- OpenAI's help article on its companion ([Getting started](https://help.openai.com/en/articles/20001530-getting-started-with-your-dot))
  refused automated access (HTTP 403) and was not read. Secondary reporting
  ([Engadget](https://engadget.com/2162796/openai-introduces-ai-generated-pets-for-its-codex-app),
  [penchan.co](https://penchan.co/en/ai/coding/codex-pets/)) describes Codex/ChatGPT pets
  as floating companions that show what the agent is doing and whether it needs input,
  with a small set of states. These informed the principle (ambient, state-legible, quiet)
  only. Community galleries are community material. No pet plugin or pet API was used;
  Ava's drawing and behaviour are original.
- Existing captures in `../output/design-references-2026-10-08/` (Linear documents and
  interface) continue to inform the guide's document layout.

## Limits

- Narration quality was chosen by measurement, not by ear. Please listen.
- The worker's attachment check can fail falsely (id compared with displayed name); it is
  reported, not hidden, and fixing verification is outside this milestone.
- Suggestions offer two validated task families. Their variants for a specific bill or
  Drive file were not each run end to end; the run below used the Mail suggestion.
- Preferences and drafts are per origin. Tucking Ava in the company apps does not tuck her
  in the console.
- The company-app dock learns about active work by polling every 5 seconds.
- The worker overlay covers the bottom-left corner of Ava's viewport for viewers; the
  input executor already keeps click targets out of the bottom 90 px.
- Memory, skills, onboarding, email drafts and calendar remain planned.
