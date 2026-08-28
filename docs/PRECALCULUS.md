# Precalculus path

Sensei's Precalculus path is a first-class course in the local learning-memory catalog. Each subject has its own mastery score, review schedule, dashboard card, and procedurally generated verifier-backed questions.

## Subjects

The path follows this order:

1. Properties of exponents
2. Factoring
3. Fractions / compound fractions
4. Rational expressions
5. Solving polynomial equations
6. Linear equations
7. Linear/nonlinear inequalities
8. Function notation and evaluating functions
9. Domain and range
10. Function composition
11. Inverse functions
12. Parent functions and graph transformations
13. Average rate of change
14. Logarithm properties
15. Exponential equations
16. Logarithmic equations
17. Unit circle
18. Trig graphs
19. Trigonometric equations
20. Trigonometric identities

The dashboard groups these subjects into Precalculus algebra, functions, exponential and logarithmic functions, and trigonometry. Unit filters change only what is shown; they do not erase or split progress.

## Practice from the dashboard

1. Start `python -m sensei.dashboard` from the repository root.
2. Open `http://127.0.0.1:8765/` if the browser does not open automatically.
3. Select **Precalculus** in the course switch.
4. Choose **Practice topic** on any subject card, or use the recommended **Generate quest** button.
5. Enter the answer using `^` for powers and `pi` for π.
6. Select **Check answer**. Sensei's restricted symbolic verifier checks mathematical equivalence locally.
7. Select **Record attempt** to commit the result, XP, mastery evidence, and next review date to local SQLite memory.
8. Select **New question** to generate another challenge in the same subject.

Checking is intentionally separate from recording. A checked result uses a short-lived, one-time token, so refreshing or replaying a request cannot award the same attempt twice.

## Current coverage

Version 0.6.0 provides a dedicated procedural generator for every subject. Each generator changes coefficients, exponents, intervals, angles, functions, or transformation values only within that subject's explicit rules. The production symbolic verifier checks the generated reference answer before the server issues the question.

The hidden target remains in process memory behind a random challenge token and is not returned in the public question document. Immediate duplicate prompts for the same subject are rejected and regenerated. Future milestones can add local-model coaching without changing the course or memory identity.
