# Sensei

Sensei is a local-first, adaptive calculus tutor. It is intended to teach through guided practice, remember demonstrated skills and misconceptions, and turn progress into an RPG-style mastery system without requiring paid model inference.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Project status

**Phase 1: minimal text tutoring loop**

The hardware and model-selection milestone is complete. The provisional local stack is:

- `llama.cpp` b10549 with its Vulkan backend
- Qwen 3.5 9B Q4_K_M as the default tutor model
- Qwen 3.5 4B Q4_K_M as the lighter fallback
- 4,096-token working context with reasoning output disabled

The default model scored 23/23 on the initial tutoring rubric and generated 29.6 tokens/second on the target RX 5700 XT. See the [benchmark report](docs/BENCHMARK_RESULTS.md) for methodology and limitations.

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
- [Benchmark results](docs/BENCHMARK_RESULTS.md)
- [Local inference setup](docs/LOCAL_INFERENCE_SETUP.md)
- [Local-first architecture decision](docs/decisions/0001-local-first-architecture.md)
- [Runtime and default-model decision](docs/decisions/0002-runtime-and-default-model.md)
- [Project log](docs/PROJECT_LOG.md)

## Planned phases

1. ~~Benchmark local model and inference-runtime candidates.~~
2. **Build a minimal text-based tutoring loop.**
3. Add persistent skill, attempt, and misconception tracking.
4. Add deterministic calculus verification.
5. Add XP, levels, review scheduling, and a portfolio-ready interface.
