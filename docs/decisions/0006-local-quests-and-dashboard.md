# ADR 0006: curated review quests and a loopback dashboard

- Status: accepted
- Date: 2026-08-21

## Context

Sensei already schedules reviews, stores progression, and verifies supported calculus expressions, but `/review` only names a skill. The learner needs a concrete practice loop and a portfolio-quality view of the RPG state. A hosted dashboard would conflict with the current student-owned local data boundary, while model-generated problem/answer pairs could introduce unverified errors.

## Decision

Use a versioned, curated quest catalog whose every sample answer is regression-checked by the production verifier. Select the next eligible skill from the existing review schedule and rotate templates by attempt count. Keep `/done` as the explicit persistence boundary. Store an optional quest ID in schema version 3 and treat the catalog skill as authoritative.

Build the progress interface as packaged HTML, CSS, and JavaScript served by a Python standard-library HTTP server fixed to `127.0.0.1`. Read the same SQLite database through an answer-key-free GET API. Do not add browser-owned progression state, hosted persistence, or model access to this dashboard milestone.

## Consequences

- Curated terminal quests become immediately playable and remain reproducible.
- Model tutoring can adapt around a problem without judging its correctness or skill identity.
- The dashboard is useful offline and cannot expose study history to a hosted backend by configuration mistake.
- Quest coverage is narrower than the 17-skill curriculum until deterministic verification expands.
- Curated content requires review and tests, but avoids silently generated answer-key errors.
- The terminal still owns tutoring conversation and answer entry; browser integration remains the next architectural step.
- A loopback service is private from the network, not an authentication boundary against other local software.

## Alternatives considered

### Generate every review problem with the language model

Rejected as the initial quest source because generation would need a second deterministic validation pipeline for problem solvability, answer correctness, and syllabus fit.

### Store progress in browser storage

Rejected because it would create a second, weaker source of truth and split the learner's history from SQLite export, backup, and deletion controls.

### Publish a hosted portfolio dashboard

Rejected for the learning application because current study history and the local tutor are intentionally machine-local. A separate public demo with synthetic data can be considered later without changing this boundary.
