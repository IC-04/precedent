# Precedent: engineering kickoff brief

Status: engineering starts 7 October 2026. The product spec is `Precedent_Product_Vision_North_Star_v2.pdf`; this brief turns it into a build.

## Deadline

The JD says **9 October, 5:30 PM IST**. We were told **12 October, 11:59 PM**. The plan is built so a complete, submittable demo exists by the end of 8 October. Days after that make it stronger; they are not needed for a submission. If the earlier date holds, we submit on the morning of 9 October.

## What we are building

A natural-language AI worker ("Ava") that completes accounts-payable tasks inside a generated company it has never seen. Before acting it reads the company's history, the current state of the work, and the authority behind each source. It then does the work in real web applications through a real browser and verifies the result against a goal contract. Every task ends with an evidence receipt.

## The one sentence a reviewer should leave with

Same worker, same task, different company, different correct behaviour, and it proves it.

## What the submission must show (from the JD)

| JD requirement | Where we show it |
|---|---|
| Understand the end goal | Goal contract, written before the first action |
| Plan, select tools, execute | Browser actions in Mail, Books, Drive and Chat |
| Observe and decide the next step | Fresh observation after every action; decision records |
| Recover from failures | Failure classification; crash-and-restart scenario |
| Maintain state | Working state plus company precedents |
| Ask for help or approval | One-question escalation; refusing an untrusted instruction |
| Verify the outcome | Checks compiled from the goal contract, run on freshly read state |
| Evidence and summary | Evidence receipt |
| Generalisation | A second company template; unseen seeds |
| Submission | Repo, README, architecture note, design decisions, demo video, limitations, next steps, assumptions, models and frameworks used |

## Scope, in priority order

**P0, the demo cannot exist without these.** Generated Northwind world; Mail, Books and Drive apps; worker loop with browser tools; goal contract; Act 1 end to end; verifier and receipt; the console showing a live run.

**P1, these make it ours.** Act 0 company context with authority ranking; ghost-run baseline; Act 2 (duplicate draft, crash and restart, colleague's edit); Globex template (Act 5); evaluation harness over seeds.

**P2, only if P1 is green.** Act 3 (one question through Chat); Act 4 (prompt injection in a PDF); more seeds and repeats; polish.

**Out of scope.** Real credentials, real SaaS, payments, multi-agent setups, pixel-based desktop control, any UI framework beyond plain HTML.

## Non-negotiables

1. The worker acts only through the apps' web interfaces. It never reads the database or the hidden truth file.
2. The grader reads the database and the hidden truth directly. It never trusts the worker's account.
3. Every consequential decision emits a decision record with its source.
4. Writes are reconciled before any retry: search by business key first.
5. Seeds are deterministic. Same seed, same world.
6. No faked autonomy in the demo. If a step is scripted, it is labelled as scripted.

## Team and tools

One person (the owner) plus Claude Code. Work is split into seven workstreams (`docs/briefs/`). Each brief is written to be pasted into a fresh Claude Code session. Shared contracts live in `docs/03_contracts.md` and `src/precedent/contracts.py`; change them only on purpose, and update both.

## Definition of done for the submission

- `make setup && make world SEED=7 && make apps` brings up Northwind locally.
- `make run TASK="Enter the latest Figma invoice and route it for approval."` completes Act 1, and the console shows the run live.
- The grader reports pass on Act 1 for Precedent on seed 7, and the result of the ghost run is shown honestly, whatever it is.
- The README covers every item on the JD's submission list.
- A demo video under 5 minutes exists, unedited apart from labelled speed-ups.
