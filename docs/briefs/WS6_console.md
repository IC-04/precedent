# WS6: Console (the "Watching Ava work" screen)

> Paste this into a fresh Claude Code session in the repo root.

## Goal

Write `src/precedent/console/`: a FastAPI app on port 8000 that is the product screen in the demo. It shows a run live, from its event log, the way the vision's main-screen figure does.

## Read first

`docs/03_contracts.md` §5 (events), the "Watching Ava work" page and the evidence receipt page in the vision PDF, `contracts.py`.

## Layout (one page per run, `/runs/{id}`)

- **Top bar:** Precedent, company name, worker, and "N tasks running, M questions waiting".
- **Left column:** the task list, with each task's status line. Below it, any open question (`question` event) with answer buttons that POST to `/runs/{id}/answer`. Below that, a company-context summary: precedents with their status words.
- **Middle column:** the latest screenshot ("Ava's screen" plus the current URL), then the latest decision record (Observed, Means, Decided, Expects).
- **Right column:** the goal contract, grouped as "Confirmed", "Being written", "Still to do" and "Must not happen"; then the plan with done and current steps.
- **Bottom strip:** the steps of this task as a row of labels.
- **When finished:** the receipt replaces the middle column (rendered from the `receipt` event), with a link to `receipt.md`.

## Behaviour

- `/`: a task inbox with a text box for a natural-language request, a seed picker and a worker picker (Precedent or baseline). Starting a task launches the runner as a subprocess.
- `/runs/{id}/events`: server-sent events tailing `events.jsonl`. The page updates in place with vanilla JS.
- `/runs/{id}/shots/{n}.png` serves screenshots.
- `/compare?a=<run>&b=<run>`: a side-by-side ghost-run view showing two receipts and a field-by-field difference.

## Visual rules (from the vision document)

- Black on warm white, one blue accent for what Ava inferred, decided or verified.
- Source Sans 3 for the UI, IBM Plex Mono only for record IDs.
- No ticks, crosses, coloured status pills or emoji. Status is a word.
- No text below 12px. Nothing decorative.

## Acceptance

- Start Act 1 from `/`. The screen updates live while the worker runs, and ends with the receipt.
- Reloading mid-run rebuilds the page correctly from the event log.
- `/compare` shows the Precedent run and the baseline run on seed 7 side by side.
