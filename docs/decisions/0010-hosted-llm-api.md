# ADR 0010: Required hosted LLM API

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

Sensei must no longer install, select, download, or run inference artifacts on the
learner's computer. Existing SQLite learning records must remain compatible and
local.

## Decision

Require a hosted OpenAI Responses-compatible API at terminal and dashboard startup.
Read the API key from `SENSEI_LLM_API_KEY` or `OPENAI_API_KEY`; do not accept it
as a command-line argument or persist it. Make the model and API root configurable
through environment variables or non-secret command-line options.

Use `POST /responses` for text and structured JSON, support streaming output, retry
transient failures, and set `store` to `false` on every request. Keep the existing
`ChatProvider` protocol so tutor, extraction, and practice code remain testable
with in-memory providers.

Do not change the SQLite schema, default database path, or progression rules.

## Consequences

- Sensei cannot tutor or generate adaptive practice without valid API credentials.
- No inference runtime or model artifact is installed or managed by the project.
- Learner records remain local and require no data migration.
- Prompt content crosses the configured provider boundary.
- Provider availability, rate limits, and usage charges affect application use.
