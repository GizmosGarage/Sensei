# Sensei

Sensei is a local-first, adaptive calculus tutor. It is intended to teach through guided practice, remember demonstrated skills and misconceptions, and turn progress into an RPG-style mastery system without requiring paid model inference.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Project status

**Phase 4 complete: deterministic calculus verification**

The local terminal tutor now combines a local language model, persistent SQLite learning memory, and a restricted symbolic verifier. It starts the selected model automatically, keeps each problem's recent context bounded, and can independently check derivatives, limits, antiderivatives, and expression equivalence before `/done` records progress. The provisional local stack is:

- `llama.cpp` b10549 with its Vulkan backend
- Qwen 3.5 9B Q4_K_M as the default tutor model
- Qwen 3.5 4B Q4_K_M as the lighter fallback
- 4,096-token working context with reasoning output disabled

The default model scored 23/23 on the initial tutoring rubric and generated 29.6 tokens/second on the target RX 5700 XT. See the [benchmark report](docs/BENCHMARK_RESULTS.md) for methodology and limitations.

## Quick start

After completing the [local inference setup](docs/LOCAL_INFERENCE_SETUP.md), start the tutor with:

```powershell
python -m sensei
```

Use the lighter model when faster startup and lower memory use are more important:

```powershell
python -m sensei --fast
```

Inside the tutor, use `/check derivative`, `/check limit`, `/check antiderivative`, or `/check equivalent` to start a guided deterministic check. Use `/hint`, `/solve`, `/done`, `/profile`, `/skills`, `/review`, `/new`, `/status`, `/help`, or `/quit` for tutoring and progress. Plain text uses coach mode. For an automated one-shot model check:

```powershell
python -m sensei --prompt "Evaluate lim_(x->0) sin(x)/x" --mode hint
```

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
- [Terminal tutor guide](docs/TEXT_TUTOR.md)
- [Learning memory and progression](docs/LEARNING_MEMORY.md)
- [Deterministic verification](docs/DETERMINISTIC_VERIFICATION.md)
- [Local-first architecture decision](docs/decisions/0001-local-first-architecture.md)
- [Runtime and default-model decision](docs/decisions/0002-runtime-and-default-model.md)
- [Terminal tutor architecture decision](docs/decisions/0003-terminal-tutor-architecture.md)
- [Learning-memory architecture decision](docs/decisions/0004-learning-memory-and-progression.md)
- [Deterministic-verification decision](docs/decisions/0005-deterministic-verification.md)
- [Project log](docs/PROJECT_LOG.md)

## Planned phases

1. ~~Benchmark local model and inference-runtime candidates.~~
2. ~~Build a minimal text-based tutoring loop.~~
3. ~~Add persistent skill, attempt, and misconception tracking.~~
4. ~~Add deterministic calculus verification.~~
5. **Build guided review quests and a portfolio-ready interface.**
