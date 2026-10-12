# Project guide and Ava’s voice

> Superseded in part by [the companion milestone](companion_milestone.md): the tour now
> moves on one clock, narration uses Gemini-TTS (Sulafat) with versioned, all-or-nothing
> assets, and the regeneration commands below changed. The rest is historical record.

Implemented October 9, 2026. The original internship problem statement governs the
scope; the user-updated deadline is October 12, 2026, 11:59 PM IST.

## Try it

The current fresh demo is at **http://localhost:8012/guide**, with company apps at
http://localhost:8118. Open **Let Ava show you around**, then **Give Ava a task**.
The latter focuses the existing task composer; it never starts a run automatically.
The home sidebar’s **Start here** and **Meet Ava** both open the guide. Run pages
also have a guide link.

To start another isolated demo after the usual setup:

```sh
.venv/bin/python scripts/demo.py --port 8012 --apps-port 8118
```

Use free ports if these are already occupied. The guide route is `/guide` on any
console. Existing companies and retained runs are preserved.

## Experience

The page is a readable project document: an introduction, actual worker loop,
company apps, historical evidence, explicitly planned memory/skills and deeper
architecture and limitations. Its lavender companion is an original SVG with
breathing, blinking and a speaking state tied to actual audio playback. Reduced
motion disables its animation.

The five-chapter introduction lasts **61.296 seconds**. It is identified as scripted
synthetic narration, not live worker speech or reasoning. Audio starts only on an
explicit interaction. Controls support pause/resume, stop/reset, chapter selection,
seeking and mute, with a readable chapter transcript. Progress comes from the media
element's actual duration/currentTime. There is no claimed word-level alignment.

Narration pauses when the page is hidden, navigation leaves the guide, or the
console reports a managed active task. Active-task detection polls every four
seconds while visible and checks again before user-triggered playback and automatic
chapter transitions; this is not an instantaneous cross-tab guarantee. The CTA then
returns to the existing task. No narration auto-resumes after the task ends.

## Content and audio

`src/precedent/console/guide.json` is the shared source for chapter text and scripts.
The engineering disclosure and evidence audit remain readable page sections.
`scripts/generate_guide_audio.py` uses the existing Google Cloud ADC configuration
and the separate Text-to-Speech API. Access and the selected voice were checked
before synthesis. Voice: **en-US-Chirp3-HD-Aoede**. Credentials are never embedded
in the page. Five generated MP3 files and their script-hash manifest live in
`src/precedent/apps/static/audio/guide/`; page visits make no TTS requests.

```sh
.venv/bin/python scripts/generate_guide_audio.py --check
.venv/bin/python scripts/generate_guide_audio.py
```

The first command only checks access. The second generates missing or changed
chapters and can incur Google Cloud TTS charges. It skips unchanged scripts and
voices. The page omits an audio URL if the current script hash does not match the
asset manifest, preventing stale narration after a content edit. If audio is absent
or fails to load, the written guide and transcripts remain usable. No browser voice
fallback is silently substituted.

The original bill link comes from the retained run's original company address,
not the fresh demo company. A fresh checkout without that run says the evidence
is not installed. The guide preserves the independent 13/13 evaluation versus the
worker receipt's reported 5/7, and discloses the additional bundled-condition
coverage gap. The worker and verifier were not changed in this milestone.

## Validation and evidence

- 25 targeted guide and console tests passed. Tests cover read-only guide loading,
  active-task navigation, original-company evidence links and stale audio rejection,
  alongside the existing task submission/console tests.
- Chromium decoded and played all five real MP3 assets. Pause/resume, mute,
  chapter changes, seek, automatic progression, completion and restart were checked.
- A controlled active-task response stopped narration and updated the CTA. A
  deliberately failed audio request showed the transcript instead of breaking the page.
- Visual checks at 1440×900, 1280×800 and 390×844 found no horizontal overflow.
  Keyboard start/pause and the mobile player were checked. Reduced motion was
  checked; browser errors and unintended task POSTs were zero.
- The retained result, original saved bill and four company links returned HTTP 200.
- No new paid agent execution was needed: the task/worker lifecycle is unchanged.
- No audio-listening tool was available. Browser playback and decoding were verified;
  perceived voice quality has not been independently auditioned by the coding agent.

Screenshots and machine-readable results: `output/guide-milestone/`.
`scripts/inspect_guide.py` is a repeatable local browser check using port 8012.
Controlled fixtures exercise failure/task states and are not presented as live agent work.

## References and design choices

[Linear documents](https://linear.app/docs/documents) informed the persistent
workspace navigation, document hierarchy, section links and separation of project
context from execution. [Notion's wiki documentation](https://www.notion.com/help/wikis-and-verified-pages)
informed the readable text and disclosure of source validity. The result uses the
existing Precedent palette and an original companion rather than copied branding.
Existing official-interface captures in `../output/design-references-2026-10-08/`
were visually reviewed (`01-linear-workspace.jpg` and `12-linear-finished-interface.jpg`).
The current Linear document reference was readable through web research, but a new
browser capture timed out; no new reference capture is claimed.

Audio implementation follows Google's [Chirp 3 HD documentation](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd)
and [synthesis API](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize).

Persistent memory, skill promotion, onboarding, email drafts and calendar remain
planned. Their design is in [the memory research](memory_skills_research.md).

## Visual story follow-up

The five chapter sections now lead with diagrams and a labelled saved browser
capture, with longer explanations under **The details**. The capture is a still
from the retained run, not a simulated live feed or a video recording. Illustrated
workflow panels are labelled separately from historical evidence.

Starting narration scrolls to its chapter. Ava hops into a reserved space next to
that chapter and follows the page as the tour advances. Visual emphasis uses the
actual audio position within the chapter; it is conceptual pacing, not word-level
alignment or live task progress. **Auto-scroll on / Follow Ava** controls following.
Wheel, touch scrolling and scrolling keys give control back to the reader; selecting
Follow Ava returns to the current chapter. Reduced-motion users start with auto-scroll
off, with no hop animation. Stop restores Ava to the introduction. Active work still
interrupts narration and clears the touring companion.

The existing voice files are reused; this follow-up made no TTS or agent inference
calls and did not change worker execution.
