import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from sensei.cli import (
    _answer_quest,
    _check_problem,
    _memory_command,
    _profile_text,
    _review_text,
    _skills_text,
    parse_args,
)
from sensei.learning import LearningEvent, Outcome
from sensei.quests import QuestDeck
from sensei.storage import LearningStore
from sensei.tutor import TutorSession
from sensei.verification import CalculusVerifier, VerificationStatus


class CliTests(unittest.TestCase):
    def test_fast_and_model_id_are_mutually_exclusive(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--fast", "--model-id", "another-model"])

    def test_one_shot_mode_parses(self) -> None:
        args = parse_args(["--prompt", "Differentiate x^2", "--mode", "hint"])
        self.assertEqual("Differentiate x^2", args.prompt)
        self.assertEqual("hint", args.mode)

    def test_derivative_check_wizard_attaches_authoritative_result(self) -> None:
        session = TutorSession(object(), "test-model")
        session.reset("Differentiate sin(x^2)")
        output = StringIO()
        with redirect_stdout(output), patch(
            "builtins.input",
            side_effect=["sin(x^2)", "", "2x*cos(x^2)"],
        ):
            result = _check_problem(session, CalculusVerifier(), "derivative")
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)
        self.assertIs(result, session.last_verification)
        self.assertIn("VERIFIED CORRECT", output.getvalue())

    def test_quest_answer_uses_curated_target(self) -> None:
        quest = QuestDeck.load().by_skill["chain_rule"][0]
        session = TutorSession(object(), "test-model")
        session.reset(quest.prompt)
        session.set_quest(quest)
        output = StringIO()
        with redirect_stdout(output):
            result = _answer_quest(
                session,
                CalculusVerifier(),
                "3x^2 cos(x^3)",
            )
        self.assertEqual(VerificationStatus.VERIFIED_CORRECT, result.status)
        self.assertIn("Quest cleared", output.getvalue())
        self.assertIs(result, session.last_verification)

    def test_profile_and_skills_format_for_terminal(self) -> None:
        profile = _profile_text(
            {
                "level": 2,
                "xp_into_level": 20,
                "xp_for_next_level": 200,
                "total_xp": 120,
                "attempts": 5,
                "skills_practiced": 2,
                "skills_mastered": 1,
            }
        )
        self.assertIn("Level 2", profile)
        self.assertIn("120 total", profile)
        skills = _skills_text(
            [
                {
                    "name": "Chain rule",
                    "mastery_score": 72.0,
                    "mastery_label": "proficient",
                    "attempts_count": 3,
                    "next_review_at": "2026-08-23T12:00:00+00:00",
                }
            ],
            include_all=False,
        )
        self.assertIn("Chain rule: 72/100", skills)
        review = _review_text(
            {
                "name": "Chain rule",
                "mastery_score": 72.0,
                "mastery_label": "proficient",
                "next_review_at": "2026-08-23T12:00:00+00:00",
                "misconception": "Forgot the inner derivative.",
                "due": True,
            }
        )
        self.assertIn("due now", review)
        self.assertIn("Forgot the inner derivative", review)

    def test_confirmed_deletion_also_clears_in_process_learner_context(self) -> None:
        with TemporaryDirectory() as directory:
            with LearningStore(Path(directory) / "sensei.db") as store:
                store.record_event(
                    LearningEvent(
                        skill_id="chain_rule",
                        outcome=Outcome.INCORRECT,
                        misconception="Missing inner derivative.",
                        evidence="The student omitted 2x.",
                        confidence=1.0,
                        problem="Differentiate sin(x^2)",
                        hints_used=0,
                        solution_revealed=False,
                        tutor_turns=1,
                    )
                )
                session = TutorSession(object(), "test-model")
                session.set_learner_context(store.tutor_context())
                with redirect_stdout(StringIO()), patch(
                    "builtins.input", return_value="DELETE"
                ):
                    handled = _memory_command(
                        "/delete-data", "", session, store, object()
                    )
                self.assertTrue(handled)
                self.assertIsNone(session.learner_context)
                self.assertEqual(0, store.profile()["attempts"])


if __name__ == "__main__":
    unittest.main()
