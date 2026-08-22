# Deterministic calculus verification

Sensei uses a symbolic verifier as a correctness boundary separate from the language model. The model teaches, asks questions, and identifies likely misconceptions; the verifier checks supported mathematical claims before they affect progress.

## Using `/check`

Start or discuss a problem, then choose a check type:

```text
/check derivative
/check limit
/check antiderivative
/check equivalent
```

The terminal asks only for the fields needed by that check. For example, a derivative check asks for the original function, variable, and proposed derivative. Common terminal notation such as `2x`, `x^2`, `sin(x)`, `sqrt(x)`, `pi`, and `oo` is accepted. Basic forms of `π`, `∞`, `×`, and function-style LaTeX names such as `\sin` are normalized.

Run the check again after revising an answer. Only the latest result is attached to the active problem. `/new`, `/done`, and a new problem clear it.

Curated review quests use the same verifier through `/answer`. Their symbolic target is fixed by the versioned quest catalog, so the general `/check` wizard cannot replace it while a quest is active.

## Supported checks

| Type | Method |
| --- | --- |
| Derivative | Symbolically differentiates the source function and compares the result with the proposal. |
| Limit | Computes the requested one-sided, two-sided, or infinite limit; a finite two-sided check compares both sides. `DNE` is accepted when they differ. |
| Antiderivative | Differentiates the proposed antiderivative and compares that derivative with the integrand, so an arbitrary constant such as `C` is allowed. |
| Equivalent | Simplifies the difference between two expressions and checks symbolic equality on their common domain. |

Each result is `verified_correct`, `verified_incorrect`, or `inconclusive`. An inconclusive result means the engine could not establish the claim; it is not evidence that the answer is wrong.

## Restricted input grammar

The parser does not use Python `eval`, SymPy's general expression parser, or model-generated code. It tokenizes a small grammar, inserts controlled implicit multiplication, parses a Python expression tree, and converts only explicitly allowed nodes into symbolic objects.

Allowed elements include:

- numbers and named variables;
- `+`, `-`, `*`, `/`, and `^` or `**`;
- parentheses and unary signs;
- common trigonometric, inverse trigonometric, hyperbolic, exponential, logarithmic, square-root, and absolute-value functions;
- `pi`, `e`, and positive or negative infinity.

Object attributes, indexing, collections, comprehensions, comparisons, assignments, keywords, arbitrary function calls, and unknown names are rejected. Character, token, syntax-node, nesting, operation, numeric-magnitude, and constant-exponent limits reduce accidental or malicious resource amplification. Compound exponent towers are outside the safe grammar.

## Learning-memory trust rule

A conclusive verifier result is the effective outcome used for XP, mastery, and review scheduling. Sensei also keeps the student- or model-reported outcome and its source. This means a self-report of `correct` can coexist with an effective `verified_incorrect` result without destroying either piece of evidence.

The schema stores the verifier kind and version, submitted and expected forms, status, and concise detail. Existing unverified records remain valid after automatic schema migration.

## Current limitations

- This is a Calculus I expression checker, not a proof assistant.
- It does not yet parse general textbook LaTeX, equations, piecewise definitions, vectors, or multivariable expressions.
- Symbolic equivalence is interpreted on the expressions' common domain; domain restrictions and assumptions are not modeled explicitly.
- Some mathematically equal expressions may remain inconclusive because symbolic simplification is not complete.
- Grammar and operation limits are enforced, but symbolic computation does not yet run in a separate process with a hard wall-clock timeout.
- The verifier checks an answer, not the quality of the student's reasoning. The tutor and stored observable evidence remain responsible for teaching and misconception tracking.

## Implementation basis

The implementation pins SymPy 1.14.0 and uses its documented differentiation, limit, and simplification operations. The equality strategy follows SymPy's guidance to reason about the simplified difference rather than relying only on structural `==`.

- [SymPy installation guide](https://docs.sympy.org/latest/guides/getting_started/install.html)
- [SymPy calculus tutorial](https://docs.sympy.org/latest/tutorial/calculus.html)
- [SymPy equality guidance](https://docs.sympy.org/latest/explanation/gotchas.html)
