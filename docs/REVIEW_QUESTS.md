# Verifier-backed review quests

Review quests turn Sensei's spaced-review recommendation into a concrete problem with a deterministic answer target. In the terminal, the local model can coach and explain without deciding correctness. In the dashboard, the learner can check and record the same kind of quest directly.

## Play loops

Terminal:

```text
/quest
/hint
/answer 3x^2 cos(x^3)
/done
```

`/quest` replaces any active problem with the selected challenge and asks Sensei for one coaching step. `/answer` may be repeated after revisions. A verified-correct answer does not write learning memory automatically; `/done` remains the explicit durable-record boundary.

The dashboard equivalent is **Start quest** or **Practice topic** → **Check answer** → **Record attempt**. The final button is the explicit durable-record boundary.

## Selection and rotation

The catalog contains 40 quests across 30 verifier-backed skills:

- 20 Calculus I quests across calculus foundations, limits, derivative rules, product/quotient/chain rules, antiderivatives, and substitution;
- one starter quest for each of the 20 subjects in the [Precalculus path](PRECALCULUS.md).

Sensei filters the review queue to skills with deterministic quest support. Due work is selected first; otherwise the earliest scheduled eligible skill is used. The dashboard maintains a separate recommendation for each course. A new Precalculus learner begins with properties of exponents, while a new Calculus learner begins with calculus foundations. Within a skill, completed attempt count rotates the template when more than one exists.

Skills without safe quest coverage remain available through ordinary tutoring and `/review`. They are not silently assigned a weak string comparison or model-only correctness check.

## Catalog contract

`config/quests.json` is versioned and validated at startup. Each quest declares an ID, skill, title, student-facing prompt, regression sample, and exactly one verifier target. The supported target kinds are the same derivative, limit, antiderivative, and expression-equivalence checks documented in [deterministic verification](DETERMINISTIC_VERIFICATION.md).

Every sample answer passes through the production verifier in the automated suite. Samples exist to catch catalog or engine regressions; the dashboard API returns neither sample answers nor verifier target configuration.

## Trust and progression

An active quest owns its skill ID, so a model classification cannot credit the attempt to another skill. Its latest conclusive answer check owns correctness. The student's or model's reported outcome remains stored as provenance when the terminal tutor records it.

When both the curated skill and answer are deterministic, mastery confidence is 1.0. Terminal help use and solution reveals still apply the normal mastery caps, and XP remains separate from mastery. The resulting attempt stores `quest_id`, verifier status, submitted and expected forms, and the effective outcome source.

Dashboard checks are not persistence events. A conclusive result is held behind a random, short-lived, one-time token and becomes durable only after **Record attempt**. Replaying that token is rejected.

The general terminal `/check` wizard is disabled while a quest is active. This prevents checking an unrelated easy expression and accidentally attaching that result to the quest.

## Extending the deck

A new quest must:

1. use an existing skill ID;
2. declare only the exact fields for its verifier kind;
3. stay inside the restricted math grammar;
4. include a sample answer that is verified by the test suite;
5. avoid exposing its answer through the public dashboard representation.

Quest depth should grow with deterministic capability. Precalculus currently has one starter quest per subject. Continuity, implicit relations, related rates, optimization, curve analysis, definite integrals, and the fundamental theorem need purpose-built verification before they enter the Calculus deck.
