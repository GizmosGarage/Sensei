import json
import unittest

from sensei.practice import AdaptiveQuestFactory, parse_adaptive_quest
from sensei.providers import CompletionResult
from sensei.verification import VerificationStatus


SKILL = {
    "id": "focus-stoichiometry-test",
    "course": "Chemistry",
    "name": "Stoichiometry",
    "description": "Practice mole ratios.",
    "difficulty": "foundation",
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
        self.assertEqual(2, len(provider.requests))

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


if __name__ == "__main__":
    unittest.main()
