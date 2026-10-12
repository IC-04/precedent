# Recorded work, with the verdicts kept intact

These are selected real runs, not a success-rate benchmark. The worker and the independent
assessors can disagree. Their results are recorded separately rather than averaged into a pass.

| Run | Work | Worker checks | Independent assessment |
| --- | --- | --- | --- |
| [d343](20261011-210344-d343.json) | Real Gmail briefing and Google Calendar hold; 158.2 seconds, 34 actions | 13/13 pass | Tribunal 13/13 pass |
| [5080](20261012-121618-5080.json) | Company Mail, Drive, Books, Calendar and Chat → real Gmail and Calendar; 257.0 seconds, 41 actions | 16/16 pass | 15 pass, 1 disputed; overall disputed |
| [0f7d](20261010-185357-0f7d.json) | Invoice entry and approval routing; 270.4 seconds, 33 actions | 11/11 pass | Tribunal 11/11; hidden-truth grader 14/14 |
| [fc9a](20261010-154410-fc9a.json) | A different invoice after restart, using scoped notes and an activated invoice skill | 12/12 pass | Hidden-truth grader 14/14 |

The JSON files are deliberately small public extracts of retained assessment files. They contain
condition IDs, verdicts and SHA-256 digests of the original sources. They omit mail bodies,
recipients, account identifiers, native object IDs and source excerpts. They are a traceable
summary, not a substitute for provider access or an independently reproducible benchmark.

## What the film shows

The [4:46 film](https://github.com/IC-04/precedent/releases/download/readme-showcase-v1/precedent-demo.mp4)
combines several recordings. The Gmail/Calendar execution comes from **5080**. The passing
11-condition invoice hearing is **0f7d**, a different task. The two must not be read as one
uninterrupted execution with a shared verdict. Some preparation/waiting time is cut; accelerated
segments show their speed. Run timings come from the event logs, not edited film duration.

The Ava/Loki recovery scene is explicitly **staged from recorded run
20261010-193810-dd3f**. The scenario intentionally removed approval routing, the Tribunal
caught unsupported claims, and a bounded remand/rehearing recovered it. This is an explanation
of that controlled scenario, not footage of a new autonomous failure happening in the scene.
See [the Tribunal implementation](../../src/precedent/tribunal) and the
[learning delivery report](../trustworthy_learning_milestone.md).

The teaching footage shows a demonstration interpreted into a reviewed **candidate**. Its
recorded rehearsal did not validate activation. Successful activation/reuse is evidenced
separately by the earlier invoice learning milestone and **fc9a**; it is not inferred from a
button or a plausible-looking skill card. Memory reuse was observed, but the warm task was
slower overall, so this project does not claim a general latency improvement.

## Boundaries of the proof

- Native Google work uses a human-signed-in Chrome profile to write, with a separately
  consented read-only API connection for fresh proof. Provider-backed OAuth execution is a
  separate path with its own partially completed acceptance report.
- Exact checks establish bounded fields and changes. Chat-message coverage is not a complete
  guarantee of semantic faithfulness; the independent jury can dispute it.
- Generated-company grades use hidden truth that the worker cannot read. They do not prove
  unrestricted websites or arbitrary desktop applications are supported.
- Retained failures, unknowns and disputes are part of the evidence. No aggregate pass rate
  is reported because the evaluation orchestrator is unfinished.

The [media manifest](../../assets/readme/manifest.json) lists sources, cuts, captions and
privacy treatment. Raw footage, browser profiles and private logs remain outside the public
package. The README previews and full film are recordings; they do not execute tasks or make model calls.

