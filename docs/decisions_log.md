# Decisions log

One line per decision. The README's design-decisions section is built from this file.

- 2026-10-07: Python only, with uv, because a one-person, few-day build needs one language and a simple interview walkthrough.
- 2026-10-07: no agent framework, because the loop, recovery and verification are what we are judged on and must be fully ours.
- 2026-10-07: browser accessibility snapshots instead of pixel computer use, because they are faster, cheaper and more reliable, and still real browser operation.
- 2026-10-07: a grader independent of the worker reads world.db and hidden.json, because a pass must not be self-reported.
- 2026-10-07: the ghost baseline uses the same runner and only swaps the context stage, so the comparison isolates company context.
- 2026-10-07: Gemini by default behind a provider-agnostic LLM interface, with open-weight models through an OpenAI-compatible adapter, so no paid key is needed to build, run or review.
- 2026-10-07: the world generator applies the same rule functions to write history and to compute hidden.json, so the hidden truth agrees with its seed by construction.
- 2026-10-07: the canonical seed (7) pins every story value from the brief; other seeds sample the same specs from Random(seed), so a pinned demo and varied evaluation share one code path.
- 2026-10-07: items for later acts (Act 3, Act 4) are generated into worlds/<seed>/held/ and delivered by a scenario hook, so they cannot interfere with earlier acts.
- 2026-10-07: a fallback model chain (PRECEDENT_MODEL_FALLBACK, Flash models only) because gemini-3.8-flash returned repeated 503s and Pro models have no free-tier quota.
