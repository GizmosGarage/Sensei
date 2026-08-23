# ADR 0007: course-aware interactive local dashboard

- Status: accepted
- Date: 2026-08-22

## Context

The first dashboard was a read-only Calculus progress view. The learner needs a complete Precalculus preparation path and wants to practice directly from the portfolio interface. Browser writes must not create a second source of truth, expose catalog answer targets before an attempt, or allow accidental duplicate XP.

## Decision

Add `course` to the versioned skill catalog and SQLite schema. Represent Precalculus and Calculus as filtered views over one progression database, with independent next-quest recommendations. Seed the requested 20 Precalculus subjects and one deterministic starter quest for each.

Allow the loopback dashboard to check and record curated quest attempts. Keep checking non-durable. After a conclusive verifier result, hold the result in process memory behind a cryptographically random token that expires after 15 minutes and can be consumed once. Require the dashboard's per-process CSRF token for writes, validate browser origin metadata, accept only small exact-shape JSON documents, and construct the durable learning event from server-owned quest and verifier data.

Keep the server bound to `127.0.0.1`, SQLite as the only durable learning store, and the local model outside the browser server for this milestone.

## Consequences

- The learner can practice every requested Precalculus subject without leaving the dashboard.
- Course navigation does not split XP, mastery, exports, backups, or identity across stores.
- The browser cannot choose the credited skill, reported correctness, XP value, or mastery confidence.
- A network retry or replay cannot record the same checked result twice.
- Public quest data remains answer-key-free before submission.
- Incorrect checks may reveal the verifier's reference form as learning feedback after the learner has attempted the problem.
- The dashboard remains a single-learner local application rather than an authenticated multi-user service.
- Local-model coaching inside the browser remains a later integration.

## Alternatives considered

### Separate databases for Precalculus and Calculus

Rejected because skills form one learning path and the learner should keep one profile, XP total, backup, export, and deletion boundary.

### Record immediately when an answer is checked

Rejected because checking and durable learning evidence are different user intentions. Explicit recording also lets the learner inspect the result before committing it.

### Trust a browser-submitted outcome or XP amount

Rejected because developer tools or another local process could forge progression. The server derives all durable fields from its own catalog and verifier result.

### Host the dashboard for portfolio viewing

Rejected for the live learning application because the user's study history and inference stack are intentionally local. A future public demo should use synthetic data and a separate deployment boundary.
