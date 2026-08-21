# Sensei

Sensei is a local-first, adaptive calculus tutor. It is intended to teach through guided practice, remember demonstrated skills and misconceptions, and turn progress into an RPG-style mastery system without requiring paid model inference.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Project status

**Phase 0: hardware baseline and local-model evaluation design**

The first engineering decision is to benchmark open-weight models that can run well on the target computer. No model has been selected yet.

## Product principles

- Run the tutor and learning memory locally.
- Treat the model as the teacher, not as permanent storage.
- Ask for a student attempt before revealing a solution.
- Reward effort with XP while measuring mastery separately.
- Verify mathematical answers with deterministic tools where possible.
- Keep personal study history, model weights, and secrets out of Git.
- Make architectural decisions and benchmark results reproducible.

## Documentation

- [Hardware baseline](docs/HARDWARE_BASELINE.md)
- [Model evaluation plan](docs/MODEL_EVALUATION.md)
- [Local-first architecture decision](docs/decisions/0001-local-first-architecture.md)
- [Project log](docs/PROJECT_LOG.md)

## Planned phases

1. Benchmark local model and inference-runtime candidates.
2. Build a minimal text-based tutoring loop.
3. Add persistent skill, attempt, and misconception tracking.
4. Add deterministic calculus verification.
5. Add XP, levels, review scheduling, and a portfolio-ready interface.
