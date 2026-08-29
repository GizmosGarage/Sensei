# ADR 0009: Grow practice from learner-directed topics

- Status: accepted
- Date: 2026-08-27

## Context

Sensei's first complete practice surface exposed a fixed 20-topic Precalculus path and 17-topic Calculus path. That proved the quest, verifier, mastery, review, XP, and dashboard foundations, but it made the product feel like a premade course rather than a tutor that follows the learner's actual class, exam, or curiosity. Extending curated generators topic by topic would also make chemistry and user-supplied material slow to support.

## Decision

The dashboard begins with a learner-created study focus: subject, topic, and optional material or emphasis. Each unique subject/topic pair becomes a durable skill row with `source=learner` and participates in the existing mastery and progression model.

Fresh practice uses the configured LLM API under a constrained contract. One pass drafts a standalone expression or multiple-choice problem; a separate pass recomputes the answer and reviews correctness and topic fit. Strict parsing rejects malformed drafts. Quantitative answers are checked through the restricted symbolic verifier, and conceptual answers use an exact four-option key. Hidden answers stay server-side until submission.

The original catalog and deterministic generators remain as a compatibility and stronger-verification foundation, but the primary interface no longer displays them as a required curriculum.

## Consequences

- Sensei can grow around math, chemistry, and future learner-supplied subjects without a catalog release.
- Existing XP, attempts, mastery, and spaced review remain unified instead of creating a second progression system.
- Model startup is now part of the normal dashboard lifecycle.
- Two model calls per adaptive quest trade latency for a meaningful validation barrier.
- Symbolic and multiple-choice answer contracts are intentionally narrower than all possible practice formats.
- Independent LLM review reduces generation errors but does not provide formal scientific proof; the UI and documentation must not overstate that assurance.
- Multi-turn conversational coaching inside the browser remains a later layer over the now-dynamic quest foundation.
