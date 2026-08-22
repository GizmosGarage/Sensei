import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sensei.learning import LearningEvent, Outcome
from sensei.quests import QuestDeck
from sensei.storage import LearningStore
from sensei.verification import CalculusVerifier, VerificationStatus


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class QuestDeckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.deck = QuestDeck.load()
        cls.verifier = CalculusVerifier()

    def test_catalog_ids_are_unique_and_samples_are_verified(self) -> None:
        self.assertEqual(20, len(self.deck.quests))
        self.assertEqual(20, len({quest.id for quest in self.deck.quests}))
        for quest in self.deck.quests:
            with self.subTest(quest=quest.id):
                result = quest.check(quest.sample_answer, self.verifier)
                self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)

    def test_public_quest_does_not_reveal_sample_or_symbolic_target(self) -> None:
        quest = self.deck.quests[0]
        public = quest.public_dict(skill_name="Calculus foundations")
        self.assertNotIn("sample_answer", public)
        self.assertNotIn("verification", public)
        self.assertEqual("/answer YOUR_EXPRESSION", public["answer_command"])

    def test_recommendation_starts_with_foundations_then_uses_review_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with LearningStore(Path(directory) / "sensei.db") as store:
                first = self.deck.recommend(store, now=NOW)
                self.assertEqual("calculus_foundations", first.quest.skill_id)
                store.record_event(
                    LearningEvent(
                        skill_id="chain_rule",
                        outcome=Outcome.INCORRECT,
                        misconception="Missed the inner derivative.",
                        evidence="The answer omitted 3x^2.",
                        confidence=1.0,
                        problem="Differentiate sin(x^3)",
                        hints_used=0,
                        solution_revealed=False,
                        tutor_turns=1,
                    ),
                    now=NOW,
                )
                review = self.deck.recommend(store, now=NOW)
                self.assertEqual("chain_rule", review.quest.skill_id)
                self.assertEqual("chain-square-root", review.quest.id)
                self.assertFalse(review.due)


if __name__ == "__main__":
    unittest.main()
