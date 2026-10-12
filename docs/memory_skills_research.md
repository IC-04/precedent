# Ava’s memory and reusable skills: recommendation

Research and repository inspection on October 9, 2026. This records the original proposal. The October 10 implementation update below supersedes its current-code and dependency observations.

## Recommendation

Proceed with persistent memory and a page called **Ava’s mind**, with the subtitle **What Ava knows, and where it came from**. Build it as the visible interface to a real evidence and skill lifecycle. Start with the installed Google ADK's native local persistence rather than adding a third-party service before proving the retrieval and trust rules.

The preferred initial stack is `Runner` with a persistent session service, `SqliteMemoryService` for searchable local recall, an application-owned registry for provenance and memory/skill status, and ADK `SkillToolset` for reviewed instruction-only skills. A `BaseMemoryService` adapter boundary allows later Mem0 or Vertex Memory Bank adoption. The underlying company database and hidden grader truth remain inaccessible to the worker.

## Current code

`worker/runner.py:_drive` creates an `InMemoryRunner` and a session with the fixed user ID `ava`. Run events, decisions, receipts and page evidence persist as files, but they are not a cross-run memory service. `worker/context.py` gathers current pages, proposes company precedents and validates their citations and support counts afresh. Crash recovery treats old logs as intentions and reconciles current application state.

The installed ADK is **2.11.0**. Read-only inspection confirmed public `SqliteMemoryService` and `SkillToolset` imports/signatures. The SQLite memory service implements persistent event storage, FTS5 search with a fallback, scoped app/user queries, and deterministic event identity for idempotent ingestion. This confirms API availability, not an integrated memory workflow or retrieval benchmark. The separate `DatabaseSessionService` import currently needs the missing `google-adk[db]` dependencies; that is a small optional dependency addition, not already working persistence. No packages or services were installed in this research turn.

Sources: [installed-version SQLite memory implementation](https://github.com/google/adk-python/blob/v2.11.0/src/google/adk/memory/_sqlite_memory_service.py), [ADK memory interface](https://adk.dev/sessions/memory/), [ADK skills](https://adk.dev/skills/), [persistent ADK sessions](https://github.com/google/adk-python/blob/main/docs/guides/sessions/session/index.md).

## Options and fit

| Option | Fit | Added work and decision |
| --- | --- | --- |
| ADK native SQLite memory | Best initial local demo fit. Installed service, durable local search, existing ADK interface, no new cloud memory credentials. | Lexical retrieval is not semantic reasoning or automatic truth validation. Add our own provenance, review, invalidation and tenant isolation. Recommended first. |
| Mem0 Platform | Viable semantic-memory upgrade. Official example adapts Mem0 to ADK `BaseMemoryService`. | New API key/service; configure identity filters and data handling. Replace the sample's blanket turn autosaving with curated evidence ingestion. Keep Vertex ADC for the agent. |
| Mem0 open source | Gives control over deployment and selectable LLM, embeddings and vector storage. | More configuration and components. Verify ADC compatibility separately for extraction and embeddings; a Vertex embedding provider alone does not establish an end-to-end ADC setup. |
| Vertex Memory Bank | Strong Google Cloud fit, native ADK adapter and ADC authentication. | Requires an Agent Platform runtime resource and appropriate APIs/permissions; existing Gemini inference access is insufficient. The worker can remain local. Attractive managed option after the local lifecycle works. |
| Zep Cloud / Graphiti | Useful when time-dependent company relationships and policy changes justify a graph. Zep offers an ADK integration; Graphiti is the open-source temporal-graph option. | Zep adds a service/key. Graphiti adds graph storage and extraction/retrieval integration. More work than needed for the first invoice memory loop. Defer unless graph relationships become a central requirement. |

Primary sources: [Mem0 ADK adapter](https://docs.mem0.ai/integrations/google-ai-adk), [Mem0 OSS configuration](https://docs.mem0.ai/open-source/configuration), [Vertex prerequisites](https://adk.dev/sessions/memory/#prerequisites), [Zep ADK](https://help.getzep.com/google-adk-memory), [Graphiti](https://github.com/getzep/graphiti).

These are integration assessments, not performance benchmarks. Persistent memory may reduce repeated context gathering, but extraction and retrieval can also add calls and latency. Measure cold/warm runs before claiming improvements.

## Three distinct things to remember

1. **Episodes:** what a run attempted, observed, changed and checked; evidence links; failures and unresolved conditions. Failed and blocked attempts also provide useful recovery lessons. Do not retain only success stories.
2. **Company knowledge:** policies, preferences, authorities and observed conventions, each with scope, source, effective time and validity. A past approver is not an eternal approval rule.
3. **Skills:** a reviewed, versioned procedure for accomplishing a class of outcomes. A skill selects current sources and checks; it does not encode an old sequence of element IDs or clicks.

Keep these separate from execution-session history. Do not ingest raw transcripts, private model reasoning, credentials, hidden grading results or arbitrary untrusted page instructions as authoritative memory.

## Data and trust rules

Each memory should retain an identifier, stable company/workspace instance ID, environment, author, type, concise statement, source references and hashes, originating run, observation/effective dates, validation status, correction/supersession links, expiry/revalidation policy and retrieval history. Any confidence value must describe a defined evidence rule, not a made-up model probability.

The current fixed `user_id='ava'` is unsafe for shared cross-company memory. Scope storage and retrieval by stable workspace instance and authorized user/worker identity. **Seed 7 and “Northwind Ltd” are not sufficient identity:** fresh generated companies reuse them. A reset should create a new instance identity; process restart should preserve the same identity. Company policies and invoice facts must not leak across instances. General procedures may be reusable across companies only when their company-specific bindings are freshly established.

A separate runtime-memory store is not permission to read `world.db` or `hidden.json`. Import the ADK service through its public API; preserve the rule that worker code never directly imports `sqlite3` or company database modules. Registry persistence belongs in an application/service layer, with a narrow approved interface.

Use memories as retrieved data with provenance, not privileged instructions. Current authoritative sources override stale memory. Revalidate company policies and business keys before consequential writes. Memory cannot authorize a write, erase uncertainty or bypass the gateway. Failed retrieval should visibly degrade to the existing fresh-context workflow.

## Completion to skill

The product interaction is **Review learning → Create skill draft → Validate → Activate**, not a one-click promotion to unchecked authority.

After a run, derive an evidence-backed learning note. Separate observed facts, inferred explanations and unresolved checks. The user can create a skill draft from the supported parts even when the whole task is incompletely verified. Activation should require all critical checks for that skill's narrower scope, explicit user acceptance and sandbox validation. Never ingest the grader's privileged expected values into the worker or generated skill.

A draft skill contains its purpose, applicability, parameters, prerequisites, permissions, source/authority selection rules, duplicate reconciliation, procedure, fresh checks, stop/clarification conditions, provenance and version. Begin with instruction-only skills; do not expose arbitrary generated scripts or additional privileged tools. Inspect/filter ADK skill tools accordingly.

Example: **Enter and route a vendor invoice** takes a vendor identity and invoice selector. It finds the current invoice, reconciles duplicates, resolves current accounting and approval policy, records a decision before each write, acts through the existing browser tools, and checks the saved record. It must not hard-code Ana Pereira, invoice FIG-1842, account 1400, an old company URL or snapshot element references.

Before reuse, match task intent and prerequisites, check source validity and skill status, then show **Using skill: [name], version [n]** with the reason. Fresh observations drive the execution. If sources or UI differ, invalidate/revise the skill or fall back to general reasoning. Repeating the same invoice must exercise duplicate prevention, not create another bill.

## Ava’s mind UI

Use two focused sections, **Memory** and **Skills**, with each memory's originating task and evidence accessible. A learning note should explain “What happened”, “What can be reused” and “What remains uncertain”. Provide useful search, source inspection, correction, archive and skill-draft creation. Show candidate, active, superseded and invalidated states honestly.

Skills need a readable detail page, parameters, source lineage, validation record, version history and activation/deactivation controls. If nothing has been learned, show an honest empty state. Do not populate fake neurons, confidence meters, memories or skill counters. This is inspectable operational knowledge, not a display of private chain-of-thought.

## Verification issue discovered in the retained proof

The milestone run `20261008-215737-5b6a` independently passed 13 grading checks. Its worker receipt reports 5/7 passed and two unknown. However, condition `c3` bundles invoice number, date and amount; its fresh evidence only compares amount. This is an additional **coverage gap**, even though the bill itself is correct according to the independent grader. Preserve the original receipt; do not describe the entire bundled condition as proven or use it to activate a broad skill.

Before memory/skill activation, either make goal conditions atomic or implement compound verification that requires all constituent facts, and reject a narrow check spec that purports to satisfy a broader condition. Add a meaningful regression test for this observed case. Memory should remember the amount evidence and coverage limit, not turn the broad claim into established fact.

## Build order and evaluation

1. Finish the in-app project guide and controlled voice tour for immediate demo clarity.
2. Repair verification scope and establish company-instance identity; define memory/skill contracts.
3. Integrate persistent sessions and local evidence memory; build the real Ava’s mind page alongside it.
4. Create, review and validate one instruction-only invoice skill; demonstrate retrieval after a process restart and skill selection on a subsequent task.
5. Add semantic retrieval through Mem0 or managed Vertex memory only if lexical recall fails useful retrieval cases or broader onboarding needs justify it.

Acceptance: persistence after restart, no cross-company leakage, no unsupported claims promoted, explicit source invalidation after a policy change, memory unavailable fallback, no duplicate business writes, auditable skill versions, current policy winning over stale memory, and real fresh verification on skill-assisted execution. Benchmark quality, context/model tokens and end-to-end latency on matched cold/warm tasks. Do not present one successful replay as a general skill success rate.

## Implementation update — October 10

Implemented the local ADK path: `DatabaseSessionService` persists per-run sessions,
`SqliteMemoryService` indexes curated entries, and the application registry owns provenance,
corrections and skill status. Added ADK's `db` optional dependencies. The installed 2.11
`add_memory` method raises `NotImplementedError`; the adapter uses the public
`add_events_to_memory` method with deterministic, curated entry/version events instead.
It never indexes full execution transcripts. Retrieval queries the scoped ADK index, then
checks current registry version/status before returning at most five entries.

`SkillToolset` exposes only `load_skill` for the reviewed instruction-only procedure.
Validation runs a real configured worker in a separate generated company. Activation
requires supported critical claims, a successful trial bound to the procedure hash, and
the explicit review/activate UI action. No scripts or additional privileges are exposed.

The stable instance sidecar survives process restarts; regenerating a company replaces it.
Scope is local environment + instance UUID + worker identity. This is a single-user local
prototype, not production multi-user authorization. Credentials and privileged grader
inputs never enter learning. ADK session history is separate from the curated recall index.

Fresh context still reads all relevant accessible policy pages and history. An exact match
of the gathered authority set and content allows reuse of prior rule candidates; code
recomputes their support against fresh history. Changed, added or missing authority
invalidates reuse. This does not prove completeness beyond the bounded accessible sources.
See `trustworthy_learning_milestone.md` for actual test/run evidence and limitations.
