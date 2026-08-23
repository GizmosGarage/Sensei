# Sensei

Sensei is a local-first, adaptive math tutor. It teaches through guided practice, remembers demonstrated skills and misconceptions, and turns progress into an RPG-style mastery system without requiring paid model inference.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Project status

**Phase 6 complete: interactive dashboard and Precalculus path**

Sensei now has a 20-subject Precalculus path alongside Calculus I. Its loopback-only dashboard can switch courses, filter topics, launch a verifier-backed quest, check the answer locally, and explicitly record XP and mastery into the same student-owned SQLite memory used by the terminal tutor. No hosted inference or cloud storage is involved. The provisional local stack is:

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

Start a scheduled terminal challenge with `/quest`, submit it with `/answer`, and record it with `/done`. Or open the local dashboard:

```powershell
python -m sensei.dashboard
```

Choose **Precalculus** or **Calculus**, select **Practice topic** on any subject, enter an expression, choose **Check answer**, and then **Record attempt** to save XP and mastery. See the [Precalculus path](docs/PRECALCULUS.md) and [dashboard guide](docs/LOCAL_DASHBOARD.md).

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
- [Review quests](docs/REVIEW_QUESTS.md)
- [Precalculus path](docs/PRECALCULUS.md)
- [Local RPG dashboard](docs/LOCAL_DASHBOARD.md)
- [Local-first architecture decision](docs/decisions/0001-local-first-architecture.md)
- [Runtime and default-model decision](docs/decisions/0002-runtime-and-default-model.md)
- [Terminal tutor architecture decision](docs/decisions/0003-terminal-tutor-architecture.md)
- [Learning-memory architecture decision](docs/decisions/0004-learning-memory-and-progression.md)
- [Deterministic-verification decision](docs/decisions/0005-deterministic-verification.md)
- [Quest-and-dashboard decision](docs/decisions/0006-local-quests-and-dashboard.md)
- [Interactive-course-dashboard decision](docs/decisions/0007-interactive-course-dashboard.md)
- [Project log](docs/PROJECT_LOG.md)

## Planned phases

1. ~~Benchmark local model and inference-runtime candidates.~~
2. ~~Build a minimal text-based tutoring loop.~~
3. ~~Add persistent skill, attempt, and misconception tracking.~~
4. ~~Add deterministic calculus verification.~~
5. ~~Build guided review quests and a portfolio-ready interface.~~
6. ~~Add an interactive dashboard practice loop and a complete Precalculus topic path.~~
7. **Bring local-model coaching conversation into the dashboard and deepen each topic's quest pool.**
