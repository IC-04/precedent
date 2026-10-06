# WS7: Submission: README, demo video, write-up

> Start a draft on day 2 and finish it on the last day. Paste this into a Claude Code session.

## The JD's submission list (every item must be present)

1. GitHub repository
2. README with setup and run instructions
3. Short explanation of the architecture
4. Important technical and design decisions
5. Demo video or live demo
6. Known limitations
7. What we would build next
8. Assumptions
9. Models, APIs, frameworks, external services and pre-built components used

## README outline

1. **Precedent in one paragraph**, plus the one-line demo claim.
2. **Quick start:** `uv sync`, `uv run playwright install chromium`, `cp .env.example .env`, `make world`, `make apps`, `make console`, then open `http://localhost:8000`.
3. **What to try:** Act 1, the ghost run, Act 2 with the crash hook, and switching to Globex.
4. **Architecture:** the diagram from `docs/01_architecture.md` and five sentences.
5. **Design decisions:** from `docs/decisions_log.md`, each with a "why".
6. **How it maps to the brief:** the traceability table.
7. **Evaluation:** the real results table from `precedent eval`, with seeds, repeats and cost. No invented numbers.
8. **Limitations:** honest and specific (browser snapshot instead of pixels, one domain, synthetic company, scripted human answers in eval, cost per task).
9. **Next:** pixel computer-use mode, real connectors, learning precedents from feedback over time, multi-task scheduling.
10. **Assumptions** and **components used**: the model provider and model IDs actually used (Gemini by default), the Google Gen AI SDK, the OpenAI SDK for open models, Playwright, FastAPI, Jinja2, SQLite, fpdf2, pypdf, uv.

## Demo video (under 5 minutes)

Follow the vision document's three-minute demo table. Then add up to 90 seconds of evaluation results and the code tour: `runner.py`, `failures.py`, `verify.py`, `grade.py`. Record unedited runs; mark speed-ups on screen. Keep the full raw recording as a second link.

## Interview prep (one page in `docs/interview_notes.md`)

- Why snapshots instead of pixels; why no framework; how the grader is independent.
- Live-change drills we can do in 5 minutes: add a failure class; add a check primitive; add a planted trap to the template; switch the model.
- Known weak spots and what we would do about them.
