# Project log

## 2026-08-29 - Hosted LLM API migration

- Preserved the existing local SQLite schema and default `data/sensei.db` path.
- Replaced bundled inference with a required Responses-compatible hosted API.
- Added environment-based API credentials, model selection, and endpoint overrides.
- Kept API secrets out of command-line arguments, SQLite, logs, and browser state.
- Kept the loopback-only dashboard and deterministic verification boundaries.
- Removed obsolete inference artifacts, download tooling, benchmarks, and setup
  documentation.
- Updated terminal, dashboard, provider, and configuration tests for the API-backed
  architecture.
