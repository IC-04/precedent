"""The Tribunal: independent verification of a finished run.

It is a pipeline, not a model (docs/verifier_patterns_research.md):

1. charges   the goal contract's conditions, each with its atomic claims
2. evidence  the Tribunal's own read-only reads and screenshots of the company apps
3. exact     the typed check primitives, rerun on those fresh reads
4. jury      neutral questions to two model families, k samples each
5. audit     the run's own write log: decisions before writes, scope, duplicates
6. verdict   fixed rules in code; an exact fail always beats an opinion

The Tribunal never reads the company database or the grader's hidden truth, and the
jurors never see Ava's claims. Ava's claims are compared with the verdict only at the
end, to show which of them the evidence did not support.
"""
