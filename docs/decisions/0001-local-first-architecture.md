# ADR 0001: Learner-owned local data architecture

- **Status:** Amended
- **Date:** 2026-08-21
- **Amended:** 2026-08-29

## Context

Sensei needs durable, inspectable learning memory without treating an LLM transcript
as the student record. Provider infrastructure must be replaceable independently
from progression and verification.

## Decision

Keep learning state in an application-controlled local SQLite database. Send only
the current problem, bounded recent context, and relevant learner summary to the
configured LLM provider.

Keep personal learning records, API credentials, and raw private conversations out
of Git. Expose a provider boundary so the hosted model and Responses-compatible
endpoint can change without moving tutoring policy into infrastructure code.

## Consequences

- Study history stays under the learner's control.
- Context remains small and targeted as learning history grows.
- Model selection evolves independently from storage and verification.
- The provider sees prompt content needed for each request.
- API availability and usage charges are external operational dependencies.
