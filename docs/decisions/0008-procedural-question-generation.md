# ADR 0008: prevalidated procedural question generation

- Status: accepted
- Date: 2026-08-22

## Context

One fixed starter question per Precalculus subject makes repeated practice predictable. Asking the language model to invent arbitrary problems and answer keys would add latency and allow an incorrect or off-subject target to influence mastery. The learner needs fresh questions while retaining strict subject identity and deterministic correctness.

## Decision

Implement one explicit procedural generator for every skill in the 37-subject catalog. Each generator may vary only parameters and forms appropriate to its owning skill. Represent its output with the existing internal quest type, then require its own reference answer to pass through the production symbolic verifier before issuance.

Hold generated quests in process memory behind cryptographically random challenge tokens for at most one hour. Return only answer-key-free public metadata to the browser. Reject immediate prompt repetition for the same subject. Continue to create a separate short-lived, single-use token after a conclusive student check, and consume that token only when the learner explicitly records the attempt.

Keep the 40 curated quests for terminal coaching and regression coverage. Use the procedural layer for dashboard repetition and for deterministic starter exercises in the seven Calculus subjects without curated terminal quests.

## Consequences

- Reopening a topic or selecting **New question** produces new parameters without crossing into another subject.
- Every generated question has passed the same verifier used to grade the learner before it appears.
- Generation is instant, offline, reproducible under a seeded test source, and independent of model availability.
- The browser cannot read or modify the hidden answer, credited skill, correctness result, or XP award.
- Temporary challenges disappear when the dashboard process stops; durable recorded attempts remain in SQLite.
- Immediate repeats are prevented, but a random form may recur later in a long session.
- The current generators emphasize compact scalar and symbolic exercises; richer multistep reasoning needs broader validated templates and LLM coaching.

## Alternatives considered

### Ask the language model for each question and answer

Rejected as the correctness boundary because a generated answer key could be wrong or subtly outside the selected subject. The configured LLM can explain or hint around a prevalidated procedural problem.

### Store a very large static question bank

Rejected as the sole approach because it is repetitive, expensive to author, and still finite. Curated quests remain valuable for regression and coaching, but parameterized rules provide more practice breadth.

### Send verifier targets to the browser

Rejected because developer tools would reveal the answer and could forge a credited result. Only the server-held challenge token crosses that boundary.

### Persist unanswered generated challenges in SQLite

Rejected because they are short-lived interaction state, not learning evidence. Only explicitly recorded attempts belong in durable learning memory.
