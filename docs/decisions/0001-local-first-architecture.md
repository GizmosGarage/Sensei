# ADR 0001: Local-first model inference and learning memory

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

Sensei must support long-term calculus study without accumulating hosted-model usage charges or depending on an ever-growing chat context. It is also a portfolio project whose design decisions should be visible and reproducible.

## Decision

Sensei will use an open-weight model running on the user's computer. Learning state will be stored locally in an application-controlled database. The model will receive only the relevant student state and recent interaction context for each tutoring request.

The application will expose a model-provider boundary so model and runtime candidates can be benchmarked or replaced. Model weights, personal learning records, secrets, and raw private conversations will not be committed to Git.

## Consequences

### Benefits

- No per-token inference charges for normal use.
- Study history remains under the user's control.
- Context stays small and targeted as the learning history grows.
- Model selection can evolve independently from the learning engine.
- The repository can demonstrate system design, evaluation, and privacy practices.

### Costs and risks

- Local performance is limited by available GPU and system memory.
- Windows support for the AMD GPU must be validated.
- Smaller models may need deterministic math tools and stricter prompting to reach acceptable reliability.
- Installation and packaging will be more involved than calling a hosted API.
