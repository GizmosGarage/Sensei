# Project log

## 2026-08-21 - Milestone 4: deterministic calculus verification

### Completed

- Added a restricted, non-`eval` expression parser with an explicit symbol, function, operator, size, depth, and exponent allowlist.
- Added deterministic checks for derivatives, one- and two-sided limits, basic antiderivatives, and symbolic expression equivalence.
- Added `/check TYPE` as an interactive terminal wizard and attached its latest result to the active problem.
- Added authoritative verifier context to later tutor replies without violating the model's single-system-message constraint.
- Migrated learning memory to schema version 2 with reported outcome, effective source, verification status and kind, verifier version, submitted answer, expected answer, and check detail.
- Made conclusive verification authoritative for XP, mastery, and review scheduling while retaining the conflicting student or model report for auditability.
- Added automatic migration and provenance backfill for existing schema-version-1 databases.
- Added adversarial parser, symbolic equivalence, command integration, tutor-context, outcome-precedence, persistence, and migration tests.

### Verification boundary

Derivative expectations are computed symbolically. Antiderivatives are checked by differentiating the proposal. Finite two-sided limits compare both one-sided results; directional and infinite limits use their requested direction. Expression comparison uses exact and simplified symbolic residuals rather than string equality.

Unsupported syntax is rejected before it reaches the symbolic engine. Supported expressions are still bounded, but symbolic work does not yet run behind a hard wall-clock timeout. A check can therefore return inconclusive, and broader notation, assumptions, domains, piecewise functions, and multivariable calculus remain future work.

### Live validation

A temporary-database workflow was completed through the actual Qwen 3.5 4B Vulkan runtime. The student submitted `cos(x^2)` for the derivative of `sin(x^2)`, then deliberately used `/done correct`. The terminal displayed `VERIFIED INCORRECT`, SQLite retained the student report as `correct`, stored the effective outcome as `incorrect` with source `verifier`, recorded the expected `2*x*cos(x**2)`, and awarded only 5 effort XP. The managed model server shut down cleanly.

### Next milestone

- Turn scheduled reviews into guided practice quests.
- Add an RPG-style progress surface around existing XP, levels, skills, and mastery.
- Design a portfolio-ready local interface without weakening the local-first data boundary.

## 2026-08-21 - Milestone 3: persistent learning memory and progression

### Completed

- Added a versioned SQLite schema with migrations and foreign-key enforcement.
- Added a 17-skill Calculus I catalog with explicit prerequisite relationships.
- Added validated, exact-field learning-event extraction with one repair attempt.
- Added `/done` as the explicit boundary between transient tutoring and durable learning memory.
- Stored problems, outcomes and their source, concise evidence, help use, misconceptions, confidence, and timestamps without storing raw transcripts.
- Added separate mastery, misconception, attempt, and XP records updated in one database transaction.
- Added additive effort XP, increasing RPG level thresholds, confidence-aware mastery evidence, and spaced-review scheduling.
- Added `/profile`, `/skills`, and `/review` progress commands.
- Added compact weak-skill and misconception retrieval for future problem prompts.
- Added JSON export, SQLite backup, confirmed data clearing, custom database paths, and stateless mode.
- Added storage, progression, extraction, catalog, adaptive-context, and terminal-format tests.

### Live validation

A temporary-database workflow was completed through the actual Qwen 3.5 4B Vulkan runtime: two tutoring turns, `/done incorrect`, model extraction, SQLite persistence, XP/mastery update, review recommendation, JSON export, backup, and clean shutdown.

The stored chain-rule misconception was then loaded into a later `cos(x^3)` problem. Qwen focused on the outer/inner structure but initially gave too many steps. The new-problem request was tightened and revalidated; the fallback then stopped after one conceptual step and one student question.

### Trust boundary

Student-reported outcomes are authoritative when supplied to `/done` and are recorded with `outcome_source=student`; otherwise the model classifies the outcome and the source is recorded as `model`. Neither is yet a deterministic proof of mathematical correctness. Confidence reduces uncertain mastery movement toward neutral, XP is never removed, and the next milestone will add symbolic/numeric verification before correctness can become high-confidence mastery evidence.

### Next milestone

- Add a deterministic expression and numeric-equivalence verification boundary.
- Verify derivatives, limits, and basic antiderivatives independently from model prose.
- Distinguish verified correctness from student- or model-reported outcomes.
- Expand evaluation cases for equivalent notation, domains, constants of integration, and undefined expressions.

## 2026-08-21 - Milestone 2: local terminal tutor

### Completed

- Added an installable Python package and `python -m sensei` entry point with no third-party runtime dependencies.
- Added a model-provider boundary around the local OpenAI-compatible API.
- Added automatic, loopback-only `llama.cpp` startup and reliable shutdown.
- Added token streaming, completion-schema validation, bounded retry behavior, and normal-completion enforcement.
- Added coach, one-hint, and complete-solution modes with explicit answer boundaries.
- Added problem-scoped context that always retains the active problem while limiting recent chat history to 12,000 characters.
- Added `/hint`, `/solve`, `/new`, `/status`, `/help`, and `/quit` terminal commands plus a one-shot automation mode.
- Added safeguards that disable reasoning at the server and remove tagged reasoning from the final stored turn.
- Added tests for the provider, stream parser, model catalog, runtime command, tutor context policy, and CLI.
- Validated streaming against Qwen 3.5 9B and a multi-turn session against the Qwen 3.5 4B fallback on the target GPU.

### Failure found during live validation

The first live request failed because Qwen's chat template requires the system message to appear only once at the beginning. The tutor originally sent separate system messages for its identity, help mode, and problem. Those instructions are now consolidated into one system message, and a regression test enforces the requirement.

The first 4B coach response also advanced through too many steps. The coach contract was tightened to one small next step and one question, then revalidated against the local fallback model.

### Context and privacy boundary

This milestone deliberately does not treat chat history as learning memory. The active problem and recent exchanges exist only for the running process, runtime logs are stored under ignored `data/`, and model weights remain ignored. Durable skills, attempts, misconceptions, mastery, and XP belong in the next SQLite milestone.

### Next milestone

- Define and migrate the local SQLite learning-state schema.
- Extract a validated learning event after each completed problem interaction.
- Store skills, attempts, misconceptions, mastery evidence, and review scheduling independently from chat context.
- Add export, backup, and deletion controls for student-owned data.

## 2026-08-21 - Milestone 1: local runtime and model baseline

### Completed

- Validated Vulkan 1.4 acceleration on the AMD Radeon RX 5700 XT.
- Selected the portable `llama.cpp` b10549 Vulkan runtime after comparing Windows/AMD inference paths.
- Added a pinned model manifest with revisions, sizes, licenses, and SHA-256 hashes.
- Added a resumable, range-validated model downloader that keeps weights out of Git.
- Added a reproducible performance and calculus-tutoring benchmark with completion gating.
- Added evaluator and configuration tests using only the Python standard library.
- Downloaded, verified, and benchmarked five cross-vendor Q4 model artifacts.
- Caught an initial Qwen reasoning-trace leak and corrected the production configuration by disabling reasoning output.
- Selected Qwen 3.5 9B Q4_K_M as the provisional default and Qwen 3.5 4B Q4_K_M as the lighter fallback.
- Sanitized benchmark results for public repository use.

### Baseline result

Qwen 3.5 9B earned 23/23 automated rubric points, generated 29.6 tokens/second in `llama-bench`, and averaged 8.03 seconds across seven non-streaming tutoring responses. This is a provisional result from a deliberately small test set, not a claim of universal model superiority.

### Next milestone

- Build the minimal text-based tutoring loop against a model-provider interface.
- Stream responses from the local OpenAI-compatible server.
- Add deterministic schema validation and retry behavior.
- Begin the local SQLite learning-state schema.

## 2026-08-21 - Milestone 0: project baseline

### Recorded

- Defined Sensei as a local-first adaptive calculus tutor.
- Confirmed that model selection is vendor-neutral and will use open-weight candidates.
- Captured the target computer's CPU, GPU, GPU memory, system memory, operating system, and available storage.
- Established a reproducible model-evaluation framework.
- Accepted local inference and local learning memory as the first architecture decision.
- Added ignore rules for model weights, personal study records, databases, raw benchmark output, and secrets.
- Initialized the Git repository on `main` and published it publicly at [GizmosGarage/Sensei](https://github.com/GizmosGarage/Sensei).

### Decisions pending

- Benchmark implementation language and application stack
- Application framework and user interface
