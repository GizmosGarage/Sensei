# ADR 0002: Vulkan runtime and provisional default tutor model

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

Sensei needs a local inference stack that works on Windows 11 with an AMD Radeon RX 5700 XT, 8 GB VRAM, and 16 GB system memory. The model must be accurate enough for college calculus, follow progressive-hint boundaries, return structured learning records, and remain responsive.

The GPU exposes a healthy Vulkan device but is not present in AMD's current Windows HIP SDK consumer compatibility table. The application must also remain independent from any single model vendor.

## Decision

Use `llama.cpp` b10549 with the Vulkan backend as the initial local inference runtime.

Use Qwen 3.5 9B Q4_K_M as the provisional default tutor model with:

- 4,096-token context;
- automatic GPU-layer fitting;
- 512 MiB device-memory margin;
- eight CPU threads;
- one inference slot;
- reasoning output disabled.

Use Qwen 3.5 4B Q4_K_M as the lightweight fallback. Access both through an application-owned model-provider interface and the runtime's localhost OpenAI-compatible API.

## Rationale

In the five-model baseline, Qwen 3.5 9B was the only candidate to earn every one of the 23 objective tutoring points. It generated 29.6 tokens/second in the repeated throughput test and averaged 8.03 seconds for a complete non-streaming response. Qwen 3.5 4B earned 21/23 while using less than half the weight-file storage and responding about 23% faster end to end.

The runtime choice provides working GPU acceleration without unsupported ROCm assumptions and supports both CLI benchmarking and an OpenAI-compatible local HTTP boundary.

## Consequences

### Benefits

- No hosted inference usage charges.
- Fully local prompts and responses.
- Reproducible pinned runtime and model artifacts.
- A standard HTTP boundary that keeps the application model-agnostic.
- A lighter fallback for development and constrained configurations.

### Costs and risks

- The default consumes most of the practical 8 GB GPU budget when context and runtime buffers are included.
- Response generation is slower than Gemma and Ministral on this GPU.
- The initial seven-case quality rubric is too small to guarantee calculus reliability.
- The chosen GGUF quantization is produced by a community quantizer even though the base model and license come from Qwen.
- Reasoning must remain disabled until the server can guarantee that internal planning never leaks into student-facing content.

## Revisit conditions

Re-run selection when the benchmark materially expands, when a new 4B-10B model has a reproducible permissive artifact, when hardware changes, or when the default model fails real study sessions in a repeatable way.
