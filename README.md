# Sensei

Sensei is a local-first, learner-directed math and chemistry tutor. Name a subject and topic, optionally supply your own material, and Sensei creates checked practice encounters while growing a persistent RPG-style mastery atlas around what you choose to study.

Repository: [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei)

## Project status

**Phase 9 complete: explicit four-level problem difficulty**

Sensei no longer requires a premade course path. Its loopback-only dashboard accepts a subject, a topic, an optional learning objective or source excerpt, and an explicit Beginner, Intermediate, Advanced, or Expert problem difficulty. Difficulty is chosen per encounter from every generation action and remembered as that topic's next default. The local model drafts a confined problem at that level, a separate review pass recomputes and approves both its answer and difficulty fit, and a deterministic answer contract checks the learner's response. Each learner-created topic joins the same student-owned SQLite memory, XP economy, mastery scoring, and spaced-review queue as the original verifier-backed math foundation. No hosted inference or cloud storage is involved. The local stack is:

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

Enter a subject such as **Chemistry**, a focus such as **Stoichiometry**, and any material or emphasis that should shape the encounter. Choose **Forge a practice quest**, answer it, and then claim XP to save the mastery evidence. The topic remains in your growing atlas for later practice and scheduled review. Use `python -m sensei.dashboard --fast` for the lighter local model. See the [dashboard guide](docs/LOCAL_DASHBOARD.md).

## Product principles

- Run the tutor and learning memory locally.
- Treat the model as the teacher, not as permanent storage.
- Ask for a student attempt before revealing a solution.
- Reward effort with XP while measuring mastery separately.
- Verify mathematical answers with deterministic tools where possible.
- Validate model-authored problems before presenting them to the learner.
- Grow the study map from learner intent instead of assuming a universal syllabus.
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
- [Local structured error log](docs/ERROR_LOG.md)
- [Local-first architecture decision](docs/decisions/0001-local-first-architecture.md)
- [Runtime and default-model decision](docs/decisions/0002-runtime-and-default-model.md)
- [Terminal tutor architecture decision](docs/decisions/0003-terminal-tutor-architecture.md)
- [Learning-memory architecture decision](docs/decisions/0004-learning-memory-and-progression.md)
- [Deterministic-verification decision](docs/decisions/0005-deterministic-verification.md)
- [Quest-and-dashboard decision](docs/decisions/0006-local-quests-and-dashboard.md)
- [Interactive-course-dashboard decision](docs/decisions/0007-interactive-course-dashboard.md)
- [Procedural-question-generation decision](docs/decisions/0008-procedural-question-generation.md)
- [Learner-directed-practice decision](docs/decisions/0009-learner-directed-practice.md)
- [Project log](docs/PROJECT_LOG.md)

## Planned phases

1. ~~Benchmark local model and inference-runtime candidates.~~
2. ~~Build a minimal text-based tutoring loop.~~
3. ~~Add persistent skill, attempt, and misconception tracking.~~
4. ~~Add deterministic calculus verification.~~
5. ~~Build guided review quests and a portfolio-ready interface.~~
6. ~~Add an interactive dashboard practice loop and a complete Precalculus topic path.~~
7. ~~Generate fresh, deterministically validated questions inside every subject.~~
8. ~~Replace fixed course selection with learner-created, locally generated questlines.~~
9. ~~Add explicit per-problem Beginner, Intermediate, Advanced, and Expert difficulty.~~
10. **Bring multi-turn coaching conversation into each dashboard encounter.**
