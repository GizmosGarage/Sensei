# Project log

## 2026-09-02 - Study-guide ingestion

- Made study-guide analysis the Dojo's entry point: `sensei/curriculum.py` turns a
  PDF, image, or pasted text into a reviewable plan of skill-level topics with
  practice briefs, example problems, and a course profile.
- Added `LearningStore.create_study_plan`, which builds the folder, topics, class
  material, and subject profile in one transaction and merges re-imports.
- Removed the manual topic form; **Train this topic** starts a practice chat directly.

## 2026-09-02 - Class-accurate practice

- Added per-topic class material (pasted or scanned) and subject course profiles in
  schema version 10; generation imitates an anchor exemplar and the reviewer
  rejects easier or off-method drafts.
- Added answer contracts for numeric tolerance, solution sets, intervals, points, and
  multi-part problems with partial credit.
- Fed mastery, recent outcomes, misconceptions, and a difficulty tier into
  generation; added misconception classification on wrong answers and automatic
  resolution after two independent correct answers.
- Added `SENSEI_SCANNER_MODEL` / `--scanner-model` for the multimodal scan.

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
