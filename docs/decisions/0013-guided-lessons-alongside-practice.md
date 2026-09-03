# ADR 0013: Guided lessons alongside practice

- Status: accepted
- Date: 2026-09-02

## Context

Practice assumes the learner already knows the method: the generator writes an
exam-style problem, the checker grades it, and help steps reveal the solution one move
at a time. Nothing in the Dojo teaches how to tackle a topic before the first problem.
A learner facing a new section had to learn elsewhere and return to practice.

## Decision

Add a **Learn** mode that is separate from practice. Every topic card gets **Learn this
topic** next to **Train this topic**.

- `sensei/lessons.py` mirrors the practice pipeline: `LessonFactory` builds one
  structured lesson from the same study brief (subject, topic, practice instructions,
  course profile, class exemplars, learner signal), validates it strictly, and sends it
  through an independent reviewer that recomputes every worked example and check-in
  answer. Weak spots from the learner signal get their own step.
- A lesson is an overview, four to seven steps, and a closing summary. Each step has an
  explanation, an optional worked example, a key takeaway, and a check-in question with
  a private expected answer and rubric.
- The dashboard reveals steps one at a time. A check-in answer is graded by a short
  stateless model call against the private rubric; a correct or partial verdict
  advances the lesson. A second short call answers free-text follow-up questions about
  any revealed step. Neither call touches practice state.
- Progress is server-authoritative in a new `topic_lessons` table (one row per topic
  with the validated document, `current_step`, `completed_at`, `xp_awarded`). Check-in
  answers never leave SQLite; the public lesson document strips them.
- Completing a lesson awards a one-time 25 XP bonus. Mastery is untouched so it keeps
  meaning "can solve exam problems". `xp_events` is rebuilt so a row references exactly
  one attempt or one lesson; the profile total needs no other change.
- **Start lesson over** replaces the document and resets the step but keeps the row id
  and `xp_awarded`, so the bonus cannot be farmed. **Restart** and **Delete** on a topic
  remove its lesson and the lesson XP along with everything else.
- Lesson generation, grading, and question calls run outside the topic state lock, as
  the scan routes do, so a long lesson draft does not block other writes.

## Consequences

- One long generation call (draft plus review) per topic lesson; two small calls per
  step at most. Lesson quality depends on the class material, like practice.
- Schema version 11. The `xp_events` rebuild runs once with foreign keys off, as the
  earlier table rebuilds did.
- The practice API version moves to 7 so stale dashboards reload.
- Lessons are per topic and per learner: there is no shared lesson library, and a
  regenerated lesson reflects the learner's current signal, not the earlier one.
