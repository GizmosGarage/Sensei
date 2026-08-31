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
            "Every quantitative given must be necessary",
            provider.requests[0][0]["content"],
        )
        self.assertIn("KaTeX-compatible LaTeX", provider.requests[0][0]["content"])
        self.assertIn(r"\ce{2H2 + O2 -> 2H2O}", provider.requests[0][0]["content"])
        self.assertIn(
            "use inline \\(...\\) notation only",
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
            "Reject unused or redundant quantitative givens",
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
