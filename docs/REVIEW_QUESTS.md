# Curated and generated review quests

Review quests turn Sensei's spaced-review recommendation into a concrete problem with a deterministic answer target. In the terminal, the local model can coach around a curated catalog problem without deciding correctness. In the dashboard, a subject-specific generator creates a fresh, prevalidated challenge before each attempt.

## Play loops

Terminal:

```text
/quest
/hint
/answer 3x^2 cos(x^3)
/done
```

`/quest` replaces any active problem with the selected challenge and asks Sensei for one coaching step. `/answer` may be repeated after revisions. A verified-correct answer does not write learning memory automatically; `/done` remains the explicit durable-record boundary.

The dashboard equivalent is **Forge a practice quest** or **Train this topic** → **Check answer** → **Record attempt**. **New encounter** repeats generation inside the active subject. The final button is the explicit durable-record boundary.

## Selection and rotation

The terminal catalog contains 40 curated quests across 30 verifier-backed skills:

- 20 Calculus I quests across calculus foundations, limits, derivative rules, product/quotient/chain rules, antiderivatives, and substitution;
- one starter quest for each of the 20 subjects in the [Precalculus path](PRECALCULUS.md).

Sensei filters the terminal review queue to skills with deterministic quest support. Due work is selected first; otherwise the earliest scheduled eligible skill is used. Within a skill, completed attempt count rotates the template when more than one exists.

The dashboard has a procedural generator for all 37 subjects. This includes bounded scalar or expression problems for continuity, implicit differentiation, related rates, optimization, curve analysis, definite integrals, and the fundamental theorem. Questions never cross skill IDs, and immediate prompt repeats within a subject are regenerated.

## Procedural-generation contract

`sensei/generation.py` owns an explicit generator for every catalog skill. A generator may vary only the mathematical parameters and problem forms defined for that skill. It creates a complete internal quest with a hidden reference answer and verifier target, then runs that reference through the production verifier. A failed self-check prevents the question from being issued.

The server keeps a generated question for at most one hour behind a cryptographically random challenge token. The public response contains its ID, skill, course, title, prompt, and check kind, but not the sample answer or verifier configuration. Checking the answer creates a separate 15-minute, single-use recording token.

## Catalog contract

`config/quests.json` is versioned and validated at startup. Each quest declares an ID, skill, title, student-facing prompt, regression sample, and exactly one verifier target. The supported target kinds are the same derivative, limit, antiderivative, and expression-equivalence checks documented in [deterministic verification](DETERMINISTIC_VERIFICATION.md).

Every sample answer passes through the production verifier in the automated suite. Samples exist to catch catalog or engine regressions; the dashboard API returns neither sample answers nor verifier target configuration.

## Trust and progression

An active quest owns its skill ID, so a model classification cannot credit the attempt to another skill. Its latest conclusive answer check owns correctness. The student's or model's reported outcome remains stored as provenance when the terminal tutor records it.

When both the curated skill and answer are deterministic, mastery confidence is 1.0. Terminal help use and solution reveals still apply the normal mastery caps, and XP remains separate from mastery. The resulting attempt stores `quest_id`, verifier status, submitted and expected forms, and the effective outcome source.

Dashboard checks are not persistence events. A conclusive result becomes durable only after **Record attempt**. Replaying its recording token is rejected.

The general terminal `/check` wizard is disabled while a quest is active. This prevents checking an unrelated easy expression and accidentally attaching that result to the quest.

## Extending the deck

A new quest must:

1. use an existing skill ID;
2. declare only the exact fields for its verifier kind;
3. stay inside the restricted math grammar;
4. include a sample answer that is verified by the test suite;
5. avoid exposing its answer through the public dashboard representation.

Quest depth should grow with deterministic capability. The procedural layer now covers every subject, while the terminal's coaching catalog remains curated. Richer domains and multistep proofs still need explicit generation and verification rules before they can influence mastery.
