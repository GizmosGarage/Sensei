# ADR 0012: Study-guide ingestion as the entry point

- Status: accepted
- Date: 2026-09-02

## Context

After ADR 0011 the generator could imitate class problems, but topics were still typed
by hand, and the learner did not know which topics an exam expected. Their real input
is a study guide: sections of objectives followed by sample exercises with answers. An
earlier PDF import (removed in commit `f158437`) produced topic lists without example
problems, which did not improve problem fidelity.

## Decision

Make document analysis the Dojo's first and only way to create topics. A dedicated
`StudyPlanScanner` sends the document (PDF `input_file`, image `input_image`, or pasted
`input_text`) to the scanner model and returns a strict JSON plan: subject, study-set
name, course profile, and 3-24 skill-level topics, each with a section label, a
practice brief, and up to six representative example problems transcribed with their
printed answers. The plan is shown for review before anything is stored. One compact
retry handles truncated output.

`LearningStore.create_study_plan` writes the folder, topics, class material, and (when
the subject has none) the course profile in one transaction. Re-importing merges:
folder reused, briefs refreshed, duplicate example problems skipped. The manual topic
form is removed; the `/api/study/focus` route remains for tooling and tests.

## Consequences

- One long multimodal call per import; cost and latency scale with document length.
- Topic quality depends on the model's reading of the document; the review step and
  the Class material panel are the correction points.
- Graph-based exercises are transcribed with a bracketed figure description rather than
  the figure itself; the generator still produces structured graphs for graph topics.
- Skill-level granularity means more cards per exam but per-skill mastery visibility.
- Learners without a document cannot create topics from the UI by design.
