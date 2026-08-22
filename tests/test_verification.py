import unittest

import sympy as sp

from sensei.verification import (
    CalculusVerifier,
    MathInputError,
    VerificationStatus,
    parse_math_expression,
)


class RestrictedParserTests(unittest.TestCase):
    def test_parses_common_terminal_notation_without_eval(self) -> None:
        x = sp.Symbol("x")
        parsed = parse_math_expression(r"2x + 3(x+1) + \sin(x) + π")
        expected = 2 * x + 3 * (x + 1) + sp.sin(x) + sp.pi
        self.assertEqual(0, sp.simplify(parsed - expected))

    def test_decimal_is_converted_to_an_exact_rational(self) -> None:
        self.assertEqual(sp.Rational(1, 2), parse_math_expression("0.5"))

    def test_rejects_code_and_object_introspection_syntax(self) -> None:
        unsafe = [
            "__import__('os')",
            "x.__class__",
            "[x for x in y]",
            "open(x)",
            "sin(x, y)",
        ]
        for expression in unsafe:
            with self.subTest(expression=expression), self.assertRaises(MathInputError):
                parse_math_expression(expression)

    def test_rejects_resource_amplifying_powers_and_invalid_numbers(self) -> None:
        for expression in ["x^101", "2^(2^20)", "1 2"]:
            with self.subTest(expression=expression), self.assertRaises(MathInputError):
                parse_math_expression(expression)


class CalculusVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = CalculusVerifier()

    def test_derivative_accepts_equivalent_implicit_multiplication(self) -> None:
        result = self.verifier.derivative("sin(x^2)", "2x*cos(x^2)")
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)

    def test_derivative_rejects_a_missing_inner_derivative(self) -> None:
        result = self.verifier.derivative("sin(x^2)", "cos(x^2)")
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, result.status)
        self.assertIn("2*x*cos", result.expected)

    def test_limit_handles_symbolic_values_and_two_sided_dne(self) -> None:
        correct = self.verifier.limit("(sqrt(1+x)-1)/x", "1/2")
        dne = self.verifier.limit("1/x", "DNE")
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, correct.status)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, dne.status)

    def test_one_sided_limit_is_directional(self) -> None:
        result = self.verifier.limit("1/x", "oo", direction="right")
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)

    def test_antiderivative_checks_by_differentiating_student_answer(self) -> None:
        correct = self.verifier.antiderivative(
            "2x*cos(x^2)", "sin(x^2) + C"
        )
        wrong = self.verifier.antiderivative(
            "2x*cos(x^2)", "x^2*sin(x^2) + C"
        )
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, correct.status)
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, wrong.status)

    def test_equivalence_uses_symbolic_not_structural_equality(self) -> None:
        result = self.verifier.equivalent("(x+1)^2", "x^2 + 2x + 1")
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)


if __name__ == "__main__":
    unittest.main()
