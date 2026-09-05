import tempfile
import unittest
from pathlib import Path
from sensei.storage import LearningStore
from sensei.learning import LearningEvent, Outcome


class FreshLearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "study.db"
        self.store = LearningStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def guide(self, name="Exam 1"):
        return self.store.create_study_plan(subject="Math", set_name=name,
                                           topics=[{"name": "Limits"}])

    def record(self, skill_id, outcome=Outcome.CORRECT, **overrides):
        fields = dict(skill_id=skill_id, outcome=outcome, misconception=None,
                      evidence="Checked answer", confidence=1.0, problem="Find the limit",
                      hints_used=0, solution_revealed=False, tutor_turns=1)
        return self.store.record_event(LearningEvent(**{**fields, **overrides}))

    def test_fresh_schema_has_no_catalog_or_rewards(self):
        self.assertEqual([], self.store.study_topics())
        self.assertEqual([], self.store.topic_folders())
        tables = {row[0] for row in self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("xp_events", tables)
        self.assertNotIn("schema_migrations", tables)
        self.assertNotIn("atlas_folders", tables)

    def test_guides_do_not_steal_same_named_concepts(self):
        first, second = self.guide(), self.guide("Exam 2")
        self.assertNotEqual(first["topics"][0]["id"], second["topics"][0]["id"])
        self.assertEqual([1, 1], [g["topic_count"] for g in self.store.topic_folders()])

    def test_support_and_misconceptions_persist_and_resolve_independently(self):
        skill_id = self.guide()["topics"][0]["id"]
        self.record(skill_id, Outcome.INCORRECT, misconception="Confuses limit and value")
        self.record(skill_id, hints_used=1)
        signal = self.store.generation_context(skill_id)
        self.assertTrue(signal["last_attempt_supported"])
        self.assertEqual(1, len(signal["misconceptions"]))
        self.record(skill_id)
        self.assertEqual(1, len(self.store.generation_context(skill_id)["misconceptions"]))
        self.record(skill_id)
        with LearningStore(self.path) as reopened:
            signal = reopened.generation_context(skill_id)
            self.assertEqual(4, signal["attempts_count"])
            self.assertEqual([], signal["misconceptions"])
            self.assertFalse(signal["last_attempt_supported"])

    def test_solution_and_lesson_completion_do_not_establish_mastery(self):
        skill_id = self.guide()["topics"][0]["id"]
        progress = self.record(skill_id, solution_revealed=True)
        self.assertEqual(0, progress.mastery_evidence)
        self.store.save_lesson(skill_id, "lesson-test", {"title": "Limits"}, 2)
        self.store.advance_lesson(skill_id, 0)
        final = self.store.advance_lesson(skill_id, 1)
        self.assertEqual("complete", final["status"])
        self.assertNotIn("xp_awarded", final)
        self.assertEqual(0, self.store.generation_context(skill_id)["mastery_score"])


class StudyPlanStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = LearningStore(self.root / "sensei.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    @staticmethod
    def _plan_topics() -> list[dict]:
        return [
            {
                "name": "Limits from a graph",
                "section": "1.2",
                "description": "Read one-sided and two-sided limits and function values from a graph.",
                "materials": [
                    {
                        "kind": "example_problem",
                        "body": "[Graph of f with a hole at (2, 1/2).] Find lim_{x->2} f(x).",
                        "solution": "L = 1/2",
                        "source_label": "Exercise 12",
                    },
                    {
                        "kind": "example_problem",
                        "body": "[Graph of g.] Find lim_{x->1^-} g(x).",
                        "solution": "L = 3",
                        "source_label": "Exercise 24",
                    },
                ],
            },
            {
                "name": "Squeeze theorem",
                "section": "1.4",
                "description": "Bound h(x) between two functions with equal limits.",
                "materials": [
                    {
                        "kind": "example_problem",
                        "body": "c = 0; 4 - x^2 <= h(x) <= 4 + x^2",
                        "solution": "L = 4",
                        "source_label": "Exercise 31",
                    }
                ],
            },
            {
                "name": "Vertical asymptotes versus holes",
                "section": "1.5",
                "description": "",
                "materials": [],
            },
        ]

    def test_plan_creates_folder_topics_materials_and_profile_atomically(self) -> None:
        result = self.store.create_study_plan(
            subject="MAC2311 Calculus I",
            set_name="Test 1",
            course_profile="Calculator in radian mode.",
            topics=self._plan_topics(),
        )
        self.assertEqual("Test 1", result["folder"]["name"])
        self.assertEqual(3, result["folder"]["topic_count"])
        self.assertEqual(3, result["created_topics"])
        self.assertEqual(0, result["updated_topics"])
        self.assertEqual(3, result["added_materials"])
        self.assertTrue(result["profile_saved"])
        names = [topic["name"] for topic in result["topics"]]
        self.assertEqual(
            ["Limits from a graph", "Squeeze theorem", "Vertical asymptotes versus holes"],
            names,
        )
        graph_topic = result["topics"][0]
        self.assertEqual("Section 1.2", graph_topic["unit"])
        self.assertEqual(result["folder"]["id"], graph_topic["folder_id"])
        self.assertEqual(2, graph_topic["material_count"])
        self.assertEqual(
            "No additional practice instructions were provided.",
            result["topics"][2]["description"],
        )
        self.assertEqual(
            {"MAC2311 Calculus I": "Calculator in radian mode."},
            self.store.subject_profiles(),
        )
        materials = self.store.topic_materials(graph_topic["id"])
        self.assertEqual(["Exercise 12", "Exercise 24"], [m["source_label"] for m in materials])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_reimport_merges_without_duplicates_and_keeps_existing_profile(self) -> None:
        first = self.store.create_study_plan(
            subject="MAC2311 Calculus I",
            set_name="Test 1",
            course_profile="Original profile.",
            topics=self._plan_topics(),
        )
        topics = self._plan_topics()
        topics[0]["materials"].append(
            {
                "kind": "example_problem",
                "body": "[Graph of f.] Find f(4).",
                "solution": "y = 2",
                "source_label": "Exercise 17",
            }
        )
        topics[1]["description"] = "Updated brief for the squeeze theorem."
        second = self.store.create_study_plan(
            subject="mac2311 calculus i",
            set_name="test 1",
            course_profile="A different profile.",
            topics=topics,
        )
        self.assertEqual(first["folder"]["id"], second["folder"]["id"])
        self.assertEqual(0, second["created_topics"])
        self.assertEqual(3, second["updated_topics"])
        self.assertEqual(1, second["added_materials"])
        self.assertFalse(second["profile_saved"])
        self.assertEqual(
            {"MAC2311 Calculus I": "Original profile."}, self.store.subject_profiles()
        )
        self.assertEqual(1, len(self.store.topic_folders()))
        self.assertEqual(3, len(self.store.study_topics()))
        self.assertEqual(
            "Updated brief for the squeeze theorem.", second["topics"][1]["description"]
        )
        self.assertEqual(3, self.store.study_topic(first["topics"][0]["id"])["material_count"])

    def test_plan_validation_rolls_back_everything(self) -> None:
        with self.assertRaisesRegex(ValueError, "from 1 to 40"):
            self.store.create_study_plan(subject="Calc", set_name="Test", topics=[])
        with self.assertRaisesRegex(ValueError, "more than once"):
            self.store.create_study_plan(
                subject="Calc",
                set_name="Test",
                topics=[{"name": "Limits"}, {"name": "limits"}],
            )
        with self.assertRaisesRegex(ValueError, "4000 characters"):
            self.store.create_study_plan(
                subject="Calc",
                set_name="Test",
                topics=[{"name": "Limits", "materials": [{"body": "x" * 4_001}]}],
            )
        self.assertEqual([], self.store.topic_folders())
        self.assertEqual([], self.store.study_topics())
        with self.assertRaisesRegex(ValueError, "Folder name"):
            self.store.create_study_plan(subject="Calc", set_name=" ", topics=[{"name": "L"}])
