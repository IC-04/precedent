# Decisions log

One line per decision. The README's design-decisions section is built from this file.

- 2026-10-07: Python only, with uv, because a one-person, few-day build needs one language and a simple interview walkthrough.
- 2026-10-07: no agent framework, because the loop, recovery and verification are what we are judged on and must be fully ours.
- 2026-10-07: browser accessibility snapshots instead of pixel computer use, because they are faster, cheaper and more reliable, and still real browser operation.
- 2026-10-07: a grader independent of the worker reads world.db and hidden.json, because a pass must not be self-reported.
- 2026-10-07: the ghost baseline uses the same runner and only swaps the context stage, so the comparison isolates company context.
- 2026-10-07: Gemini by default behind a provider-agnostic LLM interface, with open-weight models through an OpenAI-compatible adapter, so no paid key is needed to build, run or review.
