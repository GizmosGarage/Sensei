import unittest

from sensei.answers import (
    AnswerKeyError,
    answer_format_hint,
    answer_key_display,
    answer_key_latex,
    check_answer,
    check_parts,
    normalize_answer_key,
    parse_interval_set,
    submitted_latex,
)
from sensei.learning import Outcome
from sensei.verification import MathInputError, VerificationStatus


CORRECT = VerificationStatus.VERIFIED_CORRECT
INCORRECT = VerificationStatus.VERIFIED_INCORRECT
OPTIONS = ["Increasing", "Decreasing", "Constant", "Undefined"]


class NumericAnswerTests(unittest.TestCase):
    def test_numeric_accepts_values_within_relative_tolerance(self) -> None:
        spec = normalize_answer_key(
            "numeric", "6.02*10^23", tolerance=0.01, unit="molecules"
        )
        self.assertEqual(CORRECT, check_answer(spec, "6.0e23").status)
        self.assertEqual(CORRECT, check_answer(spec, "6.02 x 10^23 molecules").status)
        self.assertEqual(INCORRECT, check_answer(spec, "5.9*10^23").status)
        self.assertEqual("6.02*10^23 molecules", check_answer(spec, "6e23").expected)
        with self.assertRaises(MathInputError):
            check_answer(spec, "x")
        with self.assertRaises(MathInputError):
            check_answer(spec, "oo")

    def test_numeric_uses_absolute_tolerance_for_a_zero_key(self) -> None:
        spec = normalize_answer_key("numeric", "0")
        self.assertEqual(0.01, spec.tolerance)
        self.assertEqual(CORRECT, check_answer(spec, "0.005").status)
        self.assertEqual(INCORRECT, check_answer(spec, "0.02").status)
        self.assertEqual(CORRECT, check_answer(normalize_answer_key("numeric", "1,250"), "1250").status)

    def test_numeric_key_validation(self) -> None:
        with self.assertRaisesRegex(AnswerKeyError, "tolerance"):
            normalize_answer_key("numeric", "3", tolerance=0.5)
        with self.assertRaisesRegex(AnswerKeyError, "tolerance"):
            normalize_answer_key("numeric", "3", tolerance=0)
        with self.assertRaisesRegex(AnswerKeyError, "tolerance"):
            normalize_answer_key("numeric", "3", tolerance="1%")
        with self.assertRaisesRegex(AnswerKeyError, "could not be parsed"):
            normalize_answer_key("numeric", "x + 1")
        with self.assertRaisesRegex(AnswerKeyError, "empty option list"):
            normalize_answer_key("numeric", "3", options=OPTIONS)
        with self.assertRaisesRegex(AnswerKeyError, "unit"):
            normalize_answer_key("numeric", "3", unit="a" * 21)
        self.assertEqual(
            r"3\ \text{ft/s}",
            answer_key_latex(normalize_answer_key("numeric", "3", unit="ft/s")),
        )


class SolutionSetTests(unittest.TestCase):
    def test_solution_sets_ignore_order_labels_and_duplicates(self) -> None:
        spec = normalize_answer_key("solution_set", ["2", "-3"])
        self.assertEqual("2, -3", spec.key)
        for submitted in ("x = -3, x = 2", "-3 or 2", "{2, -3}", "2; -3", "2, 2, -3"):
            with self.subTest(submitted=submitted):
                self.assertEqual(CORRECT, check_answer(spec, submitted).status)
        self.assertEqual(INCORRECT, check_answer(spec, "2").status)
        self.assertEqual(INCORRECT, check_answer(spec, "2, -3, 5").status)
        self.assertIn("1 of 2", check_answer(spec, "2, 4").detail)
        self.assertEqual("2, -3", answer_key_latex(spec))

    def test_solution_sets_compare_symbolically(self) -> None:
        spec = normalize_answer_key("solution_set", "sqrt(2), -sqrt(2)")
        self.assertEqual(CORRECT, check_answer(spec, "2^0.5, -2^0.5").status)
        self.assertEqual(r"\sqrt{2}, - \sqrt{2}", answer_key_latex(spec))

    def test_empty_solution_set(self) -> None:
        spec = normalize_answer_key("solution_set", [])
        self.assertEqual("none", spec.key)
        for submitted in ("none", "∅", "no solution", "DNE", "{}"):
            with self.subTest(submitted=submitted):
                self.assertEqual(CORRECT, check_answer(spec, submitted).status)
        self.assertEqual(INCORRECT, check_answer(spec, "0").status)
        self.assertEqual(r"\varnothing", answer_key_latex(spec))

    def test_solution_set_key_validation(self) -> None:
        with self.assertRaisesRegex(AnswerKeyError, "at most 6"):
            normalize_answer_key("solution_set", [str(index) for index in range(7)])
        with self.assertRaisesRegex(AnswerKeyError, "could not be parsed"):
            normalize_answer_key("solution_set", ["x^^2"])
        with self.assertRaisesRegex(AnswerKeyError, "list of expressions"):
            normalize_answer_key("solution_set", 4)


class IntervalTests(unittest.TestCase):
    def test_interval_unions_compare_regardless_of_order_or_symbols(self) -> None:
        spec = normalize_answer_key("interval", "(-oo, 1) U [3, oo)")
        for submitted in (
            "(-oo,1)∪[3,oo)",
            "(-∞, 1) u [3, ∞)",
            "[3, oo) U (-oo, 1)",
            "(-oo, 1) union [3, oo)",
        ):
            with self.subTest(submitted=submitted):
                self.assertEqual(CORRECT, check_answer(spec, submitted).status)
        self.assertEqual(INCORRECT, check_answer(spec, "(-oo, 1] U [3, oo)").status)
        self.assertEqual(INCORRECT, check_answer(spec, "(-oo, 1)").status)
        self.assertEqual(INCORRECT, check_answer(spec, "all reals").status)
        latex = answer_key_latex(spec)
        self.assertIn(r"\infty", latex)
        self.assertIn(r"\cup", latex)

    def test_all_reals_finite_sets_and_empty_sets(self) -> None:
        reals = normalize_answer_key("interval", "(-oo, oo)")
        for submitted in ("all real numbers", "R", "ℝ", "(-oo, oo)"):
            with self.subTest(submitted=submitted):
                self.assertEqual(CORRECT, check_answer(reals, submitted).status)
        mixed = normalize_answer_key("interval", "(0, 2] U {5}")
        self.assertEqual(CORRECT, check_answer(mixed, "{5} U (0, 2]").status)
        self.assertEqual(INCORRECT, check_answer(mixed, "(0, 2]").status)
        empty = normalize_answer_key("interval", "none")
        self.assertEqual(CORRECT, check_answer(empty, "∅").status)
        self.assertEqual(INCORRECT, check_answer(empty, "(0, 1)").status)

    def test_interval_parsing_rejects_bad_notation(self) -> None:
        with self.assertRaisesRegex(MathInputError, "smallest to largest"):
            parse_interval_set("(3, 1)")
        with self.assertRaises(MathInputError):
            parse_interval_set("(a, b)")
        with self.assertRaisesRegex(MathInputError, "Unsupported interval"):
            parse_interval_set("[1 2]")
        with self.assertRaisesRegex(AnswerKeyError, "could not be parsed"):
            normalize_answer_key("interval", "(3, 1)")


class PointTests(unittest.TestCase):
    def test_point_sets_ignore_order_and_accept_bare_pairs(self) -> None:
        spec = normalize_answer_key("point", [["2", "-5"], ["3", "1"]])
        self.assertEqual("(2, -5), (3, 1)", spec.key)
        self.assertEqual(CORRECT, check_answer(spec, "(3, 1), (2, -5)").status)
        self.assertEqual(CORRECT, check_answer(spec, "(2,-5) and (3,1)").status)
        self.assertEqual(INCORRECT, check_answer(spec, "(2, -5)").status)
        single = normalize_answer_key("point", "(1/2, sqrt(2))")
        self.assertEqual(CORRECT, check_answer(single, "0.5, 2^0.5").status)
        self.assertEqual(r"\left(\frac{1}{2}, \sqrt{2}\right)", answer_key_latex(single))
        with self.assertRaises(MathInputError):
            check_answer(single, "(1, 2, 3)")
        with self.assertRaisesRegex(AnswerKeyError, "pair"):
            normalize_answer_key("point", [["1", "2", "3"]])


class ChoiceAndExpressionTests(unittest.TestCase):
    def test_multiple_choice_accepts_letter_or_exact_option(self) -> None:
        spec = normalize_answer_key("multiple_choice", "b", options=OPTIONS)
        self.assertEqual("B", spec.key)
        self.assertEqual(CORRECT, check_answer(spec, "b.").status)
        self.assertEqual(CORRECT, check_answer(spec, "decreasing").status)
        self.assertEqual(INCORRECT, check_answer(spec, "E").status)
        self.assertEqual("B. Decreasing", answer_key_display(spec))
        self.assertIsNone(answer_key_latex(spec))
        with self.assertRaisesRegex(AnswerKeyError, "four options"):
            normalize_answer_key("multiple_choice", "A", options=OPTIONS[:3])

    def test_expression_keys_including_dne(self) -> None:
        spec = normalize_answer_key("expression", "does not exist")
        self.assertEqual("DNE", spec.key)
        self.assertEqual(CORRECT, check_answer(spec, "dne").status)
        self.assertEqual(INCORRECT, check_answer(spec, "0").status)
        self.assertEqual(r"\(\mathrm{DNE}\)", answer_key_display(spec))
        derivative = normalize_answer_key("expression", "2*x")
        self.assertEqual(CORRECT, check_answer(derivative, "2x").status)
        self.assertEqual("2 x", submitted_latex(derivative, "2x"))
        with self.assertRaisesRegex(AnswerKeyError, "could not be parsed"):
            normalize_answer_key("expression", "2x+")
        with self.assertRaisesRegex(AnswerKeyError, "tolerance applies only"):
            normalize_answer_key("expression", "x^2", tolerance=0.1)
        with self.assertRaisesRegex(AnswerKeyError, "answer_type must be"):
            normalize_answer_key("essay", "x")
        with self.assertRaises(ValueError):
            check_answer(derivative, "   ")

    def test_format_hints_name_the_expected_entry_style(self) -> None:
        self.assertIn("ft/s", answer_format_hint("numeric", "ft/s"))
        self.assertIn("(-oo, 1) U [3, oo)", answer_format_hint("interval"))
        self.assertIn("(x, y)", answer_format_hint("point"))
        self.assertIn("DNE", answer_format_hint("expression"))


class MultiPartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parts = (
            ("a", normalize_answer_key("expression", "2*x")),
            ("b", normalize_answer_key("solution_set", ["0"])),
            ("c", normalize_answer_key("interval", "(0, oo)")),
        )

    def test_all_parts_correct(self) -> None:
        result = check_parts(self.parts, {"a": "2x", "b": "x = 0", "c": "(0, oo)"})
        self.assertIs(Outcome.CORRECT, result.outcome)
        self.assertEqual(3, result.correct_count)
        self.assertEqual(CORRECT, result.summary().status)
        self.assertEqual("(a) 2*x; (b) x = 0; (c) (0, oo)", result.summary().submitted)

    def test_some_parts_correct_is_partial(self) -> None:
        result = check_parts(self.parts, {"a": "2x", "b": "1", "c": "(0, oo)"})
        self.assertIs(Outcome.PARTIAL, result.outcome)
        self.assertEqual(2, result.correct_count)
        summary = result.summary()
        self.assertEqual(INCORRECT, summary.status)
        self.assertIn("2 of 3", summary.detail)
        self.assertEqual("(a) 2*x; (b) 0; (c) (0, oo)", summary.expected)

    def test_no_parts_correct_and_validation(self) -> None:
        result = check_parts(self.parts, {"a": "x", "b": "1", "c": "[0, oo)"})
        self.assertIs(Outcome.INCORRECT, result.outcome)
        with self.assertRaisesRegex(ValueError, r"part \(c\)"):
            check_parts(self.parts, {"a": "2x", "b": "0"})
        with self.assertRaisesRegex(ValueError, "Unknown part"):
            check_parts(self.parts, {"a": "2x", "b": "0", "c": "(0, oo)", "d": "x"})
        with self.assertRaises(MathInputError):
            check_parts(self.parts, {"a": "2x", "b": "0", "c": "(3, 1)"})


if __name__ == "__main__":
    unittest.main()
