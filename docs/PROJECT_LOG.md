# Project log

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
