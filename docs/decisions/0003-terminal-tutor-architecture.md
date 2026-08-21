# ADR 0003: Terminal tutor and bounded problem context

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

Sensei needs a usable study loop before persistent mastery features are added. A general chat transcript cannot serve as learning memory: it consumes the model context, slows requests, mixes unrelated problems, and does not represent demonstrated mastery in a queryable form.

The application must remain local, work with the selected `llama.cpp` runtime, preserve the ability to change model vendors, and expose enough behavior for automated testing.

## Decision

Build the first interface as a standard-library Python terminal application with four separated responsibilities:

- the CLI handles commands and token rendering;
- `TutorSession` owns pedagogical modes and bounded problem context;
- `ChatProvider` defines the model-independent inference boundary;
- `LocalLlamaRuntime` manages the loopback-only server process.

Every request contains one consolidated system message, the active problem, and at most 12,000 characters of recent exchanges. The active problem is stored separately so trimming cannot remove it. Starting a new problem resets the transient history.

Provide coach, hint, and solution modes. Coach mode advances one small step at a time, hint mode withholds the final answer, and solution mode permits a complete walkthrough.

Do not persist transcripts or infer durable mastery in this milestone. Add those capabilities through a local SQLite boundary in the next architecture decision.

## Rationale

- A terminal interface is fast to build, easy to test, and adequate for real study sessions before UI work.
- The Python standard library is already present and keeps setup small.
- Streaming improves perceived latency on a GPU that generates the default model at roughly 30 tokens per second.
- A provider protocol prevents tutor logic from depending directly on Qwen or `llama.cpp` response handling.
- Problem-scoped trimming solves immediate context growth without inventing an unreliable transcript summarizer.
- Separating transient chat from durable learning state keeps the upcoming memory model explicit and auditable.

## Consequences

### Benefits

- A usable local tutor with no hosted inference charges.
- Immediate first-token feedback and controlled answer-reveal modes.
- Predictable context size across many practice problems.
- Testable lifecycle, schema, prompt, and context behavior.
- A clean insertion point for future local runtimes and persistent memory.

### Costs and risks

- The terminal is not yet a portfolio-ready graphical interface.
- A character budget only approximates token usage.
- The model can still violate pedagogical instructions, so live behavior and expanded evaluations remain necessary.
- Tagged reasoning can be removed from retained context, but token streaming cannot retract text already printed; the runtime-level reasoning-off setting remains the primary safeguard.
- No learning survives process exit until the SQLite milestone is implemented.
