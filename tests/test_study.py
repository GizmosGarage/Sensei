import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sensei.dashboard import DashboardService
from sensei.study import guide_progress


class StudyGuideTests(unittest.TestCase):
    def setUp(self):
        self.topics = [
            {"id": "a", "name": "Limits", "lesson_status": "none"},
            {"id": "b", "name": "Continuity", "lesson_status": "none"},
        ]
        self.contexts = {
            key: {"attempts_count": 0, "mastery_score": 0, "recent_outcomes": [],
                  "misconceptions": [], "mastery_label": "Developing"}
            for key in ("a", "b")
        }

    def progress(self):
        return guide_progress(self.topics, self.contexts,
                              now=datetime(2026, 9, 5, tzinfo=timezone.utc))

    def test_unseen_concepts_are_unknown_and_checked_before_known_gaps(self):
        self.contexts["a"].update(attempts_count=1, recent_outcomes=["incorrect"])
        result = self.progress()
        self.assertEqual("b", result["next"]["skill_id"])
        self.assertEqual("Not checked yet", result["concepts"][1]["status"])
        self.assertEqual(1, result["checked"])

    def test_gap_gets_explanation_then_independent_check(self):
        self.topics = self.topics[:1]
        self.contexts["a"].update(attempts_count=1, recent_outcomes=["partial"])
        self.assertEqual("learn", self.progress()["next"]["action"])
        self.topics[0]["lesson_status"] = "complete"
        self.assertEqual("practice", self.progress()["next"]["action"])

    def test_unresolved_mistake_stays_visible_after_one_correct_answer(self):
        self.topics = self.topics[:1]
        self.contexts["a"].update(attempts_count=2, recent_outcomes=["correct"],
                                  misconceptions=["Confuses value and limit"])
        result = self.progress()
        self.assertEqual("Needs practice", result["concepts"][0]["status"])
        self.assertEqual(["Confuses value and limit"], result["concepts"][0]["mistakes"])

    def test_due_review_precedes_optional_practice(self):
        for signal in self.contexts.values():
            signal.update(attempts_count=5, recent_outcomes=["correct"], mastery_score=50)
        self.topics[1]["next_review_at"] = "2026-09-04T00:00:00+00:00"
        self.contexts["b"]["mastery_score"] = 90
        self.assertEqual("b", self.progress()["next"]["skill_id"])
        self.assertEqual("Review understanding", self.progress()["next"]["label"])

    def test_weakest_evidence_is_next_when_no_reviews_are_due(self):
        for signal in self.contexts.values():
            signal.update(attempts_count=5, recent_outcomes=["correct"], mastery_score=70)
        self.contexts["b"]["mastery_score"] = 30
        self.assertEqual("b", self.progress()["next"]["skill_id"])

    def test_correct_answer_with_help_still_needs_independent_evidence(self):
        self.topics = self.topics[:1]
        self.contexts["a"].update(attempts_count=1, recent_outcomes=["correct"],
                                  last_attempt_supported=True)
        self.assertEqual("Needs practice", self.progress()["concepts"][0]["status"])
        self.assertEqual("learn", self.progress()["next"]["action"])

    def test_empty_guide_has_no_action(self):
        self.assertIsNone(guide_progress([], {})["next"])

    def test_dashboard_scopes_recommendations_to_each_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            service = DashboardService(Path(directory) / "study.db")
            first = service.create_study_plan(subject="Math", set_name="Exam 1", course_profile="", topics=[{"name": "Limits"}])
            second = service.create_study_plan(subject="Math", set_name="Exam 2", course_profile="", topics=[{"name": "Continuity"}])
            guides = service.state()["study_guides"]
            self.assertEqual(2, len(guides))
            self.assertEqual(first["topics"][0]["id"], guides[0]["next"]["skill_id"])
            self.assertEqual(second["topics"][0]["id"], guides[1]["next"]["skill_id"])
