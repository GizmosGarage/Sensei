# Verifier-backed review quests

Review quests turn Sensei's spaced-review recommendation into a concrete problem with a deterministic answer target. The local model still coaches and explains, but it does not invent the problem or decide whether the submitted answer is correct.

## Play loop

```text
/quest
/hint
/answer 3x^2 cos(x^3)
/done
```

`/quest` replaces any active problem with the selected challenge and asks Sensei for one coaching step. `/answer` may be repeated after revisions. A verified-correct answer does not write learning memory automatically; `/done` remains the explicit durable-record boundary.

## Selection and rotation

The catalog currently contains 20 quests across 10 skills:

- calculus foundations;
- limit concepts and techniques;
- derivative definition and basic derivative rules;
- product, quotient, and chain rules;
- antiderivatives and substitution.

Sensei filters the review queue to skills with deterministic quest support. Due work is selected first; otherwise the earliest scheduled eligible skill is used. A new learner begins with a foundation quest. Within a skill, completed attempt count rotates the template so the next review does not always repeat the same problem.

Skills without safe quest coverage remain available through ordinary tutoring and `/review`. They are not silently assigned a weak string comparison or model-only correctness check.

## Catalog contract

`config/quests.json` is versioned and validated at startup. Each quest declares an ID, skill, title, student-facing prompt, regression sample, and exactly one verifier target. The supported target kinds are the same derivative, limit, antiderivative, and expression-equivalence checks documented in [deterministic verification](DETERMINISTIC_VERIFICATION.md).

Every sample answer passes through the production verifier in the automated suite. Samples exist to catch catalog or engine regressions; the dashboard API returns neither sample answers nor verifier target configuration.

## Trust and progression

An active quest owns its skill ID, so a model classification cannot credit the attempt to another skill. Its latest conclusive `/answer` result owns correctness. The student's or model's reported outcome remains stored as provenance.

When both the curated skill and answer are deterministic, mastery confidence is 1.0. Help use and solution reveals still apply the normal mastery caps, and XP remains separate from mastery. The resulting attempt stores `quest_id`, verifier status, submitted and expected forms, and the effective outcome source.

The general `/check` wizard is disabled while a quest is active. This prevents checking an unrelated easy expression and accidentally attaching that result to the quest.

## Extending the deck

A new quest must:

1. use an existing skill ID;
2. declare only the exact fields for its verifier kind;
3. stay inside the restricted math grammar;
4. include a sample answer that is verified by the test suite;
5. avoid exposing its answer through the public dashboard representation.

Quest coverage should grow with deterministic capability. Continuity, implicit relations, related rates, optimization, curve analysis, definite integrals, and the fundamental theorem need purpose-built verification before they enter the deck.
