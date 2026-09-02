# ADR 0011: Exemplar-driven, multi-part practice with a learning loop

- Status: accepted
- Date: 2026-09-02

## Context

Learner-directed practice (ADR 0009) generated one problem per topic from three short
strings: subject, topic, and practice instructions. The learner reported that the
problems never matched the complexity or style of their college course. Four causes
were found in the code: Sensei had never seen a real class problem; the answer contract
allowed only one expression or one lettered choice, so the model simplified every
problem to fit; prompt and solution caps of about 700 characters excluded exam-style
work; and generation received no mastery, outcome, or misconception data, so nothing
adapted.

## Decision

Store class material per topic (`topic_materials`) and a course profile per subject
(`subject_profiles`) in schema version 10. Material is pasted as text or transcribed
by a dedicated multimodal scanner call from a PDF or image; the file is never
persisted. Generation prompts include the material as exemplars, name one anchor
exemplar in rotation, and require the draft to be isomorphic to it. The independent
reviewer sees the same exemplars and rejects drafts that are easier, shorter, use a
different method, or copy an exemplar.

Add answer contracts in `sensei/answers.py`: `numeric` with relative tolerance,
`solution_set`, `interval`, `point`, and `multi_part` (2-5 labeled parts, each with
its own contract). Every key is validated against its own checker before a problem is
issued. Multi-part attempts record `correct`, `partial`, or `incorrect`; partial
reuses the existing 55-evidence, 12-XP rule.

Feed a learner signal into generation: mastery score and label, the last five
outcomes, unresolved misconceptions, and a difficulty tier derived by a pure function.
On a wrong or partial answer without a revealed key, run one short classification call
that names the likely misconception; store it with the attempt and resolve it after
two independent correct answers.

## Consequences

- Problem fidelity now depends on what the learner saves; an empty material list
  falls back to standard exam style for the subject.
- Two to three model calls per attempt (draft, review, optional classification) plus
  one per scan; latency and cost rise accordingly.
- Class material and the course profile cross the provider boundary with each
  generation request.
- The local checker remains the correctness boundary; interval and set comparison
  rely on SymPy set semantics and can return inconclusive results.
- Partial credit is coarse (a fixed evidence value) and difficulty tiers are
  heuristics; both are documented as follow-ups.
- The practice API version rises to 6; older dashboard tabs are told to restart.
