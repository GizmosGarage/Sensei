# Project log

## 2026-08-27 - Milestone 9: explicit per-problem difficulty

### Completed

- Replaced the ambiguous Foundation/Adaptive/Challenge starting-intensity control with Beginner, Intermediate, Advanced, and Expert problem difficulty.
- Defined concrete generation requirements for all four levels, from one-step essential concepts through synthesis, edge cases, and minimal scaffolding.
- Added a difficulty selector beside every dashboard generation action: first quest, review recommendation, topic card training, and New encounter.
- Made difficulty an encounter-level request while remembering each topic's most recent selection as its next default.
- Required the independent review pass to reject drafts whose setup, step count, scaffolding, or conceptual depth do not fit the selected level.
- Pinned dashboard assets to the server version that loaded them, preventing a running older API from serving newer incompatible JavaScript after a code update.
- Added action-local generation status so topic-card, recommendation, and New encounter failures are visible beside the button that initiated them.
- Added an explicit concise-output budget plus a bounded walkthrough margin so slightly verbose local-model solutions do not consume every generation retry.
- Added validated coordinate-graph data and an accessible SVG renderer so graphical topics require a real graph instead of a prose-only graph description.
- Removed redundant adaptive-answer comparison text and tightened generation instructions so prompts, hints, and walkthroughs do not restate the same facts.
- Retried transient local-model and HTTP generation failures once, while returning generation-specific errors that keep the current encounter usable.
- Migrated schema version 5 difficulty values safely into schema version 6: Foundation to Beginner, Adaptive to Intermediate, and Challenge to Advanced.
- Released the application metadata as version 0.8.0.

### Verification

All 86 automated tests pass. Coverage includes the four difficulty contracts, selected-level propagation, real graph requirements and validation, concise graph-reading prompts, transient generation recovery, per-request HTTP overrides, saved topic defaults, bounded walkthrough verbosity, and foreign-key-safe migration of existing difficulty data.

### Next milestone

- Add multi-turn Socratic conversation inside each browser encounter.
- Offer a mastery-informed suggested difficulty while preserving the learner's explicit override.
- Accept larger source materials through an explicit local ingestion and chunking boundary.

## 2026-08-27 - Milestone 8: learner-directed adaptive questlines

### Completed

- Replaced the dashboard's fixed course-first entry point with subject, topic, optional study material, and difficulty inputs.
- Migrated learning memory to schema version 5 so learner-created subjects coexist with the original catalog and use the same attempts, XP, mastery, misconceptions, and review schedule.
- Added stable subject/topic identities so revisiting the same focus grows one history instead of fragmenting progress.
- Added local-model practice drafting with strict schemas, bounded retries, and a separate recomputation/review pass before issuance.
- Added fresh per-request variation, nondeterministic adaptive seeds, an eight-problem recent history per topic, persisted-attempt exclusions, and hard duplicate rejection before a new encounter can be issued.
- Restricted adaptive encounters to locally checkable expression or four-option answer contracts; hidden answers remain in the server's expiring challenge store.
- Added hints, post-submission walkthroughs, RPG encounter language, a growing mastery atlas, and cross-subject review recommendations to the browser surface.
- Preserved the stronger deterministic Precalculus and Calculus generators and their existing protected API route.
- Integrated local model startup into the dashboard command, with fast-model, existing-server, custom-path, and diagnostic no-model options.
- Generalized the tutor identity and RPG ranks beyond Calculus-only language.
- Released the application metadata as version 0.7.0 and recorded the architecture in ADR 0009.

### Verification

All 78 automated tests pass. Coverage includes schema upgrades from versions 1-4, foreign-key integrity after the flexible-subject migration, learner-topic identity and retrieval, adaptive draft parsing, independent approval, forced-repeat rejection for graphical limits, expression and multiple-choice checks, answer-key-free public documents, full protected HTTP focus/generate/check/record flow, one-time persistence, and every original deterministic generator.

### Next milestone

- Add multi-turn Socratic conversation inside each browser encounter.
- Use recent mastery and misconceptions to tune adaptive difficulty automatically.
- Accept larger source materials through an explicit local ingestion and chunking boundary.

## 2026-08-22 - Milestone 7: subject-confined procedural questions

### Completed

- Added a dedicated procedural question generator for every one of the 37 Precalculus and Calculus subjects.
- Varied coefficients, powers, roots, intervals, transformations, function parameters, unit-circle angles, and trigonometric forms within explicit subject boundaries.
- Ran each generated reference answer through the production symbolic verifier before issuing the question.
- Added a protected generation endpoint that returns only answer-key-free quest metadata and an opaque random challenge token.
- Kept generated answer targets in process memory with a one-hour lifetime; they never enter HTML, browser storage, or the public dashboard snapshot.
- Prevented an immediate repeated prompt in the same subject by regenerating before issuance.
- Added **Generate quest** and **New question** controls and enabled dashboard practice for all seven Calculus disciplines that previously lacked curated browser quests.
- Preserved the explicit **Record attempt** boundary and one-time recording token, so generating or checking alone does not change XP or mastery.
- Released the application metadata as version 0.6.0.

### Verification

All 72 automated tests pass. Coverage now proves that generator IDs exactly match all 37 catalog skills, every subject produces multiple prompt variants, every generated sample is accepted by the production verifier, generated public documents omit answer targets, immediate repeats are rejected, generated-only subjects enter the review queue, protected writes remain enforced, and generated attempts still award and persist progression exactly once. An additional seeded fuzz pass successfully prevalidated 7,400 generated questions across all subjects.

Live loopback validation generated two different factoring prompts in sequence—`x^2 - 13x + 40` and `x^2 - 13x + 36`—with no answer field exposed. The refreshed dashboard remains local on `127.0.0.1:8765`; it was not deployed or given cloud persistence.

### Next milestone

- Add explicit beginner, intermediate, and challenge difficulty bands per subject.
- Bring local-model hints and Socratic coaching into the browser arena.
- Use demonstrated mastery to select parameters and problem forms within the active subject.

## 2026-08-22 - Milestone 6: interactive Precalculus dashboard

### Completed

- Expanded the versioned skill catalog from 17 Calculus disciplines to 37 course-aware disciplines, including the requested 20-subject Precalculus path in its specified order.
- Added one curated, production-verifier-backed starter quest for every Precalculus subject, increasing the catalog from 20 to 40 quests.
- Added independent Precalculus and Calculus review recommendations while retaining the existing learning-memory and scheduling rules.
- Migrated local learning memory to schema version 4 with a required course identity and automatic v1, v2, and v3 upgrade coverage.
- Turned the dashboard into an interactive practice surface with course tabs, unit filters, subject-specific launch buttons, answer entry, local symbolic checking, feedback, and explicit attempt recording.
- Added protected loopback write endpoints with exact-shape request validation, a per-process CSRF token, origin/fetch-metadata checks, bounded request bodies, and short-lived one-time checked-attempt tokens.
- Kept SQLite as the only durable source of truth; the browser still stores no learning history, answer keys, cookies, or model state.
- Renamed progression ranks to course-neutral titles and released the application metadata as version 0.5.0.

### Verification

All 67 automated tests pass, including every one of the 40 quest sample answers, schema upgrades from versions 1-3, exact Precalculus subject coverage, answer-key-free public representations, protected HTTP writes, correct XP persistence, and one-time token replay rejection. Python bytecode compilation also succeeds.

The refreshed local preview on `127.0.0.1:8765` returned health `ok`, 37 skills, 40 public quests, exactly 20 Precalculus skills and quests, the properties-of-exponents starting recommendation, and a live write-session token. The dashboard was handed off to the in-app browser. It remains local-only and was not published to a hosting service.

### Next milestone

- Bring local-model coaching conversation into the browser quest arena.
- Add several difficulty tiers and validated variations per Precalculus subject.
- Add course-specific achievements only after their learning meaning and anti-inflation rules are documented.

## 2026-08-21 - Milestone 5: review quests and local RPG dashboard

### Completed

- Added a validated, versioned catalog of 20 curated quests across 10 verifier-backed Calculus I skills.
- Regression-checked every catalog sample answer through the production symbolic verifier.
- Added `/quest` to choose a challenge from scheduled practiced skills and rotate templates using attempt count.
- Added `/answer` to check the active quest without allowing an unrelated manual check to replace its target.
- Made curated quest skill classification authoritative and preserved the quest ID in each completed attempt.
- Migrated learning memory to schema version 3 with automatic v1→v3 and v2→v3 coverage.
- Removed model-confidence discounting when both a curated skill and its answer are deterministic.
- Added a responsive local dashboard for level, XP, rank, next quest, mastery disciplines, and recent attempts.
- Added an answer-key-free JSON boundary, loopback-only HTTP server, restrictive browser headers, and no browser-owned learning state.
- Added a packaged `sensei-dashboard` entry point and retained the standard-library application stack outside the existing SymPy dependency.

### Live validation

The actual Qwen 3.5 4B Vulkan tutor completed `/quest` → `/answer x^2 - 16` → `/done correct` against a temporary database. The result stored `foundation-difference-squares`, the authoritative `calculus_foundations` skill, verified correctness with confidence 1.0, 100/100 first-attempt evidence, 25 independent XP, and schema version 3. The first local dashboard preview returned level 2, the scheduled `chain-square-root` quest, and all 17 skill records from representative data on `127.0.0.1`.

### Privacy and trust boundary

The dashboard is a local read surface, not a second learning store. It binds only to `127.0.0.1`, serves only fixed packaged assets and GET endpoints, and reads the selected SQLite database. Quest sample answers and symbolic target configuration are not returned by its JSON API. No hosted dashboard was created because Sensei's tutor and learning history are intentionally local-first.

### Next milestone

- Bring the tutor conversation and quest-answer input into the browser surface.
- Add deterministic quests for continuity, implicit differentiation, applications, and definite integrals as verifier support expands.
- Add achievement rules only after their learning meaning and anti-inflation behavior are explicit.

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
