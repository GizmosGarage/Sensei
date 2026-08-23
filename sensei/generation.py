"""Subject-confined procedural quests validated before they reach a learner."""

from __future__ import annotations

import random
import secrets
from fractions import Fraction
from typing import Callable

from sensei.quests import QuestTemplate
from sensei.verification import CalculusVerifier, VerificationStatus


GENERATED_SKILL_IDS = (
    "calculus_foundations",
    "limit_concepts",
    "limit_techniques",
    "continuity",
    "derivative_definition",
    "basic_derivative_rules",
    "product_rule",
    "quotient_rule",
    "chain_rule",
    "implicit_differentiation",
    "related_rates",
    "optimization",
    "curve_analysis",
    "antiderivatives",
    "definite_integrals",
    "fundamental_theorem",
    "u_substitution",
    "precalc_exponent_properties",
    "precalc_factoring",
    "precalc_compound_fractions",
    "precalc_rational_expressions",
    "precalc_polynomial_equations",
    "precalc_linear_equations",
    "precalc_inequalities",
    "precalc_function_evaluation",
    "precalc_domain_range",
    "precalc_function_composition",
    "precalc_inverse_functions",
    "precalc_graph_transformations",
    "precalc_average_rate_change",
    "precalc_log_properties",
    "precalc_exponential_equations",
    "precalc_logarithmic_equations",
    "precalc_unit_circle",
    "precalc_trig_graphs",
    "precalc_trig_equations",
    "precalc_trig_identities",
)


def _signed(value: int) -> str:
    return f"+ {value}" if value >= 0 else f"- {abs(value)}"


def _coefficient(value: int, expression: str) -> str:
    if value == 1:
        return expression
    if value == -1:
        return f"-{expression}"
    return f"{value}{expression}"


def _signed_term(value: int, expression: str) -> str:
    operator = "+" if value >= 0 else "-"
    return f"{operator} {_coefficient(abs(value), expression)}"


def _shift(variable: str, value: int) -> str:
    return f"{variable} + {value}" if value >= 0 else f"{variable} - {abs(value)}"


def _linear(a: int, b: int) -> str:
    return f"{_coefficient(a, 'x')} {_signed(b)}"


def _quadratic(a: int, b: int, c: int) -> str:
    return f"{_coefficient(a, 'x^2')} {_signed_term(b, 'x')} {_signed(c)}"


def _fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


class GeneratedQuestFactory:
    """Creates fresh questions inside an explicit generator for each skill."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.SystemRandom()
        self.verifier = CalculusVerifier()
        self._generators: dict[str, Callable[[], QuestTemplate]] = {
            "calculus_foundations": self._calculus_foundations,
            "limit_concepts": self._limit_concepts,
            "limit_techniques": self._limit_techniques,
            "continuity": self._continuity,
            "derivative_definition": self._derivative_definition,
            "basic_derivative_rules": self._basic_derivative_rules,
            "product_rule": self._product_rule,
            "quotient_rule": self._quotient_rule,
            "chain_rule": self._chain_rule,
            "implicit_differentiation": self._implicit_differentiation,
            "related_rates": self._related_rates,
            "optimization": self._optimization,
            "curve_analysis": self._curve_analysis,
            "antiderivatives": self._antiderivatives,
            "definite_integrals": self._definite_integrals,
            "fundamental_theorem": self._fundamental_theorem,
            "u_substitution": self._u_substitution,
            "precalc_exponent_properties": self._exponent_properties,
            "precalc_factoring": self._factoring,
            "precalc_compound_fractions": self._compound_fractions,
            "precalc_rational_expressions": self._rational_expressions,
            "precalc_polynomial_equations": self._polynomial_equations,
            "precalc_linear_equations": self._linear_equations,
            "precalc_inequalities": self._inequalities,
            "precalc_function_evaluation": self._function_evaluation,
            "precalc_domain_range": self._domain_range,
            "precalc_function_composition": self._function_composition,
            "precalc_inverse_functions": self._inverse_functions,
            "precalc_graph_transformations": self._graph_transformations,
            "precalc_average_rate_change": self._average_rate_change,
            "precalc_log_properties": self._log_properties,
            "precalc_exponential_equations": self._exponential_equations,
            "precalc_logarithmic_equations": self._logarithmic_equations,
            "precalc_unit_circle": self._unit_circle,
            "precalc_trig_graphs": self._trig_graphs,
            "precalc_trig_equations": self._trig_equations,
            "precalc_trig_identities": self._trig_identities,
        }

    @property
    def skill_ids(self) -> frozenset[str]:
        return frozenset(self._generators)

    def generate(self, skill_id: str) -> QuestTemplate:
        try:
            quest = self._generators[skill_id]()
        except KeyError as error:
            raise ValueError(
                f"Fresh question generation is unavailable for skill {skill_id!r}."
            ) from error
        result = quest.check(quest.sample_answer, self.verifier)
        if result.status is not VerificationStatus.VERIFIED_CORRECT:
            raise RuntimeError(
                f"Generated quest {quest.id!r} failed its answer validation."
            )
        return quest

    def _quest(
        self,
        skill_id: str,
        title: str,
        prompt: str,
        sample_answer: str,
        verification: dict[str, str],
    ) -> QuestTemplate:
        suffix = secrets.token_hex(5)
        return QuestTemplate(
            id=f"generated-{skill_id.replace('_', '-')}-{suffix}",
            skill_id=skill_id,
            title=title,
            prompt=prompt,
            sample_answer=sample_answer,
            verification=verification,
        )

    def _equivalent(
        self,
        skill_id: str,
        title: str,
        prompt: str,
        answer: str,
    ) -> QuestTemplate:
        return self._quest(
            skill_id,
            title,
            prompt,
            answer,
            {"kind": "equivalent", "reference": answer, "variable": "x"},
        )

    def _derivative(
        self,
        skill_id: str,
        title: str,
        prompt: str,
        expression: str,
        answer: str,
    ) -> QuestTemplate:
        return self._quest(
            skill_id,
            title,
            prompt,
            answer,
            {"kind": "derivative", "expression": expression, "variable": "x"},
        )

    def _limit(
        self,
        skill_id: str,
        title: str,
        prompt: str,
        expression: str,
        point: str,
        answer: str,
    ) -> QuestTemplate:
        return self._quest(
            skill_id,
            title,
            prompt,
            answer,
            {
                "kind": "limit",
                "expression": expression,
                "variable": "x",
                "point": point,
                "direction": "both",
            },
        )

    def _antiderivative(
        self,
        skill_id: str,
        title: str,
        prompt: str,
        integrand: str,
        answer: str,
    ) -> QuestTemplate:
        return self._quest(
            skill_id,
            title,
            prompt,
            answer,
            {
                "kind": "antiderivative",
                "integrand": integrand,
                "variable": "x",
            },
        )

    def _calculus_foundations(self) -> QuestTemplate:
        if self.rng.randrange(2) == 0:
            value = self.rng.randint(2, 10)
            return self._equivalent(
                "calculus_foundations",
                "Foundation Forge",
                f"Expand and simplify (x + {value})(x - {value}).",
                f"x^2-{value * value}",
            )
        outside = self.rng.randint(2, 7)
        shift = self.rng.randint(1, 8)
        coefficient = self.rng.randint(2, 7)
        return self._equivalent(
            "calculus_foundations",
            "Algebra Tempering",
            f"Simplify {outside}(x + {shift}) + {coefficient}x.",
            f"{outside + coefficient}*x+{outside * shift}",
        )

    def _limit_concepts(self) -> QuestTemplate:
        if self.rng.randrange(2) == 0:
            coefficient = self.rng.randint(2, 9)
            return self._limit(
                "limit_concepts",
                "Sine Threshold",
                f"Evaluate lim as x approaches 0 of sin({coefficient}x)/x.",
                f"sin({coefficient}*x)/x",
                "0",
                str(coefficient),
            )
        point = self.rng.randint(-5, 5)
        shifted = _shift("x", -point)
        return self._limit(
            "limit_concepts",
            "Two-Sided Gate",
            f"Evaluate lim as x approaches {point} of "
            f"abs({shifted})/({shifted}). Enter DNE if it does not exist.",
            f"abs(x-({point}))/(x-({point}))",
            str(point),
            "DNE",
        )

    def _limit_techniques(self) -> QuestTemplate:
        root = self.rng.choice([value for value in range(-7, 8) if value != 0])
        return self._limit(
            "limit_techniques",
            "Factor Passage",
            f"Evaluate lim as x approaches {root} of "
            f"(x^2 - {root * root})/({_shift('x', -root)}).",
            f"(x^2-{root * root})/(x-({root}))",
            str(root),
            str(2 * root),
        )

    def _continuity(self) -> QuestTemplate:
        point = self.rng.randint(-5, 5)
        slope = self.rng.choice([value for value in range(-6, 7) if value != 0])
        intercept = self.rng.randint(-8, 8)
        answer = slope * point + intercept
        return self._equivalent(
            "continuity",
            "Continuity Bridge",
            f"Let f(x) = {_linear(slope, intercept)} for x != {point}, and "
            f"f({point}) = k. Find k so f is continuous at x = {point}.",
            str(answer),
        )

    def _derivative_definition(self) -> QuestTemplate:
        a = self.rng.randint(1, 6)
        b = self.rng.randint(-8, 8)
        c = self.rng.randint(-8, 8)
        expression = f"{a}*x^2+({b})*x+({c})"
        return self._derivative(
            "derivative_definition",
            "First-Principles Trial",
            "Use the derivative definition on paper to find f'(x) for "
            f"f(x) = {_quadratic(a, b, c)}.",
            expression,
            f"{2 * a}*x+({b})",
        )

    def _basic_derivative_rules(self) -> QuestTemplate:
        high_power = self.rng.randint(4, 8)
        low_power = self.rng.randint(2, high_power - 1)
        a = self.rng.randint(2, 6)
        b = self.rng.choice([value for value in range(-7, 8) if value != 0])
        c = self.rng.randint(-9, 9)
        expression = f"{a}*x^{high_power}+({b})*x^{low_power}+({c})"
        answer = (
            f"{a * high_power}*x^{high_power - 1}"
            f"+({b * low_power})*x^{low_power - 1}"
        )
        return self._derivative(
            "basic_derivative_rules",
            "Power Rule Kata",
            f"Differentiate {a}x^{high_power} {_signed(b)}x^{low_power} "
            f"{_signed(c)} with respect to x.",
            expression,
            answer,
        )

    def _product_rule(self) -> QuestTemplate:
        power = self.rng.randint(2, 6)
        constant = self.rng.randint(1, 8)
        polynomial = f"x^{power}+{constant}"
        expression = f"({polynomial})*sin(x)"
        answer = (
            f"{power}*x^{power - 1}*sin(x)+({polynomial})*cos(x)"
        )
        return self._derivative(
            "product_rule",
            "Product Rule Duel",
            f"Differentiate (x^{power} + {constant})sin(x) with respect to x.",
            expression,
            answer,
        )

    def _quotient_rule(self) -> QuestTemplate:
        constant = self.rng.randint(1, 12)
        expression = f"(x^2+{constant})/x"
        answer = f"(x^2-{constant})/x^2"
        return self._derivative(
            "quotient_rule",
            "Quotient Rule Duel",
            f"Differentiate (x^2 + {constant})/x with respect to x.",
            expression,
            answer,
        )

    def _chain_rule(self) -> QuestTemplate:
        power = self.rng.randint(2, 6)
        constant = self.rng.randint(1, 8)
        inner = f"x^{power}+{constant}"
        return self._derivative(
            "chain_rule",
            "Nested Sine",
            f"Differentiate sin(x^{power} + {constant}) with respect to x.",
            f"sin({inner})",
            f"{power}*x^{power - 1}*cos({inner})",
        )

    def _implicit_differentiation(self) -> QuestTemplate:
        x_value, y_value, radius = self.rng.choice(
            [(3, 4, 5), (4, 3, 5), (5, 12, 13), (12, 5, 13), (8, 15, 17)]
        )
        return self._equivalent(
            "implicit_differentiation",
            "Implicit Circle",
            f"For x^2 + y^2 = {radius * radius}, find dy/dx at ({x_value}, {y_value}).",
            f"-{x_value}/{y_value}",
        )

    def _related_rates(self) -> QuestTemplate:
        radius = self.rng.randint(2, 12)
        rate = self.rng.randint(1, 6)
        return self._equivalent(
            "related_rates",
            "Expanding Circle",
            f"A circle's radius grows at {rate} units/s. Find dA/dt when "
            f"r = {radius}. Give an exact answer using pi.",
            f"{2 * radius * rate}*pi",
        )

    def _optimization(self) -> QuestTemplate:
        side = self.rng.randint(3, 15)
        perimeter = 4 * side
        return self._equivalent(
            "optimization",
            "Rectangle Summit",
            f"A rectangle has perimeter {perimeter}. What is its maximum possible area?",
            str(side * side),
        )

    def _curve_analysis(self) -> QuestTemplate:
        a = self.rng.randint(1, 6)
        critical = self.rng.choice([value for value in range(-6, 7) if value != 0])
        b = -2 * a * critical
        c = self.rng.randint(-9, 9)
        return self._equivalent(
            "curve_analysis",
            "Critical Point Scout",
            f"Find the x-coordinate of the critical point of f(x) = {_quadratic(a, b, c)}.",
            str(critical),
        )

    def _antiderivatives(self) -> QuestTemplate:
        power = self.rng.randint(2, 6)
        multiplier = self.rng.randint(1, 5)
        coefficient = multiplier * (power + 1)
        constant = self.rng.choice([value for value in range(-7, 8) if value != 0])
        integrand = f"{coefficient}*x^{power}+({constant})"
        answer = f"{multiplier}*x^{power + 1}+({constant})*x"
        return self._antiderivative(
            "antiderivatives",
            "Reverse Power Kata",
            f"Find an antiderivative of {coefficient}x^{power} {_signed(constant)}.",
            integrand,
            answer,
        )

    def _definite_integrals(self) -> QuestTemplate:
        slope = self.rng.randint(1, 6)
        intercept = self.rng.randint(-6, 6)
        lower = self.rng.randint(-3, 3)
        upper = lower + self.rng.randint(2, 6)
        answer = Fraction(slope * (upper * upper - lower * lower), 2)
        answer += intercept * (upper - lower)
        return self._equivalent(
            "definite_integrals",
            "Area Ledger",
            f"Evaluate the definite integral from {lower} to {upper} of "
            f"({_linear(slope, intercept)}) dx.",
            _fraction_text(answer),
        )

    def _fundamental_theorem(self) -> QuestTemplate:
        lower = self.rng.randint(-5, 5)
        power = self.rng.randint(2, 6)
        constant = self.rng.randint(1, 9)
        return self._equivalent(
            "fundamental_theorem",
            "FTC Gateway",
            f"Let F(x) = integral from {lower} to x of (t^{power} + {constant}) dt. Find F'(x).",
            f"x^{power}+{constant}",
        )

    def _u_substitution(self) -> QuestTemplate:
        power = self.rng.randint(2, 6)
        constant = self.rng.randint(1, 8)
        inner = f"x^{power}+{constant}"
        if self.rng.randrange(2) == 0:
            function = "cos"
            answer = f"sin({inner})"
        else:
            function = "exp"
            answer = f"exp({inner})"
        integrand = f"{power}*x^{power - 1}*{function}({inner})"
        return self._antiderivative(
            "u_substitution",
            "Reverse Chain Quest",
            f"Use substitution to find an antiderivative of {power}x^{power - 1} "
            f"{function}(x^{power} + {constant}).",
            integrand,
            answer,
        )

    def _exponent_properties(self) -> QuestTemplate:
        first = self.rng.randint(3, 10)
        second = self.rng.randint(3, 10)
        divisor = self.rng.randint(1, min(first + second - 1, 9))
        result = first + second - divisor
        return self._equivalent(
            "precalc_exponent_properties",
            "Exponent Forge",
            f"Simplify (x^{first} x^{second})/x^{divisor} using exponent properties.",
            f"x^{result}",
        )

    def _factoring(self) -> QuestTemplate:
        first, second = self.rng.sample(range(1, 11), 2)
        middle = -(first + second)
        constant = first * second
        return self._equivalent(
            "precalc_factoring",
            "Factor Foundry",
            f"Factor x^2 {_signed(middle)}x + {constant} completely.",
            f"(x-{first})*(x-{second})",
        )

    def _compound_fractions(self) -> QuestTemplate:
        denominator = self.rng.randint(2, 12)
        return self._equivalent(
            "precalc_compound_fractions",
            "Fraction Labyrinth",
            f"Simplify 1/(1/x + 1/{denominator}).",
            f"{denominator}*x/(x+{denominator})",
        )

    def _rational_expressions(self) -> QuestTemplate:
        root = self.rng.randint(2, 12)
        return self._equivalent(
            "precalc_rational_expressions",
            "Rational Reduction",
            f"Simplify (x^2 - {root * root})/(x - {root}). "
            "Keep the original restriction in your written work.",
            f"x+{root}",
        )

    def _polynomial_equations(self) -> QuestTemplate:
        first, second = self.rng.sample(range(-8, 9), 2)
        middle = -(first + second)
        constant = first * second
        return self._equivalent(
            "precalc_polynomial_equations",
            "Polynomial Gate",
            f"Solve x^2 {_signed(middle)}x {_signed(constant)} = 0 "
            "and submit the larger solution.",
            str(max(first, second)),
        )

    def _linear_equations(self) -> QuestTemplate:
        coefficient = self.rng.randint(2, 10)
        solution = self.rng.randint(-9, 9)
        intercept = self.rng.randint(-12, 12)
        right_side = coefficient * solution + intercept
        return self._equivalent(
            "precalc_linear_equations",
            "Linear Balance",
            f"Solve {_linear(coefficient, intercept)} = {right_side} for x.",
            str(solution),
        )

    def _inequalities(self) -> QuestTemplate:
        if self.rng.randrange(2) == 0:
            coefficient = self.rng.randint(2, 9)
            largest = self.rng.randint(-6, 8)
            intercept = self.rng.randint(-10, 10)
            right_side = coefficient * (largest + 1) + intercept
            prompt = (
                f"Find the largest integer satisfying "
                f"{_linear(coefficient, intercept)} < {right_side}."
            )
            answer = largest
        else:
            boundary = self.rng.randint(2, 10)
            prompt = (
                f"Find the largest integer satisfying x^2 < {boundary * boundary}."
            )
            answer = boundary - 1
        return self._equivalent(
            "precalc_inequalities",
            "Inequality Boundary",
            prompt,
            str(answer),
        )

    def _function_evaluation(self) -> QuestTemplate:
        a = self.rng.randint(1, 5)
        b = self.rng.randint(-7, 7)
        c = self.rng.randint(-9, 9)
        value = self.rng.randint(-5, 5)
        answer = a * value * value + b * value + c
        return self._equivalent(
            "precalc_function_evaluation",
            "Function Call",
            f"Let f(x) = {_quadratic(a, b, c)}. Evaluate f({value}).",
            str(answer),
        )

    def _domain_range(self) -> QuestTemplate:
        horizontal = self.rng.choice([value for value in range(-8, 9) if value != 0])
        if self.rng.randrange(2) == 0:
            return self._equivalent(
                "precalc_domain_range",
                "Domain Threshold",
                f"For f(x) = sqrt({_shift('x', -horizontal)}), what is the "
                "smallest real x in the domain?",
                str(horizontal),
            )
        vertical = self.rng.randint(-8, 8)
        return self._equivalent(
            "precalc_domain_range",
            "Range Threshold",
            f"For f(x) = ({_shift('x', -horizontal)})^2 {_signed(vertical)}, "
            "what is the smallest y-value in the range?",
            str(vertical),
        )

    def _function_composition(self) -> QuestTemplate:
        a = self.rng.choice([value for value in range(-5, 6) if value not in {0}])
        b = self.rng.randint(-7, 7)
        c = self.rng.choice([value for value in range(-5, 6) if value not in {0}])
        d = self.rng.randint(-7, 7)
        return self._equivalent(
            "precalc_function_composition",
            "Composition Chamber",
            f"Let f(x) = {_linear(a, b)} and g(x) = {_linear(c, d)}. Find (f o g)(x).",
            f"{a * c}*x+({a * d + b})",
        )

    def _inverse_functions(self) -> QuestTemplate:
        coefficient = self.rng.choice(
            [value for value in range(-8, 9) if value not in {-1, 0, 1}]
        )
        intercept = self.rng.randint(-10, 10)
        return self._equivalent(
            "precalc_inverse_functions",
            "Inverse Mirror",
            f"Find the inverse of f(x) = {_linear(coefficient, intercept)}. Submit f^(-1)(x).",
            f"(x-({intercept}))/{coefficient}",
        )

    def _graph_transformations(self) -> QuestTemplate:
        horizontal = self.rng.choice([value for value in range(-7, 8) if value != 0])
        vertical = self.rng.choice([value for value in range(-7, 8) if value != 0])
        horizontal_words = (
            f"right {horizontal}" if horizontal > 0 else f"left {abs(horizontal)}"
        )
        vertical_words = (
            f"up {vertical}" if vertical > 0 else f"down {abs(vertical)}"
        )
        return self._equivalent(
            "precalc_graph_transformations",
            "Graph Shifter",
            f"Start with y = x^2. Shift it {horizontal_words} units and "
            f"{vertical_words} units. Submit the transformed formula.",
            f"(x-({horizontal}))^2+({vertical})",
        )

    def _average_rate_change(self) -> QuestTemplate:
        a = self.rng.randint(1, 5)
        b = self.rng.randint(-7, 7)
        c = self.rng.randint(-9, 9)
        first = self.rng.randint(-5, 3)
        second = first + self.rng.randint(2, 7)
        answer = a * (first + second) + b
        return self._equivalent(
            "precalc_average_rate_change",
            "Rate Crossing",
            "Find the average rate of change of "
            f"f(x) = {_quadratic(a, b, c)} from x = {first} to x = {second}.",
            str(answer),
        )

    def _log_properties(self) -> QuestTemplate:
        first = self.rng.randint(2, 15)
        second = self.rng.randint(2, 15)
        return self._equivalent(
            "precalc_log_properties",
            "Logarithm Seal",
            f"Condense log({first}) + log({second}) into one logarithm.",
            f"log({first * second})",
        )

    def _exponential_equations(self) -> QuestTemplate:
        base = self.rng.randint(2, 6)
        shift = self.rng.randint(-5, 5)
        exponent = self.rng.randint(2, 7)
        return self._equivalent(
            "precalc_exponential_equations",
            "Exponential Lock",
            f"Solve {base}^(x {_signed(shift)}) = {base ** exponent} for x.",
            str(exponent - shift),
        )

    def _logarithmic_equations(self) -> QuestTemplate:
        base = self.rng.randint(2, 6)
        shift = self.rng.randint(-6, 6)
        exponent = self.rng.randint(2, 5)
        return self._equivalent(
            "precalc_logarithmic_equations",
            "Logarithmic Lock",
            f"Solve log base {base} of (x {_signed(shift)}) = {exponent} for x.",
            str(base**exponent - shift),
        )

    def _unit_circle(self) -> QuestTemplate:
        angle, sine, cosine = self.rng.choice(
            [
                ("0", "0", "1"),
                ("pi/6", "1/2", "sqrt(3)/2"),
                ("pi/4", "sqrt(2)/2", "sqrt(2)/2"),
                ("pi/3", "sqrt(3)/2", "1/2"),
                ("pi/2", "1", "0"),
                ("2pi/3", "sqrt(3)/2", "-1/2"),
                ("3pi/4", "sqrt(2)/2", "-sqrt(2)/2"),
                ("5pi/6", "1/2", "-sqrt(3)/2"),
                ("pi", "0", "-1"),
                ("7pi/6", "-1/2", "-sqrt(3)/2"),
                ("5pi/4", "-sqrt(2)/2", "-sqrt(2)/2"),
                ("3pi/2", "-1", "0"),
                ("7pi/4", "-sqrt(2)/2", "sqrt(2)/2"),
                ("11pi/6", "-1/2", "sqrt(3)/2"),
            ]
        )
        function, answer = self.rng.choice([("sin", sine), ("cos", cosine)])
        return self._equivalent(
            "precalc_unit_circle",
            "Unit Circle Compass",
            f"Evaluate {function}({angle}) exactly.",
            answer,
        )

    def _trig_graphs(self) -> QuestTemplate:
        amplitude = self.rng.choice([value for value in range(-6, 7) if value not in {0}])
        frequency = self.rng.randint(1, 5)
        midline = self.rng.choice([value for value in range(-7, 8) if value != 0])
        formula = (
            f"y = {_coefficient(amplitude, f'sin({frequency}x)')} "
            f"{_signed(midline)}"
        )
        if self.rng.randrange(2) == 0:
            prompt = f"What is the midline y-value of {formula}?"
            answer = midline
        else:
            prompt = f"What is the amplitude of {formula}?"
            answer = abs(amplitude)
        return self._equivalent(
            "precalc_trig_graphs",
            "Wave Reader",
            prompt,
            str(answer),
        )

    def _trig_equations(self) -> QuestTemplate:
        function, value, answer = self.rng.choice(
            [
                ("sin", "1/2", "pi/6"),
                ("sin", "sqrt(2)/2", "pi/4"),
                ("sin", "sqrt(3)/2", "pi/3"),
                ("sin", "-1/2", "7*pi/6"),
                ("cos", "1/2", "pi/3"),
                ("cos", "-1/2", "2*pi/3"),
                ("cos", "0", "pi/2"),
                ("cos", "-sqrt(2)/2", "3*pi/4"),
            ]
        )
        return self._equivalent(
            "precalc_trig_equations",
            "Angle Hunt",
            f"On 0 <= x < 2pi, give the smallest nonnegative solution of {function}(x) = {value}.",
            answer,
        )

    def _trig_identities(self) -> QuestTemplate:
        prompt, answer = self.rng.choice(
            [
                ("Simplify sin(x)^2 + cos(x)^2.", "1"),
                ("Simplify 1 - sin(x)^2.", "cos(x)^2"),
                ("Simplify 1 - cos(x)^2.", "sin(x)^2"),
                ("Simplify (1 - cos(x)^2)/sin(x)^2.", "1"),
                ("Simplify (1 - sin(x)^2)/cos(x)^2.", "1"),
            ]
        )
        return self._equivalent(
            "precalc_trig_identities",
            "Identity Seal",
            prompt,
            answer,
        )
