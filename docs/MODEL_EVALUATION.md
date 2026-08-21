# Local model evaluation plan

## Objective

Choose the best open-weight model and local inference runtime for Sensei on the target computer. The winner must be selected by measured tutoring quality and usability on this hardware, regardless of model vendor.

"Best" means the best complete experience for this project, not the largest parameter count or highest general leaderboard position.

## Outcome

The first baseline is complete. Qwen 3.5 9B Q4_K_M is the provisional default, and Qwen 3.5 4B Q4_K_M is the lighter fallback. Both run locally through `llama.cpp`'s Vulkan backend.

See [Benchmark results](BENCHMARK_RESULTS.md) for the measurements and [ADR 0002](decisions/0002-runtime-and-default-model.md) for the decision.

## Hard requirements

- Runs locally without per-token API charges.
- Fits within the target computer's practical GPU and system-memory limits.
- Has a license suitable for a public portfolio project.
- Can explain college calculus accurately.
- Can follow a Socratic tutoring policy and avoid immediately revealing answers.
- Can return reliably parseable structured assessments.
- Has an actively usable local inference path on Windows with an AMD GPU.

## Benchmark tiers

1. **Primary tier:** quantized 4B-9B-class models expected to fit entirely in GPU memory.
2. **Stretch tier:** selected 12B-14B-class models using partial offload when necessary.
3. **Exceptional candidates:** larger or mixture-of-experts models only when a realistic quantization is interactive on this machine.

Candidates may come from OpenAI, Alibaba/Qwen, Google, Meta, Mistral, DeepSeek, Microsoft, or another provider. Inclusion depends on current model availability, license review, runtime support, and hardware fit.

## Evaluation dimensions

| Dimension | Weight | What will be measured |
| --- | ---: | --- |
| Mathematical correctness | 30% | Correct answers, transformations, domains, and edge cases |
| Teaching quality | 20% | Useful questions, progressive hints, clarity, and adaptation |
| Misconception diagnosis | 15% | Ability to identify why a student's attempt failed |
| Interactive performance | 15% | Time to first token, generation speed, and end-to-end latency |
| Hardware efficiency | 10% | Peak GPU memory, system memory, and stability |
| Structured-output reliability | 5% | Valid responses matching the assessment schema |
| License and maintainability | 5% | Portfolio suitability, redistribution terms, and runtime support |

A model that fails a hard requirement cannot win solely through its weighted score.

## Test set design

Use the same versioned prompts and fixed generation settings for every candidate. The initial test set should include:

- limits and continuity
- derivative rules and derivative definitions
- chain rule and implicit differentiation
- related-rates and optimization word problems
- introductory antiderivatives and definite integrals
- deliberately incorrect student work for misconception diagnosis
- requests that tempt the tutor to reveal the answer too early
- structured assessment output after an interaction

Mathematical results should be checked with deterministic symbolic or numeric tools when possible. Human review is still required for pedagogy and hint quality.

## Measurements to retain

- exact model name, version, quantization, and download source
- model license
- inference runtime and version
- runtime configuration and offload settings
- prompt/test-set version
- time to first token and tokens per second
- peak GPU and system memory
- per-problem correctness and teaching rubric scores
- notable failures and reproducible logs

Raw logs may contain personal study material and remain ignored. Sanitized benchmark summaries and the scripts needed to reproduce them will be committed.

## Decision rule

The initial selection compared five current, hardware-viable artifacts from Google, Mistral AI, and Qwen. Models whose Q4 weights would leave inadequate headroom for a 4,096-token context were screened out before download. Microsoft Phi and DeepSeek candidates were researched, but the relevant community GGUF repositories required authenticated access during this run and were not suitable for the unauthenticated reproducibility requirement.

The application must remain model-agnostic so a future model can replace the winner without rewriting the learning system. The default should be challenged again after the benchmark grows beyond seven cases and whenever a promising hardware-compatible model is released.
