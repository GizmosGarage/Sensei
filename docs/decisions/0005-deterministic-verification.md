# ADR 0005: deterministic calculus verification

- Status: accepted
- Date: 2026-08-21

## Context

Sensei previously derived correctness from a student report or a local model classification. That is useful learning evidence but not a reliable mathematical oracle. Incorrect classifications could award mastery, while a growing prompt or a larger model would not create a dependable correctness boundary.

The project needs an offline, reproducible check for common Calculus I answers. It must not execute user input, must preserve disagreements for later inspection, and must degrade safely when symbolic mathematics is undecidable or unsupported in practice.

## Decision

Add a deterministic verifier based on pinned SymPy 1.14.0 behind Sensei's own restricted expression parser.

The parser accepts a deliberately small allowlisted grammar and constructs symbolic expressions from validated syntax-tree nodes. It does not call `eval` or expose SymPy's general parser to terminal input. Resource-oriented grammar bounds are applied before symbolic operations.

Support four explicit check kinds: derivative, limit, antiderivative, and equivalence. Return a three-state result: verified correct, verified incorrect, or inconclusive.

Attach the latest check to the active problem. On `/done`, a conclusive verification result overrides the effective reported outcome for progression, but schema version 2 stores both values and their sources. Inconclusive or absent verification leaves the student/model report effective.

## Consequences

- Mathematical correctness for supported problems no longer depends on model prose.
- The local model can use an authoritative result to explain a specific error.
- XP, mastery, and review decisions are auditable through stored provenance.
- Existing learning databases require an automatic forward-only migration and backfill.
- A restricted grammar rejects some valid notation and must be expanded deliberately with tests.
- Symbolic simplification is not complete, so inconclusive remains a necessary outcome.
- The current resource bounds are not a substitute for a future isolated worker with a hard compute timeout.

## Alternatives considered

### Ask the language model to check its own answer

Rejected as the correctness boundary because the verifier would share the same probabilistic failure mode as the tutor.

### Use SymPy's general string parser directly

Rejected for untrusted terminal input. Sensei needs a narrower, inspectable grammar and explicit control over which syntax becomes a symbolic object.

### Compare answer strings or numeric samples only

Rejected as the primary method. String comparison rejects equivalent notation, while numeric sampling can miss singularities, domain differences, and adversarial coincidences. Numeric checks may later supplement, but not silently replace, symbolic provenance.
