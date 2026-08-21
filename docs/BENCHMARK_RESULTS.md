# Local model benchmark results

## Decision

Use **Qwen 3.5 9B Q4_K_M** as Sensei's provisional default tutor model. Use **Qwen 3.5 4B Q4_K_M** as the lighter fallback for development, reduced memory use, or a future fast mode.

The word *provisional* is important: this is the best model in the first hardware-constrained benchmark, not a claim that it is the best open-weight model for every machine or every calculus course.

## Environment

| Item | Configuration |
| --- | --- |
| Date | 2026-08-21 |
| CPU | AMD Ryzen 7 3800XT, 8 cores / 16 threads |
| GPU | AMD Radeon RX 5700 XT, 8 GB VRAM |
| RAM | 16 GB |
| Runtime | `llama.cpp` b10549 |
| Backend | Vulkan |
| Context target | 4,096 tokens |
| GPU fit margin | 512 MiB |
| Reasoning mode | Off |
| Quality sampling | Temperature 0, seed 42, maximum 512 tokens |

All five artifacts fully offloaded under the runtime's automatic fit configuration.

## Results

| Candidate | Weight file | Quality | Prompt tok/s | Generation tok/s | Mean full response |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen 3.5 9B Q4_K_M | 5.75 GiB | **23/23** | 404.5 | 29.6 | 8.03 s |
| Qwen 3.5 4B Q4_K_M | 2.81 GiB | 21/23 | 732.9 | 36.5 | 6.19 s |
| Ministral 3 8B Instruct Q4_K_M | 4.84 GiB | 17/23 | 373.7 | 54.7 | 3.35 s |
| Ministral 3 8B Reasoning Q4_K_M | 4.84 GiB | 14/23 | 373.4 | 54.8 | 3.54 s |
| Gemma 4 E4B Q4_0 QAT | 4.80 GiB | 12/23 | **727.6** | **66.2** | **1.67 s** |

The committed [machine-readable result](../benchmarks/results/baseline-2026-08-21.json) contains each response, individual rubric checks, timings, runtime metadata, and pinned model revisions. Raw server logs remain ignored.

## Quality cases

The 23-point screening rubric covers seven interactions:

1. Give only the first chain-rule hint and ask a question.
2. Diagnose a missing inner derivative.
3. Correctly solve a rationalization limit.
4. Respect a no-answer boundary on a related-rates hint.
5. Diagnose an incorrect substitution antiderivative.
6. Adapt an explanation to the derivative limit definition.
7. Return an exact structured learning record.

Each response must finish normally. A response that hits its token limit receives zero points even if unfinished text contains rubric keywords.

## Manual review

The automated score is a screening aid, not a substitute for mathematical and pedagogical review.

- Qwen 3.5 9B completed every requested task, respected hint boundaries, and produced valid JSON. Its substitution diagnosis began with an imprecise phrase before giving the correct substitution and result; the tutor prompt and future rubric should become stricter about misconception wording.
- Qwen 3.5 4B produced a good diagnosis for the substitution case but stopped at a hint instead of providing the explicitly requested corrected result.
- Ministral Instruct was stronger than its Reasoning sibling for this conversational tutor configuration.
- Gemma was exceptionally fast but too often withheld requested solutions or failed to include required setup details.

## Reasoning-mode failure discovered

An initial pilot used automatic reasoning with a 256-token reasoning budget. Qwen continued its internal response plan after that budget, exposed planning text in the student-facing content, and sometimes reached the output limit before presenting an answer. Keyword scoring incorrectly rewarded portions of that leaked plan.

The final benchmark therefore:

- disables reasoning output in the server configuration;
- explicitly prohibits planning or self-critique in the system prompt;
- fails any response that does not finish normally;
- saves responses for human inspection.

This corrected configuration produced clean student-facing responses and is the configuration selected for the application.

## Candidate and runtime scope

The shortlist represents current, permissively licensed model families with Q4 artifacts that realistically fit this computer. It is intentionally hardware-constrained rather than exhaustive.

- [Qwen 3.5 9B base model](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Qwen 3.5 9B GGUF artifact](https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF)
- [Qwen 3.5 4B base model](https://huggingface.co/Qwen/Qwen3.5-4B)
- [Qwen 3.5 4B GGUF artifact](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF)
- [Ministral 3 8B Instruct GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF)
- [Ministral 3 8B Reasoning GGUF](https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF)
- [Gemma 4 E4B Q4_0 QAT GGUF](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf)

Larger models were screened out when their quantized weights would consume the practical VRAM/RAM budget before context and application overhead. Older math-specialized candidates remain eligible for a later expanded benchmark when they can be pinned through an unauthenticated, reproducible artifact source.

## Limitations and next evaluation work

- Seven cases are not enough to estimate course-wide calculus reliability.
- The rubric uses deterministic phrase and JSON checks; it can miss equivalent notation or reward shallow keyword matches.
- Mean response time is measured with non-streaming HTTP calls and is not time to first token.
- The benchmark does not yet sample GPU memory continuously.
- Only Q4-class artifacts were compared; a different quantization can change both quality and speed.
- The benchmark needs more limits, continuity, implicit differentiation, optimization, integration, and adversarial student-work cases.

The default model should not be fine-tuned until a much larger evaluation set can demonstrate that tuning improves tutoring without degrading correctness.
