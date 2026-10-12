# Verifier patterns: research for the Tribunal

Written 10 Oct 2026. The question: how do agentic systems verify that work was actually done, and which of those patterns should the Tribunal use so that it is exact where it can be, honest where it cannot be, and never a lone LLM guessing?

## 1. The patterns, and how each one operates

### A. State-based (execution-based) verification
- **How it works:** after the agent stops, a program inspects the environment's end state and compares it with a specification. Examples:
  - WebArena checks whether the order was placed or the issue closed, through page state or API calls.
  - OSWorld runs a per-task evaluator script against the application's final state.
  - τ-bench compares the final database with the state the gold actions produce.
  - Terminal-Bench runs a per-task test script.
- **Strength:** exact and repeatable, and it judges outcomes rather than claims.
- **Weakness:**
  - Somebody must write the specification.
  - It only sees what it was written to check, so side effects and superficial successes slip past one check.
  - AgentRewardBench found that rule-based evaluation *undercounts* real success.
- **In Precedent:** this is the grader (`grader/grade.py`, reading `world.db` and `hidden.json`). It is the held-out oracle and never part of the run.

### B. Rule checks on observations (typed assertions)
- **How it works:** the same idea as A, but run against what the agent's environment *shows*, without privileged access: parse the page and assert typed fields (amount, approver, status, file id).
- **Strength:** exact, and it can run inside the product, because it needs only the browser.
- **Weakness:** brittle when representations differ. Our own run `20261009-131448` compared filename `FIG-1842.pdf` against id `f-0004` and produced a false fail.
- **In Precedent:** `worker/verify.py` primitives. These become the Tribunal's deterministic court.

### C. LLM-as-a-judge (single pass)
- **How it works:** a model reads the task and the final state, and answers yes or no, or gives a score.
- **Strength:** flexible, and it handles meaning ("does the memo give the reason?").
- **Weaknesses:**
  - Variance between calls.
  - Self-preference bias, including a preference for its own model family.
  - Sensitivity to wording.
  - It can be talked into a verdict by text inside the evidence (prompt injection).
- **Verdict:** not acceptable alone. This is exactly the "LLM sitting there verifying randomly" we want to avoid.

### D. Agent-as-a-judge (WebJudge, Mind2Web 2)
- **How it works:** the judge works through the task in steps:
  1. extract the task's key points (the requirements)
  2. select the key screenshots or evidence for each point
  3. judge each point against its evidence
  4. combine the per-point results
- **Results:** WebJudge on o4-mini reached about 86% agreement with human labels on Online-Mind2Web, and about 82% precision on AgentRewardBench. Mind2Web 2 gives the judge tools, so it gathers evidence rather than only reading it.
- **Strength:** it is decomposed and grounded, and each verdict points at evidence.
- **Weakness:** still a model. Agreement is far from 100%, and results vary by backbone.
- **In Precedent:** the shape of the semantic court, with claim → evidence → verdict for each claim.

### E. Tool-interactive critique (CRITIC)
- **How it works:** a draft is checked by calling external tools (search, an interpreter, a classifier), and the critique is grounded in what the tools return. Reported gains largely disappear when the tool is removed, so the external signal is what does the work.
- **In Precedent:** a judge may only cite evidence that the Tribunal's own read-only browser captured. It gets no access to the agent's narrative.

### F. Chain-of-Verification (factored)
- **How it works:**
  1. draft an answer
  2. plan verification questions
  3. answer each question *independently of the draft*
  4. revise
  
  The "factored" variant hides the draft while the questions are answered, which removes anchoring.
- **In Precedent:** the judge never sees Ava's claims, receipt or completion message. Each claim becomes one neutral question ("Who is the approver on this bill?"), and code compares the answer with the expectation. The judge is never asked "Did Ava set Ana?"

### G. Self-consistency and sampling votes
- **How it works:** ask the same question k times, independently. The share of agreeing answers is a cheap confidence estimate. Low agreement is a signal to abstain.
- **In Precedent:** k = 3 for each semantic question. A split vote means "disputed", never "pass".

### H. A panel of judges from different families
- **How it works:** several judges, preferably from different model families, each give a verdict, and the panel aggregates them.
- **Evidence:**
  - Panels of smaller, cross-provider judges have been reported to beat a single large judge.
  - Same-family preference is measurable.
  - Ensembling reduces *variance* but does not remove *shared* bias, so a panel is not ground truth.
- **In Precedent:** two jurors from different families. Qwen3-VL 235B on Bedrock is the first juror. Gemini is the second, and is *not* Ava's own reasoning context: it's a fresh call with the same evidence only. Grok 4.3 breaks ties on disputed claims.

### I. Maker-checker (four eyes), and N-version checking
- **How it works:** standard control in finance and safety engineering. The person who makes a change is not the one who approves it, and the checker sees the change and its justification *before* it commits.
- **In Precedent:** a pre-write reviewer in the gateway sees the form about to be submitted, plus the recorded decision and its cited sources, and blocks the write on a "no". Prevention is better than detection.

### J. Evaluator-optimizer loop
- **How it works:** an evaluator's feedback drives another attempt, until it passes or a budget runs out.
- **Risk:** if the evaluator is the same thing that decides "done", the agent optimises against the evaluator.
- **In Precedent:** the Tribunal may send a *reason* back to Ava for one bounded repair attempt, but its verdict is recomputed from fresh evidence, and the grader stays held out.

### K. Process and side-effect audit, not just outcome
- **How it works:** check the trajectory as well as the end state:
  - Did it take forbidden actions?
  - Did it touch anything outside the task?
  - Did it blind-retry a write?
  
  AgentRewardBench labels side effects separately from success, for exactly this reason. WildClawBench argues that rule, execution, state and semantic checks each miss something on their own, and that hybrids are needed.
- **In Precedent:** deterministic audit of the gateway log against the event log:
  - every write is preceded by a decision with sources
  - no write targets an entity outside the goal's scope
  - every retry was preceded by a business-key search
  - nothing ran after `finish`

### L. Calibration and meta-evaluation
- **How it works:** a judge is itself measured against labelled cases. Practice is to report agreement (Cohen's kappa, with 0.6 as a common bar) and a confusion matrix, to set thresholds on one split and report on another, and to re-measure whenever the judge model changes.
- **In Precedent:** labels come from the grader on saved runs, plus *mutation fixtures* where we deliberately break one fact (wrong approver, duplicate bill, changed bank details, wrong attachment). Thresholds are set on a development split, and kappa and a confusion matrix are reported on the held-out split.

### M. Robustness to manipulation
- **How it works:** a judge that reads page text can be steered by that text, and the same weakness applies to typed-decision models.
- **In Precedent:**
  - Evidence is passed as quoted data with provenance (URL, capture time, hash).
  - Instructions sit outside it.
  - The poisoned-invoice fixture is part of the calibration set.
  - A deterministic fail always overrides a semantic pass.

## 2. What this means: the Tribunal is a pipeline, not a model

```
Goal contract ──► 1 Charges: atomic claims, coverage enforced in code
                       │
Fresh, independent ─► 2 Evidence: the Tribunal's own read-only browser session
read-only capture       (screenshot + parsed fields + URL/time/hash per record)
                       │
                       ├─► 3 Deterministic court: typed primitives (exact)
                       ├─► 4 Semantic court: factored questions, 2 families × k=3 votes
                       └─► 5 Process audit: gateway log vs event log (exact)
                       │
                  6 Verdict rules (code) ─► per-claim verdict + overall + reasons
                       │
held-out oracle ───► 7 Meta-evaluation: grader labels → kappa, confusion matrix
```

**1. Charges.** The goal contract is turned into atomic claims, each with an id, a kind and an expected value taken from cited sources, never from Ava's completion message. Grok 4.3 proposes the split. Code rejects:
- a claim that has no check
- a check that covers only part of a compound claim
- an expectation with no source quote

**2. Evidence.**
- A separate read-only session goes through the gateway with its own identity header, using only GET.
- It opens each record named by the claims and keeps a screenshot, the page text and the parsed typed fields.
- It never reads Ava's receipt, event narrative or `finish` message.

**3. The deterministic court.** Typed comparison:
- normalised money and currency
- explicit dates
- file identity from the attachment href
- vendor plus invoice-number business key
- separate bill and approval statuses
- exact count of matching bills, across every page of search results

The result is pass, fail or unknown, and unknown when the evidence is missing.

**4. The semantic court.** Only for claims that code can't decide:
- a reason given in free text
- whether the routing note cites the instruction
- what a screenshot shows when the DOM is ambiguous
- whether the chosen invoice is really the latest, given the candidates captured

Each claim becomes one neutral question. It is asked of Qwen3-VL and of a fresh Gemini call, 3 samples each, and the answers are compared with the expectation in code. The output is a vote share and a short rationale that cites evidence ids.

**5. The process audit.** Deterministic checks over the run:
- every write was preceded by a decision with sources
- no blind retries
- no writes outside scope
- the write gate's refusals were respected
- no actions after `finish`

**6. Verdict rules (code, not a model):**

| Deterministic | Semantic | Verdict |
|---|---|---|
| fail | any | **fail** (an exact check beats an opinion) |
| pass | agrees, or not needed | **pass** |
| pass | disagrees | **disputed**: escalate to Grok 4.3 with the same evidence; if still split, ask a human |
| unknown | ≥ 5 of 6 votes agree | **pass, judged**: shown as a weaker kind of pass, never merged with exact passes |
| unknown | split or below threshold | **unknown** |

A process-audit violation caps the overall verdict at **fail**, whatever the outcome checks said.

**7. Meta-evaluation.**
- The grader stays outside the Tribunal. It's used only to score it.
- Report per-claim-kind agreement, kappa, a confusion matrix and the rate of unknown verdicts.
- Report what the semantic court adds on its own.
- Mutation fixtures make sure every failure kind appears in the test set.

## 3. Deterministic or semantic, by claim kind

| Claim kind (invoice task) | Court | Why |
|---|---|---|
| Exactly one bill for vendor + invoice no. | Deterministic | A count over the business key |
| Amount, currency, dates | Deterministic | Typed normalisation |
| Account code, approver identity, statuses | Deterministic | Exact field match on the right table |
| Attachment is the source invoice | Deterministic | File id from the href, not the filename |
| Vendor bank details unchanged | Deterministic | Baseline captured before the run, compared after |
| The approver follows the governing instruction | Deterministic plus a source quote check | The expectation comes from the cited instruction |
| The routing note gives the reason | Semantic | Free text |
| The screenshot shows a saved record, not an error state | Semantic, with a deterministic DOM cross-check | Covers visual-only failures |
| "Latest invoice" was selected | Semantic over the candidates captured; unknown if they're incomplete | Needs a judgement about completeness |
| No harmful side effects | Process audit (deterministic) | From gateway provenance |

## 4. Risks and how we handle them

- **Judge disagreement looks bad on stage.** It's a feature: "disputed" is shown honestly, with evidence.
- **Cost and latency.** About 10 claims × 2 jurors × 3 samples costs fractions of a cent and runs in parallel. Grok is called only on disputes.
- **Overfitting the judge to the grader.** Thresholds are set on a development split only, with results reported on a held-out split, and the mutation fixtures are written before thresholds are tuned.
- **Bedrock lacks the Decisions API, and this account cannot call GPT-5.x or 6.x, so there are no native probabilities.** Votes stand in for confidence, and the `Juror` interface allows swapping in a Decisions-API or Jev juror later.

## 5. The Loki-style Tribunal screen: what we can and can't do

**We can build:**
- a retro-futurist bureaucratic courtroom: amber CRT glow, 1970s civic-brutalist panels, stamped case files
- a branching-timeline metaphor where a failing claim makes the run's timeline visibly "branch off"
- a bailiff-style companion pet in SVG that inspects evidence and stamps verdicts

**We shouldn't build:**
- copies of Marvel's protected elements: the TVA name and logo, the Miss Minutes character or a lookalike, the Loki title, or character likenesses

That's both an intellectual-property risk and a poor look in a hiring submission. The pet should be our own original character that nods to the genre, not a copy. Its name and design are the user's call.

## Sources

- [An Illusion of Progress? Assessing the Current State of Web Agents (WebJudge, Online-Mind2Web)](https://arxiv.org/pdf/2504.01382)
- [Online-Mind2Web repository](https://github.com/OSU-NLP-Group/Online-Mind2Web)
- [AgentRewardBench](https://arxiv.org/pdf/2504.08942)
- [Mind2Web 2: agent-as-a-judge](https://arxiv.org/pdf/2506.21506)
- [WebRetriever](https://arxiv.org/pdf/2607.06118)
- [Benchmarking LLM judges for mobile agents](https://arxiv.org/html/2608.11434v1)
- [WildClawBench](https://arxiv.org/pdf/2605.10912)
- [STAGE-Claw](https://arxiv.org/pdf/2606.10394)
- [AgentAtlas](https://arxiv.org/html/2605.20530v1)
- [OSWorld](https://www.researchgate.net/publication/397199026_OSWorld_Benchmarking_Multimodal_Agents_for_Open-Ended_Tasks_in_Real_Computer_Environments)
- [CRITIC](https://arxiv.org/pdf/2305.11738)
- [Self-preference bias in LLM-as-a-judge](https://arxiv.org/pdf/2410.21819)
- [Who judges matters: family-conditioned preference](https://arxiv.org/pdf/2609.17857)
- [Self- and other-labels induce bidirectional bias](https://arxiv.org/pdf/2608.18091)
- [LLM-native psychometric instrument (shared judge bias)](https://arxiv.org/pdf/2606.09843)
- [LLM juries in practice](https://orq.ai/blog/llm-juries-in-practice)
- [LLM-as-judge best practices 2026](https://futureagi.com/blog/llm-as-judge-best-practices-2026/)
- [VentureBeat: prompt injection and typed-decision judges](https://venturebeat.com/security/companies-are-putting-jev-in-charge-of-ai-agent-decisions-and-prompt-injection-can-influence-the-verdict)
- Chain-of-Verification (Dhuliawala et al., 2023) and the evaluator-optimizer pattern are described from background knowledge; they weren't re-fetched in this session.
