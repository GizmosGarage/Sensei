import json
import unittest

from sensei.practice import (
    MAX_SOLUTION_CHARACTERS,
    AdaptiveQuestFactory,
    PracticeGenerationError,
    adaptive_quest_fingerprint,
    parse_adaptive_quest,
)
from sensei.providers import CompletionResult, ProviderError
from sensei.verification import VerificationStatus


SKILL = {
    "id": "focus-stoichiometry-test",
    "course": "Chemistry",
    "name": "Stoichiometry",
    "description": "Practice mole ratios.",
}


class StubProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        return CompletionResult(self.responses.pop(0), "stop")


class AdaptivePracticeTests(unittest.TestCase):
    def test_factory_generates_and_independently_approves_a_safe_quest(self) -> None:
        draft = json.dumps(
            {
                "title": "Mole Ratio Trial",
                "prompt": (
                    r"For \(\ce{2H2 + O2 -> 2H2O}\), how many moles of "
                    r"\(\ce{H2O}\) form from \(3\) moles of \(\ce{H2}\)? "
                    "Enter only the number."
                ),
                "answer_type": "expression",
                "answer": "3",
                "options": [],
                "help_steps": [
                    r"Compare the coefficients of \(\ce{H2}\) and \(\ce{H2O}\).",
                    "Use that coefficient ratio to convert the given moles.",
                ],
                "solution": (
                    r"The coefficient ratio is \(2:2=1:1\), so \(3\) moles form."
                ),
                "graph": None,
            }
        )
        provider = StubProvider(
            [draft, json.dumps({"approved": True, "reason": "Answer recomputed."})]
        )
        quest = AdaptiveQuestFactory(provider).generate(SKILL)
        self.assertEqual("Stoichiometry", quest.topic)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, quest.check("3").status)
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, quest.check("6").status)
        public = quest.public_dict()
        self.assertNotIn("answer", public)
        self.assertNotIn("solution", public)
        self.assertNotIn("help_steps", public)
        self.assertEqual(2, len(quest.help_steps))
        self.assertEqual(2, len(provider.requests))
        self.assertIn("Subject: Chemistry", provider.requests[0][-1]["content"])
        self.assertIn("Topic or skill: Stoichiometry", provider.requests[0][-1]["content"])
        self.assertIn(
            "Practice instructions: Practice mole ratios.",
            provider.requests[0][-1]["content"],
        )
        self.assertIn(
            "Course fidelity is the top priority",
            provider.requests[0][0]["content"],
        )
        self.assertIn("KaTeX-compatible LaTeX", provider.requests[0][0]["content"])
        self.assertIn(r"\ce{2H2 + O2 -> 2H2O}", provider.requests[0][0]["content"])
        self.assertIn(
            "use inline \\(...\\) notation only",
            provider.requests[0][0]["content"],
        )
        self.assertIn(
            "every LaTeX command and delimiter must have one backslash",
            provider.requests[0][0]["content"],
        )
        self.assertIn("Requested subject: Chemistry", provider.requests[1][-1]["content"])
        self.assertIn(
            "Requested topic or skill: Stoichiometry",
            provider.requests[1][-1]["content"],
        )
        self.assertIn(
            "Requested practice instructions: Practice mole ratios.",
            provider.requests[1][-1]["content"],
        )
        self.assertIn(
            "compare the draft with the anchor exemplar",
            provider.requests[1][0]["content"],
        )
        self.assertIn(
            "help_steps are ordered",
            provider.requests[1][0]["content"],
        )
        self.assertIn("reject raw ASCII formulas", provider.requests[1][0]["content"])

    def test_fixable_draft_is_revised_with_feedback_instead_of_discarded(self) -> None:
        incorrect_key = json.dumps(
            {
                "title": "Direct Conversion",
                "prompt": "Convert 100 centimeters to meters. Enter only the value.",
                "answer_type": "expression",
                "answer": "100",
                "options": [],
                "hint": "There are 100 centimeters in one meter.",
                "solution": "The keyed answer is 100.",
                "graph": None,
            }
        )
        revised = json.dumps(
            {
                "title": "Direct Conversion",
                "prompt": "Convert 100 centimeters to meters. Enter only the value.",
                "answer_type": "expression",
                "answer": "1",
                "options": [],
                "hint": "There are 100 centimeters in one meter.",
                "solution": "Divide 100 by 100 to get 1.",
                "graph": None,
            }
        )
        provider = StubProvider(
            [
                incorrect_key,
                json.dumps(
                    {
                        "approved": False,
                        "reason": "The keyed answer is wrong; it should be 1.",
                    }
                ),
                revised,
                json.dumps({"approved": True, "reason": "Checked."}),
            ]
        )
        quest = AdaptiveQuestFactory(provider).generate(
            {**SKILL, "name": "Unit conversions"}
        )

        self.assertEqual("1", quest.answer)
        revision_request = provider.requests[2][-1]["content"]
        self.assertIn("prior draft was rejected", revision_request)
        self.assertIn("keyed answer is wrong", revision_request)
        self.assertIn("Convert 100 centimeters to meters", revision_request)
        self.assertIn("Return one clean, self-contained replacement", revision_request)

    def test_scope_or_science_failure_starts_over_without_anchoring(self) -> None:
        flawed = json.dumps(
            {
                "title": "Charged Particle Paths",
                "prompt": "Which ion bends more? Choose the best answer.",
                "answer_type": "multiple_choice",
                "answer": "A",
                "options": ["Lighter ion", "Heavier ion", "Both", "Neither"],
                "hint": "Compare the masses.",
                "solution": "The lighter ion bends more.",
                "graph": None,
            }
        )
        replacement = json.dumps(
            {
                "title": "Mass-to-Charge Paths",
                "prompt": "Which ion has the smallest mass-to-charge ratio?",
                "answer_type": "multiple_choice",
                "answer": "B",
                "options": ["40/1", "20/2", "30/1", "60/2"],
                "hint": "Compare each mass divided by charge magnitude.",
                "solution": "The second ratio is the smallest.",
                "graph": None,
            }
        )
        provider = StubProvider(
            [
                flawed,
                json.dumps(
                    {
                        "approved": False,
                        "reason": (
                            "The problem does not address the requested effect of "
                            "different ion charges on trajectories."
                        ),
                    }
                ),
                replacement,
                json.dumps({"approved": True, "reason": "Checked."}),
            ]
        )

        quest = AdaptiveQuestFactory(provider).generate(
            {
                **SKILL,
                "name": "Mass spectrometry",
                "description": "Compare how ion mass and charge affect trajectories.",
            }
        )

        self.assertEqual("Mass-to-Charge Paths", quest.title)
        replacement_request = provider.requests[2][-1]["content"]
        self.assertIn("Start over with a clean problem", replacement_request)
        self.assertNotIn("Prior draft:", replacement_request)

    def test_repeated_graphical_limit_is_rejected_and_replaced(self) -> None:
        skill = {
            **SKILL,
            "id": "focus-graphical-limits-test",
            "course": "Mathematics",
            "name": "Graphical limits",
            "description": "Read limits from graph behavior.",
        }
        repeated_prompt = (
            "A graph approaches y = 3 from both sides as x approaches 2. "
            "What is the limit? Enter only the number."
        )
        repeated = json.dumps(
            {
                "title": "Approach at Two",
                "prompt": repeated_prompt,
                "answer_type": "expression",
                "answer": "3",
                "options": [],
                "hint": "Follow the curve from both sides.",
                "solution": "Both sides approach 3, so the limit is 3.",
                "graph": {
                    "x_min": -2,
                    "x_max": 6,
                    "y_min": -2,
                    "y_max": 6,
                    "curves": [[[-2, 1], [2, 3]], [[2, 3], [6, 1]]],
                    "points": [{"x": 2, "y": 3, "type": "open"}],
                    "description": "Both branches approach the open point at (2, 3).",
                },
            }
        )
        fresh = json.dumps(
            {
                "title": "One-Sided Graph Gate",
                "prompt": (
                    "A graph approaches y = -1 as x approaches 4 from the left, "
                    "while the right side approaches y = 5. What is the two-sided "
                    "limit? Choose the best answer."
                ),
                "answer_type": "multiple_choice",
                "answer": "D",
                "options": ["-1", "4", "5", "The limit does not exist"],
                "hint": "A two-sided limit needs matching one-sided behavior.",
                "solution": "The sides approach different values, so the limit DNE.",
                "graph": {
                    "x_min": 0,
                    "x_max": 8,
                    "y_min": -3,
                    "y_max": 6,
                    "curves": [[[0, -3], [4, -1]], [[4, 5], [8, 3]]],
                    "points": [
                        {"x": 4, "y": -1, "type": "open"},
                        {"x": 4, "y": 5, "type": "open"},
                    ],
                    "description": (
                        "The left branch approaches (4, -1), while the right branch "
                        "approaches (4, 5); both endpoints are open."
                    ),
                },
            }
        )
        provider = StubProvider(
            [
                repeated,
                fresh,
                json.dumps({"approved": True, "reason": "Recomputed."}),
            ]
        )
        quest = AdaptiveQuestFactory(provider).generate(
            skill,
            avoid_prompts=[repeated_prompt],
            avoid_fingerprints=[
                adaptive_quest_fingerprint(
                    parse_adaptive_quest(repeated, skill=skill)
                )
            ],
        )
        self.assertNotEqual(repeated_prompt, quest.prompt)
        self.assertNotIn("from the left", quest.prompt)
        self.assertNotIn("from the right", quest.prompt)
        self.assertIsNotNone(quest.graph)
        self.assertEqual("open", quest.public_dict()["graph"]["points"][0]["type"])
        self.assertEqual(3, len(provider.requests))
        first_request = provider.requests[0][-1]["content"]
        second_request = provider.requests[1][-1]["content"]
        self.assertIn(repeated_prompt, first_request)
        self.assertIn("prior draft was rejected", second_request)
        self.assertNotEqual(
            first_request.split("Internal variation key", 1)[1].splitlines()[0],
            second_request.split("Internal variation key", 1)[1].splitlines()[0],
        )

    def test_multiple_choice_accepts_a_letter_or_the_exact_option(self) -> None:
        quest = parse_adaptive_quest(
            json.dumps(
                {
                    "title": "Limiting Reagent Gate",
                    "prompt": "Which reactant is consumed first in a reaction?",
                    "answer_type": "multiple_choice",
                    "answer": "B",
                    "options": [
                        "A. Catalyst",
                        "B) Limiting reagent",
                        "C. Solvent",
                        "D) Excess reagent",
                    ],
                    "hint": "Its name describes the cap it places on product.",
                    "solution": "The limiting reagent is exhausted first.",
                    "graph": None,
                }
            ),
            skill=SKILL,
        )
        self.assertEqual(
            ("Catalyst", "Limiting reagent", "Solvent", "Excess reagent"),
            quest.options,
        )
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, quest.check("B").status)
        self.assertEqual(
            VerificationStatus.VERIFIED_CORRECT,
            quest.check("Limiting reagent").status,
        )
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, quest.check("D").status)

    def test_multiple_choice_rejects_an_unbounded_option(self) -> None:
        document = {
            "title": "Oversized option",
            "prompt": "Choose the best answer.",
            "answer_type": "multiple_choice",
            "answer": "A",
            "options": ["x" * 501, "Second", "Third", "Fourth"],
            "hint": "Compare the choices.",
            "solution": "The first choice is keyed.",
            "graph": None,
        }
        with self.assertRaisesRegex(PracticeGenerationError, "500 characters"):
            parse_adaptive_quest(json.dumps(document), skill=SKILL)

    def test_double_escaped_display_notation_is_repaired(self) -> None:
        document = {
            "title": "Constant limit",
            "prompt": (
                r"For \\(f(x)=6\\), determine "
                r"\\(\\lim_{x \\to 13} f(x)\\)."
            ),
            "answer_type": "multiple_choice",
            "answer": "B",
            "options": [r"\\(-6\\)", r"\\(6\\)", r"\\(0\\)", "DNE"],
            "help_steps": [
                r"Use the constant-function rule for \\(f(x)=6\\).",
                r"The output stays \\(6\\) as \\(x\\) approaches any value.",
            ],
            "solution": r"A constant function remains \\(6\\), so the limit is \\(6\\).",
            "graph": None,
        }

        quest = parse_adaptive_quest(json.dumps(document), skill=SKILL)

        self.assertEqual(
            r"For \(f(x)=6\), determine \(\lim_{x \to 13} f(x)\).",
            quest.prompt,
        )
        self.assertEqual((r"\(-6\)", r"\(6\)", r"\(0\)", "DNE"), quest.options)
        self.assertEqual(
            r"Use the constant-function rule for \(f(x)=6\).",
            quest.help_steps[0],
        )
        self.assertEqual(
            r"A constant function remains \(6\), so the limit is \(6\).",
            quest.solution,
        )

    def test_unmatched_display_notation_is_rejected(self) -> None:
        document = {
            "title": "Broken notation",
            "prompt": r"Evaluate \(x^2.",
            "answer_type": "expression",
            "answer": "4",
            "options": [],
            "hint": "Substitute the value.",
            "solution": r"The value is \(4\).",
            "graph": None,
        }

        with self.assertRaisesRegex(PracticeGenerationError, "unclosed notation"):
            parse_adaptive_quest(json.dumps(document), skill=SKILL)

    def test_bare_numerical_array_is_repaired_for_display(self) -> None:
        document = {
            "title": "Estimate a limit from a table",
            "prompt": (
                "Use the numerical table to estimate the two-sided limit. "
                r"\begin{array}{c|ccccc} x&1.90&1.99&2.01&2.10\hline "
                r"f(x)&4.90&4.99&5.01&5.10 \end{array} Estimate "
                r"\(\lim_{x \to 2} f(x)\)."
            ),
            "answer_type": "expression",
            "answer": "5",
            "options": [],
            "help_steps": [
                "Compare the function values on both sides of the target input.",
                r"Both sides approach \(5\).",
            ],
            "solution": r"The nearby values approach \(5\) from both sides.",
            "graph": None,
        }

        quest = parse_adaptive_quest(json.dumps(document), skill=SKILL)

        self.assertIn(
            r"\[\begin{array}{c|ccccc} x&1.90&1.99&2.01&2.10\\ "
            r"\hline f(x)&4.90&4.99&5.01&5.10 \end{array}\]",
            quest.prompt,
        )

    def test_mismatched_math_environments_are_rejected(self) -> None:
        document = {
            "title": "Broken table",
            "prompt": r"Read \[\begin{array}{cc}x&1\end{matrix}\].",
            "answer_type": "expression",
            "answer": "1",
            "options": [],
            "hint": "Read the value.",
            "solution": r"The value is \(1\).",
            "graph": None,
        }

        with self.assertRaisesRegex(PracticeGenerationError, "mismatched"):
            parse_adaptive_quest(json.dumps(document), skill=SKILL)

    def test_dne_expression_key_is_checked_by_normalized_exact_match(self) -> None:
        document = {
            "title": "Nonexistent limit",
            "prompt": "Find a two-sided limit. Enter DNE if it does not exist.",
            "answer_type": "expression",
            "answer": "DNE",
            "options": [],
            "hint": "Compare both sides.",
            "solution": "The sides differ, so the limit does not exist.",
            "graph": None,
        }

        quest = parse_adaptive_quest(json.dumps(document), skill=SKILL)

        self.assertEqual(
            VerificationStatus.VERIFIED_CORRECT,
            quest.check("does not exist").status,
        )
        self.assertEqual(
            VerificationStatus.VERIFIED_INCORRECT,
            quest.check("0").status,
        )

    def test_unparseable_expression_key_becomes_a_retryable_generation_error(self) -> None:
        document = {
            "title": "Invalid expression key",
            "prompt": "Find the requested value.",
            "answer_type": "expression",
            "answer": "not-a-number",
            "options": [],
            "hint": "Recompute it.",
            "solution": "The draft used an invalid answer key.",
            "graph": None,
        }

        with self.assertRaisesRegex(
            PracticeGenerationError,
            "expression answer could not be parsed",
        ):
            parse_adaptive_quest(json.dumps(document), skill=SKILL)

    def test_walkthrough_allows_bounded_provider_verbosity(self) -> None:
        document = {
            "title": "Verbose but bounded walkthrough",
            "prompt": "Evaluate 1 + 1. Enter only the number.",
            "answer_type": "expression",
            "answer": "2",
            "options": [],
            "hint": "Add the two values.",
            "solution": "Reason carefully. " * 75,
            "graph": None,
        }
        quest = parse_adaptive_quest(json.dumps(document), skill=SKILL)
        self.assertGreater(len(quest.solution), 1_200)

        document["solution"] = "x" * (MAX_SOLUTION_CHARACTERS + 1)
        with self.assertRaisesRegex(
            PracticeGenerationError,
            f"solution exceeds {MAX_SOLUTION_CHARACTERS} characters",
        ):
            parse_adaptive_quest(json.dumps(document), skill=SKILL)

    def test_prompt_discards_stray_show_your_work_instruction(self) -> None:
        document = {
            "title": "Answer-only encounter",
            "prompt": (
                "Evaluate (1 - cos(3x))/x^2 as x approaches 0. "
                "You must show your work using two transformations. "
                "Enter only the final number."
            ),
            "answer_type": "expression",
            "answer": "9/2",
            "options": [],
            "hint": "Use a trigonometric identity.",
            "solution": "Rewrite 1-cos(3x), use the sine limit, and obtain 9/2.",
            "graph": None,
        }

        quest = parse_adaptive_quest(json.dumps(document), skill=SKILL)

        self.assertNotIn("show your work", quest.prompt.casefold())
        self.assertEqual(
            "Evaluate (1 - cos(3x))/x^2 as x approaches 0. "
            "Enter only the final number.",
            quest.prompt,
        )

    def test_graphical_topic_rejects_a_text_only_problem(self) -> None:
        document = {
            "title": "Text-only graph",
            "prompt": "A curve approaches 2. What is its limit?",
            "answer_type": "expression",
            "answer": "2",
            "options": [],
            "hint": "Read the curve.",
            "solution": "The curve approaches 2.",
            "graph": None,
        }
        with self.assertRaisesRegex(PracticeGenerationError, "structured graph data"):
            parse_adaptive_quest(
                json.dumps(document),
                skill={**SKILL, "name": "Graphical limits"},
            )

    def test_graphical_limit_prompt_is_replaced_with_concise_graph_copy(self) -> None:
        document = {
            "title": "Formula disguised as a graph",
            "prompt": "The graph shows f(x) = 2*x + 1. Find the limit at x = 2.",
            "answer_type": "expression",
            "answer": "5",
            "options": [],
            "hint": "Read the graph near x = 2.",
            "solution": "The curve approaches 5.",
            "graph": {
                "x_min": -2,
                "x_max": 4,
                "y_min": -3,
                "y_max": 9,
                "curves": [[[-2, -3], [2, 5], [4, 9]]],
                "points": [],
                "description": "A straight line passing through (2, 5).",
            },
        }
        quest = parse_adaptive_quest(
            json.dumps(document),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertEqual(
            r"Use the displayed graph to determine \(\displaystyle \lim_{x \to 2} "
            r"f(x)\). Enter only the value of the limit.",
            quest.prompt,
        )

        document["prompt"] = (
            "The graph is a line through (-2, 0) and (2, 4). Find the limit at x = 0."
        )
        quest = parse_adaptive_quest(
            json.dumps(document),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertNotIn("(-2, 0)", quest.prompt)
        self.assertNotIn("(2, 4)", quest.prompt)

        document["prompt"] = (
            "The curve passes through (0, 1). Find the limit as x approaches 2."
        )
        quest = parse_adaptive_quest(
            json.dumps(document),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertNotIn("(0, 1)", quest.prompt)

        document["prompt"] = (
            r"Use the displayed graph to evaluate "
            r"\(\lim_{x \to 2^{-}} f(x)\)."
        )
        quest = parse_adaptive_quest(
            json.dumps(document),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertEqual(
            r"Use the displayed graph to determine "
            r"\(\displaystyle \lim_{x \to 2^{-}} f(x)\). "
            r"Enter only the value of the limit.",
            quest.prompt,
        )

    def test_graph_axes_expand_to_include_model_coordinates(self) -> None:
        document = {
            "title": "Expanded graph bounds",
            "prompt": "Use the displayed graph to find the limit as x approaches 1.",
            "answer_type": "expression",
            "answer": "3",
            "options": [],
            "hint": "Follow the curve toward x = 1.",
            "solution": "Both sides approach 3.",
            "graph": {
                "x_min": -2,
                "x_max": 2,
                "y_min": -2,
                "y_max": 2,
                "curves": [[[-3, -1], [1, 3], [3, 5]]],
                "points": [{"x": 1, "y": 3, "type": "open"}],
                "description": "A rising line approaches an open point at (1, 3).",
            },
        }
        quest = parse_adaptive_quest(
            json.dumps(document),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertEqual(-3, quest.graph.x_min)
        self.assertEqual(5, quest.graph.y_max)

        alternate = json.loads(json.dumps(document))
        alternate["graph"]["curves"] = [[[-3, 1], [1, 3], [3, 4]]]
        alternate_quest = parse_adaptive_quest(
            json.dumps(alternate),
            skill={**SKILL, "name": "Graphical limits"},
        )
        self.assertEqual(quest.prompt, alternate_quest.prompt)
        self.assertNotEqual(
            adaptive_quest_fingerprint(quest),
            adaptive_quest_fingerprint(alternate_quest),
        )

    def test_factory_retries_a_transient_provider_failure(self) -> None:
        draft = json.dumps(
            {
                "title": "Mole Ratio Retry",
                "prompt": "Evaluate 4/2. Enter only the number.",
                "answer_type": "expression",
                "answer": "2",
                "options": [],
                "hint": "Divide.",
                "solution": "Four divided by two is two.",
                "graph": None,
            }
        )

        class FlakyProvider(StubProvider):
            def __init__(self) -> None:
                super().__init__(
                    [draft, json.dumps({"approved": True, "reason": "Checked."})]
                )
                self.failed = False

            def complete(self, messages, on_token=None):
                if not self.failed:
                    self.failed = True
                    self.requests.append(list(messages))
                    raise ProviderError("temporary hosted model disconnect")
                return super().complete(messages, on_token)

        provider = FlakyProvider()
        quest = AdaptiveQuestFactory(provider).generate(SKILL)
        self.assertEqual("2", quest.answer)
        self.assertEqual(3, len(provider.requests))


if __name__ == "__main__":
    unittest.main()


from sensei.learning import Outcome  # noqa: E402
from sensei.practice import (  # noqa: E402
    _private_quest_document,
    exemplar_block,
    learner_signal_block,
)


CALCULUS_SKILL = {
    "id": "focus-related-rates-test",
    "course": "Calculus I",
    "name": "Related rates",
    "description": "Match Dr. Lee's homework style.",
}
APPROVED = json.dumps({"approved": True, "reason": "Recomputed every part."})
MATERIALS = (
    {
        "id": "material-1",
        "kind": "example_problem",
        "body": (
            "A 13 ft ladder leans against a wall and its base slides out at 2 ft/s.\n"
            "(a) How fast is the top sliding when the base is 5 ft out?\n"
            "(b) How fast is the angle with the ground changing?"
        ),
        "solution": "dy/dt = -5/6 ft/s; dtheta/dt = -1/6 rad/s",
        "source_label": "HW 4 #7",
    },
    {
        "id": "material-2",
        "kind": "example_problem",
        "body": "Sand falls into a conical pile whose height equals its radius.",
        "solution": None,
        "source_label": "",
    },
    {
        "id": "material-3",
        "kind": "notes",
        "body": "Dr. Lee wants every rate written with units.",
        "solution": None,
        "source_label": "Lecture 12",
    },
)


def multi_part_draft() -> dict:
    return {
        "title": "Sliding ladder",
        "prompt": (
            r"A 10 ft ladder leans against a wall. Its base slides away from the "
            r"wall at \(2\) ft/s."
        ),
        "answer_type": "multi_part",
        "answer": "",
        "options": [],
        "parts": [
            {
                "label": "(a)",
                "prompt": (
                    r"Find \(\frac{dy}{dt}\) when \(x = 6\). Enter only the value "
                    "in ft/s."
                ),
                "answer_type": "expression",
                "answer": "-3/2",
            },
            {
                "label": "b",
                "prompt": (
                    "For which base distances is the top moving faster than 1 ft/s "
                    "downward? Use interval notation."
                ),
                "answer_type": "interval",
                "answer": "(4, 10)",
            },
            {
                "label": "c",
                "prompt": "Which quantity stays constant? Choose the best answer.",
                "answer_type": "multiple_choice",
                "answer": "C",
                "options": ["x", "y", "The ladder length", r"\(\frac{dy}{dt}\)"],
            },
        ],
        "help_steps": [
            "Relate the base distance and height with the Pythagorean theorem.",
            r"Differentiate both sides with respect to \(t\).",
            "Substitute the known values and solve for the unknown rate.",
        ],
        "solution": (
            r"From \(x^2 + y^2 = 100\), \(2x\,x' + 2y\,y' = 0\), so at \(x = 6\), "
            r"\(y = 8\) and \(y' = -\frac{3}{2}\) ft/s."
        ),
        "graph": None,
    }


class CourseFidelityTests(unittest.TestCase):
    def test_prompt_carries_exemplars_profile_and_learner_signal(self) -> None:
        provider = StubProvider([json.dumps(multi_part_draft()), APPROVED])
        quest = AdaptiveQuestFactory(provider).generate(
            CALCULUS_SKILL,
            materials=MATERIALS,
            subject_profile="Exams: five free-response problems, no calculator.",
            learner_signal={
                "mastery_score": 42.0,
                "mastery_label": "developing",
                "attempts_count": 7,
                "success_streak": 2,
                "recent_outcomes": [
                    "incorrect",
                    "correct",
                    "incorrect",
                    "correct",
                    "correct",
                ],
                "misconceptions": ["Forgets the chain rule on the inner function."],
                "difficulty_tier": "challenging",
            },
            anchor_index=1,
        )

        user = provider.requests[0][-1]["content"]
        self.assertIn(
            "Course profile: Exams: five free-response problems, no calculator.",
            user,
        )
        self.assertIn("Anchor exemplar for this problem: [1]", user)
        self.assertLess(user.index("Sand falls"), user.index("A 13 ft ladder"))
        self.assertIn("[2] (HW 4 #7)", user)
        self.assertIn("Worked solution: dy/dt = -5/6 ft/s", user)
        self.assertIn("Worked solution: not provided", user)
        self.assertIn("Class notes:\nDr. Lee wants every rate written with units.", user)
        self.assertIn("mastery 42/100 (developing); 7 attempts", user)
        self.assertIn("incorrect, correct, incorrect, correct, correct", user)
        self.assertIn("Target difficulty tier: challenging", user)
        self.assertIn("- Forgets the chain rule on the inner function.", user)
        system = provider.requests[0][0]["content"]
        self.assertIn("Course fidelity is the top priority", system)
        self.assertIn("multi_part", system)
        self.assertIn("interval notation", system)
        review_user = provider.requests[1][-1]["content"]
        self.assertIn("Anchor exemplar for this problem: [1]", review_user)
        self.assertIn("Target difficulty tier: challenging", review_user)
        self.assertIn('"parts"', review_user)
        self.assertIn(
            "compare the draft with the anchor exemplar",
            provider.requests[1][0]["content"],
        )
        self.assertEqual("material-2", quest.anchor_material_id)
        self.assertEqual("challenging", quest.difficulty_tier)
        self.assertEqual(3, quest.material_count)
        self.assertEqual("challenging", quest.public_dict()["difficulty_tier"])

    def test_brief_without_material_or_history_uses_standard_tier(self) -> None:
        provider = StubProvider([json.dumps(multi_part_draft()), APPROVED])
        quest = AdaptiveQuestFactory(provider).generate(CALCULUS_SKILL)
        user = provider.requests[0][-1]["content"]
        self.assertIn("Course profile: None provided.", user)
        self.assertIn("Class exemplars: none provided.", user)
        self.assertIn("Learner signal: no recorded attempts on this topic yet.", user)
        self.assertIn("Target difficulty tier: standard", user)
        self.assertIn("Known weak spots to exercise: none recorded.", user)
        self.assertEqual("standard", quest.difficulty_tier)
        self.assertIsNone(quest.anchor_material_id)

    def test_exemplar_block_bounds_size_and_rotates_anchor(self) -> None:
        many = [
            {
                "id": f"material-{index}",
                "kind": "example_problem",
                "body": "x" * 2_000,
                "solution": None,
                "source_label": "",
            }
            for index in range(10)
        ]
        text, anchor = exemplar_block(many, anchor_index=13)
        self.assertEqual("material-3", anchor)
        self.assertEqual(4, text.count("Worked solution: not provided"))
        self.assertTrue(text.startswith("Class exemplars"))
        empty, none_anchor = exemplar_block([])
        self.assertIsNone(none_anchor)
        self.assertIn("none provided", empty)
        signal = learner_signal_block(None)
        self.assertIn("no recorded attempts", signal)
        self.assertIn("Target difficulty tier: standard", signal)


class MultiPartQuestTests(unittest.TestCase):
    def test_multi_part_quest_checks_each_part_with_partial_credit(self) -> None:
        quest = parse_adaptive_quest(json.dumps(multi_part_draft()), skill=CALCULUS_SKILL)
        self.assertTrue(quest.is_multi_part)
        self.assertEqual(("a", "b", "c"), tuple(part.label for part in quest.parts))
        public = quest.public_dict()
        self.assertEqual(3, len(public["parts"]))
        self.assertNotIn("answer", public["parts"][0])
        self.assertIn("interval notation", public["parts"][1]["answer_format_hint"])
        self.assertEqual(
            ["x", "y", "The ladder length", r"\(\frac{dy}{dt}\)"],
            public["parts"][2]["options"],
        )
        self.assertIsNone(public["answer_format_hint"])
        self.assertIn("(a) Find", quest.full_text)
        self.assertIn("(c) Which quantity", quest.full_text)

        complete = quest.evaluate({"a": "-1.5", "b": "(4, 10)", "c": "c"})
        self.assertIs(Outcome.CORRECT, complete.outcome)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, complete.result.status)
        self.assertEqual(3, len(complete.parts))

        partial = quest.evaluate({"a": "-1.5", "b": "[4, 10]", "c": "A"})
        self.assertIs(Outcome.PARTIAL, partial.outcome)
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, partial.result.status)
        self.assertEqual(
            VerificationStatus.VERIFIED_INCORRECT, partial.parts[1][1].status
        )
        self.assertIn("1 of 3", partial.result.detail)

        with self.assertRaisesRegex(ValueError, "several parts"):
            quest.check("-1.5")
        with self.assertRaisesRegex(ValueError, "several parts"):
            quest.evaluate("-1.5")
        with self.assertRaisesRegex(ValueError, r"part \(b\)"):
            quest.evaluate({"a": "-1.5", "c": "C"})
        private = _private_quest_document(quest)
        self.assertEqual("-3/2", private["parts"][0]["answer"])
        self.assertEqual("(4, 10)", private["parts"][1]["answer"])

    def test_multi_part_validation(self) -> None:
        def parse(**changes: object) -> None:
            document = multi_part_draft()
            document.update(changes)
            parse_adaptive_quest(json.dumps(document), skill=CALCULUS_SKILL)

        duplicate = multi_part_draft()["parts"][:2]
        duplicate[1] = {**duplicate[1], "label": "A"}
        with self.assertRaisesRegex(PracticeGenerationError, "short and unique"):
            parse(parts=duplicate)
        with self.assertRaisesRegex(PracticeGenerationError, "from 2 to 5 parts"):
            parse(parts=multi_part_draft()["parts"][:1])
        with self.assertRaisesRegex(PracticeGenerationError, "keep answer empty"):
            parse(answer="5")
        nested = multi_part_draft()["parts"]
        nested[0] = {**nested[0], "answer_type": "multi_part"}
        with self.assertRaisesRegex(PracticeGenerationError, "answer_type must be one of"):
            parse(parts=nested)
        extra = multi_part_draft()["parts"]
        extra[0] = {**extra[0], "hint": "no"}
        with self.assertRaisesRegex(PracticeGenerationError, "part fields must include"):
            parse(parts=extra)
        wrong_key = multi_part_draft()["parts"]
        wrong_key[1] = {**wrong_key[1], "answer": "(10, 4)"}
        with self.assertRaisesRegex(PracticeGenerationError, r"part \(b\)"):
            parse(parts=wrong_key)
        single = {
            "title": "Single",
            "prompt": "Evaluate 1 + 1. Enter only the number.",
            "answer_type": "expression",
            "answer": "2",
            "options": [],
            "help_steps": ["Add.", "Check."],
            "solution": "Two.",
            "graph": None,
            "parts": multi_part_draft()["parts"],
        }
        with self.assertRaisesRegex(PracticeGenerationError, "parts are allowed only"):
            parse_adaptive_quest(json.dumps(single), skill=CALCULUS_SKILL)

    def test_numeric_set_interval_and_point_keys_parse_and_check(self) -> None:
        def quest_for(**fields: object):
            document = {
                "title": "Format check",
                "prompt": "Answer the question. Enter the requested form.",
                "options": [],
                "help_steps": ["First move.", "Second move."],
                "solution": "Worked.",
                "graph": None,
            }
            document.update(fields)
            return parse_adaptive_quest(json.dumps(document), skill=CALCULUS_SKILL)

        numeric = quest_for(
            answer_type="numeric", answer="3.5", tolerance=0.02, unit="ft/s"
        )
        self.assertEqual(0.02, numeric.tolerance)
        self.assertEqual("ft/s", numeric.unit)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, numeric.check("3.45").status)
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, numeric.check("3.6").status)
        self.assertEqual("ft/s", numeric.public_dict()["unit"])
        self.assertIn("ft/s", numeric.public_dict()["answer_format_hint"])
        self.assertEqual(0.02, _private_quest_document(numeric)["tolerance"])

        solutions = quest_for(answer_type="solution_set", answer=["2", "-3"])
        self.assertEqual("2, -3", solutions.answer)
        self.assertEqual(
            VerificationStatus.VERIFIED_CORRECT, solutions.check("x = -3, x = 2").status
        )
        interval = quest_for(answer_type="interval", answer="(-oo, 1) U [3, oo)")
        self.assertEqual(
            VerificationStatus.VERIFIED_CORRECT,
            interval.check("[3, oo) U (-oo, 1)").status,
        )
        point = quest_for(answer_type="point", answer=[["1", "2"]])
        self.assertEqual("(1, 2)", point.answer)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, point.check("(1, 2)").status)
        self.assertIs(Outcome.INCORRECT, point.evaluate("(2, 1)").outcome)

        with self.assertRaisesRegex(PracticeGenerationError, "tolerance applies only"):
            quest_for(answer_type="expression", answer="x^2", tolerance=0.1)
        with self.assertRaisesRegex(PracticeGenerationError, "answer_type must be one of"):
            quest_for(answer_type="essay", answer="x")
        with self.assertRaisesRegex(PracticeGenerationError, "from 2 to 8"):
            quest_for(
                answer_type="expression",
                answer="2",
                help_steps=[f"Step {index}." for index in range(9)],
            )
        eight = quest_for(
            answer_type="expression",
            answer="2",
            help_steps=[f"Step {index}." for index in range(8)],
        )
        self.assertEqual(8, len(eight.help_steps))
