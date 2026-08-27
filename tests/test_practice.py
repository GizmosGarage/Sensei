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
    "difficulty": "beginner",
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
                    "For 2 H2 + O2 -> 2 H2O, how many moles of H2O form "
                    "from 3 moles of H2? Enter only the number."
                ),
                "answer_type": "expression",
                "answer": "3",
                "options": [],
                "hint": "Compare the coefficients of H2 and H2O.",
                "solution": "The coefficient ratio is 2:2, or 1:1, so 3 moles form.",
                "graph": None,
            }
        )
        provider = StubProvider(
            [draft, json.dumps({"approved": True, "reason": "Answer recomputed."})]
        )
        quest = AdaptiveQuestFactory(provider).generate(SKILL)
        self.assertEqual("Stoichiometry", quest.topic)
        self.assertEqual("beginner", quest.difficulty)
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, quest.check("3").status)
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, quest.check("6").status)
        public = quest.public_dict()
        self.assertNotIn("answer", public)
        self.assertNotIn("solution", public)
        self.assertEqual(2, len(provider.requests))
        self.assertIn(
            "Beginner (level 1 of 4)",
            provider.requests[0][-1]["content"],
        )
        self.assertIn(
            "Requested problem difficulty: Beginner (level 1 of 4)",
            provider.requests[1][-1]["content"],
        )

    def test_all_four_difficulties_have_specific_generation_contracts(self) -> None:
        expected = {
            "beginner": ("Beginner (level 1 of 4)", "one direct step"),
            "intermediate": ("Intermediate (level 2 of 4)", "two or three connected steps"),
            "advanced": ("Advanced (level 3 of 4)", "multi-step reasoning"),
            "expert": ("Expert (level 4 of 4)", "subtle edge case or constraint"),
        }
        for difficulty, phrases in expected.items():
            with self.subTest(difficulty=difficulty):
                messages = AdaptiveQuestFactory._request(
                    {**SKILL, "difficulty": difficulty},
                    "",
                    variation_key="test-variation",
                    avoid_prompts=(),
                )
                request = messages[-1]["content"]
                for phrase in phrases:
                    self.assertIn(phrase, request)
                self.assertIn("graph", messages[0]["content"])

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
                        "Catalyst",
                        "Limiting reagent",
                        "Solvent",
                        "Excess reagent",
                    ],
                    "hint": "Its name describes the cap it places on product.",
                    "solution": "The limiting reagent is exhausted first.",
                    "graph": None,
                }
            ),
            skill=SKILL,
        )
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, quest.check("B").status)
        self.assertEqual(
            VerificationStatus.VERIFIED_CORRECT,
            quest.check("Limiting reagent").status,
        )
        self.assertEqual(VerificationStatus.VERIFIED_INCORRECT, quest.check("D").status)

    def test_walkthrough_allows_bounded_local_model_verbosity(self) -> None:
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
            "Use the displayed graph to determine the limit of f(x) as x approaches "
            "2. Enter only the value of the limit.",
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
                    raise ProviderError("temporary local model disconnect")
                return super().complete(messages, on_token)

        provider = FlakyProvider()
        quest = AdaptiveQuestFactory(provider).generate(SKILL)
        self.assertEqual("2", quest.answer)
        self.assertEqual(3, len(provider.requests))


if __name__ == "__main__":
    unittest.main()
