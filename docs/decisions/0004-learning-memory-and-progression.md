# ADR 0004: SQLite learning memory and separate progression signals

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

Sensei must remember what the student has practiced, demonstrated, and misunderstood without keeping an unbounded transcript in the model context. The student also wants RPG-style progress, but rewarding effort and asserting mastery are different claims and must not be represented by one score.

Learning records are personal data. Storage, export, backup, deletion, and inference boundaries must be explicit before a graphical interface makes them less visible.

## Decision

Use the Python standard library's SQLite interface with versioned migrations and an application-owned schema. Store structured attempts, consolidated misconceptions, mastery aggregates, review dates, and immutable additive XP events in separate tables.

Create durable evidence only after the student invokes `/done`. Ask the local model for an exact five-field learning event, validate it deterministically, and retry once before failing without a write. Record whether the outcome came from the student or model.

Update one attempt, misconception, mastery aggregate, and XP event atomically. Keep XP additive and independent from mastery. Reduce uncertain mastery movement using extraction confidence and require repeated correct attempts for higher labels.

Retrieve only a compact summary of up to five weak practiced skills and unresolved misconceptions for future tutor prompts. Do not persist or replay raw chat transcripts.

Provide JSON export, SQLite backup, confirmed personal-data clearing, custom database paths, and a stateless mode from the first persistent version.

## Consequences

### Benefits

- Study history survives model and application restarts without growing prompts.
- The database is inspectable, portable, and owned by the student.
- XP can reward effort without inflating claims of mathematical mastery.
- Outcome provenance and confidence make the current trust boundary auditable.
- Scheduled review and misconception retrieval directly influence later tutoring.
- Data controls are available before substantial personal history accumulates.

### Costs and risks

- Model- or student-reported correctness can be wrong until deterministic verification exists.
- Heuristic mastery weights and review intervals may need substantial revision.
- The v1 catalog may not match every course's terminology or ordering.
- A single local database supports one learner profile.
- Exported JSON and copied backups remain personal files outside the active database's deletion control.

## Revisit conditions

Revisit the evidence weights after deterministic verification is integrated and enough real study attempts exist for evaluation. Add a migration rather than editing an applied schema whenever stored columns or semantics change.
