# Local model evaluation plan

## Objective

Choose the best open-weight model and local inference runtime for Sensei on the target computer. The winner must be selected by measured tutoring quality and usability on this hardware, regardless of model vendor.

"Best" means the best complete experience for this project, not the largest parameter count or highest general leaderboard position.

## Hard requirements

- Runs locally without per-token API charges.
- Fits within the target computer's practical GPU and system-memory limits.
- Has a license suitable for a public portfolio project.
- Can explain college calculus accurately.
- Can follow a Socratic tutoring policy and avoid immediately revealing answers.
- Can return reliably parseable structured assessments.
- Has an actively usable local inference path on Windows with an AMD GPU.

## Benchmark tiers

1. **Primary tier:** quantized 7B-9B-class models expected to fit mostly or entirely in GPU memory.
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

Select a default model only after at least one candidate from the primary tier and viable candidates from the stretch tier have completed the same benchmark. Keep the application model-agnostic so a future model can replace the winner without rewriting the learning system.
