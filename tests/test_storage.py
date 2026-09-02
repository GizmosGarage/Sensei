import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sensei.learning import LearningEvent, Outcome
from sensei.storage import (
    MIGRATION_1,
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    LearningStore,
    evidence_score,
    mastery_score,
    xp_award,
    xp_level,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def event(
    *,
    outcome: Outcome = Outcome.CORRECT,
    misconception: str | None = None,
    hints_used: int = 0,
    solution_revealed: bool = False,
    confidence: float = 1.0,
) -> LearningEvent:
    return LearningEvent(
        skill_id="chain_rule",
        outcome=outcome,
        misconception=misconception,
        evidence="The student identified and applied the inner derivative.",
        confidence=confidence,
        problem="Differentiate sin(x^2)",
        hints_used=hints_used,
        solution_revealed=solution_revealed,
        tutor_turns=2,
    )


class ProgressionRuleTests(unittest.TestCase):
    def test_xp_is_additive_and_independent_work_gets_bonus(self) -> None:
        self.assertEqual(
            (25, "practice effort, correct result, independent solution"),
            xp_award(event()),
        )
        self.assertEqual(5, xp_award(event(outcome=Outcome.INCORRECT))[0])
        self.assertEqual(20, xp_award(event(hints_used=1))[0])
        self.assertEqual(15, xp_award(event(hints_used=2))[0])
        self.assertEqual(0, xp_award(event(hints_used=3, solution_revealed=True))[0])
        self.assertEqual((2, 0, 200), xp_level(100))

    def test_low_confidence_pulls_mastery_evidence_toward_neutral(self) -> None:
        self.assertEqual(100.0, evidence_score(event()))
        self.assertEqual(50.0, evidence_score(event(confidence=0.0)))
        self.assertEqual(85.0, evidence_score(event(hints_used=1)))
        self.assertEqual(70.0, evidence_score(event(hints_used=2)))
        self.assertEqual(0.0, evidence_score(event(outcome=Outcome.INCORRECT)))
        self.assertEqual(0.0, evidence_score(event(solution_revealed=True)))

    def test_mastery_combines_accuracy_with_practice_volume(self) -> None:
        self.assertEqual(31.62, mastery_score(100.0, 1))
        self.assertEqual(70.71, mastery_score(500.0, 5))
        self.assertEqual(83.67, mastery_score(700.0, 7))
        self.assertEqual(90.0, mastery_score(900.0, 10))
        self.assertEqual(0.0, mastery_score(0.0, 0))


class LearningStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "sensei.db"
        self.store = LearningStore(self.database)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_schema_is_versioned_and_skill_catalog_is_seeded(self) -> None:
        version = self.store.connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        self.assertEqual(10, version)
        self.assertEqual(37, len(self.store.skill_names()))
        self.store.close()
        self.store = LearningStore(self.database)
        migration_count = self.store.connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]
        self.assertEqual(10, migration_count)

    def test_schema_v1_database_migrates_and_backfills_provenance(self) -> None:
        self.store.close()
        old_database = self.root / "version-one.db"
        connection = sqlite3.connect(old_database)
        connection.executescript(MIGRATION_1)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (NOW.isoformat(),),
        )
        connection.execute(
            """INSERT INTO skills(
                   id, name, unit, description, prerequisites_json, sort_order
               ) VALUES ('chain_rule', 'Chain rule', 'Derivatives', 'Test', '[]', 0)"""
        )
        connection.execute(
            """INSERT INTO attempts(
                   skill_id, problem, outcome, outcome_source, evidence, confidence,
                   hints_used, solution_revealed, tutor_turns, created_at
               ) VALUES (
                   'chain_rule', 'Differentiate x^2', 'correct', 'student',
                   'Student answer.', 1, 0, 0, 1, ?
               )""",
            (NOW.isoformat(),),
        )
        connection.execute(
            """INSERT INTO mastery(
                   skill_id, mastery_score, attempts_count, correct_count,
                   partial_count, incorrect_count, independent_correct_count,
                   success_streak, last_practiced_at, next_review_at, updated_at
               ) VALUES ('chain_rule', 100, 1, 1, 0, 0, 1, 1, ?, ?, ?)""",
            (NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
        connection.close()

        self.store = LearningStore(old_database)
        attempt = self.store.connection.execute(
            "SELECT * FROM attempts"
        ).fetchone()
        self.assertEqual("correct", attempt["reported_outcome"])
        self.assertEqual("reported", attempt["effective_outcome_source"])
        self.assertEqual("unverified", attempt["verification_status"])
        version = self.store.connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        self.assertEqual(10, version)
        self.assertIsNone(attempt["quest_id"])
        self.assertEqual(100.0, attempt["mastery_evidence"])
        progress = self.store.connection.execute(
            "SELECT mastery_score FROM mastery WHERE skill_id = 'chain_rule'"
        ).fetchone()
        self.assertEqual(31.62, progress["mastery_score"])

    def test_schema_v2_database_migrates_quest_provenance(self) -> None:
        self.store.close()
        old_database = self.root / "version-two.db"
        connection = sqlite3.connect(old_database)
        connection.executescript(MIGRATION_1)
        connection.executescript(MIGRATION_2)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(1, NOW.isoformat()), (2, NOW.isoformat())],
        )
        connection.commit()
        connection.close()

        self.store = LearningStore(old_database)
        columns = {
            row["name"]
            for row in self.store.connection.execute("PRAGMA table_info(attempts)")
        }
        self.assertIn("quest_id", columns)
        version = self.store.connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        self.assertEqual(10, version)

    def test_schema_v3_database_migrates_course_and_preserves_old_skills(self) -> None:
        self.store.close()
        old_database = self.root / "version-three.db"
        connection = sqlite3.connect(old_database)
        connection.executescript(MIGRATION_1)
        connection.executescript(MIGRATION_2)
        connection.executescript(MIGRATION_3)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(1, NOW.isoformat()), (2, NOW.isoformat()), (3, NOW.isoformat())],
        )
        connection.execute(
            """INSERT INTO skills(
                   id, name, unit, description, prerequisites_json, sort_order
               ) VALUES ('chain_rule', 'Chain rule', 'Derivatives', 'Test', '[]', 0)"""
        )
        connection.commit()
        connection.close()

        self.store = LearningStore(old_database)
        row = self.store.connection.execute(
            "SELECT course FROM skills WHERE id = 'chain_rule'"
        ).fetchone()
        self.assertEqual("calculus", row["course"])
        version = self.store.connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        self.assertEqual(10, version)

    def test_schema_v6_removes_obsolete_skill_metadata_without_losing_topics(self) -> None:
        self.store.close()
        old_database = self.root / "version-six.db"
        connection = sqlite3.connect(old_database)
        for migration in (
            MIGRATION_1,
            MIGRATION_2,
            MIGRATION_3,
            MIGRATION_4,
            MIGRATION_5,
        ):
            connection.executescript(migration)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(version, NOW.isoformat()) for version in range(1, 7)],
        )
        connection.execute("ALTER TABLE skills ADD COLUMN obsolete_mode TEXT")
        connection.execute(
            """INSERT INTO skills(
                   id, name, unit, description, prerequisites_json, sort_order,
                   course, source, created_at, obsolete_mode
               ) VALUES ('legacy-topic', 'Legacy topic', 'Legacy', 'Test', '[]',
                         100, 'Mathematics', 'learner', ?, 'old-value')""",
            (NOW.isoformat(),),
        )
        connection.commit()
        connection.close()

        self.store = LearningStore(old_database)
        topic = self.store.study_topic("legacy-topic")
        self.assertEqual("Legacy topic", topic["name"])
        columns = {
            row["name"]
            for row in self.store.connection.execute("PRAGMA table_info(skills)")
        }
        self.assertNotIn("obsolete_mode", columns)
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_learner_topics_expand_the_catalog_without_a_fixed_course(self) -> None:
        topic = self.store.create_study_topic(
            subject="Chemistry",
            topic="Stoichiometry",
            context="Mole ratios and limiting reagents",
        )
        self.assertEqual("Chemistry", topic["course"])
        self.assertEqual("learner", topic["source"])
        self.assertEqual(38, len(self.store.skill_names()))
        self.assertEqual([topic["id"]], [item["id"] for item in self.store.study_topics()])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_named_subject_folders_persist_and_move_topics_without_deleting_them(self) -> None:
        stoichiometry = self.store.create_study_topic(
            subject="Chemistry", topic="Stoichiometry", context="Mole ratios"
        )
        lewis = self.store.create_study_topic(
            subject="Chemistry", topic="Lewis structures", context="Valence electrons"
        )
        quadratic = self.store.create_study_topic(
            subject="Mathematics", topic="Quadratic equations", context="Factoring"
        )

        review = self.store.create_topic_folder(
            subject="Chemistry",
            name="Exam Review",
            skill_ids=[stoichiometry["id"], lewis["id"]],
        )
        self.assertEqual(
            [stoichiometry["id"], lewis["id"]], review["topic_ids"]
        )
        self.assertEqual(
            review["id"], self.store.study_topic(stoichiometry["id"])["folder_id"]
        )

        renamed = self.store.update_topic_folder(
            review["id"], name="Final Review", skill_ids=[lewis["id"]]
        )
        self.assertEqual("Final Review", renamed["name"])
        self.assertIsNone(self.store.study_topic(stoichiometry["id"])["folder_id"])

        priority = self.store.create_topic_folder(
            subject="Chemistry", name="Priority", skill_ids=[lewis["id"]]
        )
        self.assertEqual([], self.store.topic_folders()[0]["topic_ids"])
        self.assertEqual(
            priority["id"], self.store.study_topic(lewis["id"])["folder_id"]
        )
        with self.assertRaisesRegex(ValueError, "must belong to its subject"):
            self.store.update_topic_folder(
                priority["id"], name="Priority", skill_ids=[quadratic["id"]]
            )

        deletion = self.store.delete_topic_folder(priority["id"])
        self.assertEqual(1, deletion["topic_count"])
        self.assertIsNone(self.store.study_topic(lewis["id"])["folder_id"])
        self.assertEqual("Lewis structures", self.store.study_topic(lewis["id"])["name"])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

        self.store.close()
        self.store = LearningStore(self.database)
        self.assertEqual("Final Review", self.store.topic_folders()[0]["name"])

    def test_folder_names_are_unique_within_a_subject(self) -> None:
        self.store.create_study_topic(
            subject="Chemistry", topic="Stoichiometry", context="Mole ratios"
        )
        self.store.create_topic_folder(
            subject="Chemistry", name="Exam Review", skill_ids=[]
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.store.create_topic_folder(
                subject="Chemistry", name="  EXAM   REVIEW  ", skill_ids=[]
            )

    def test_delete_learner_topic_removes_every_related_learning_record(self) -> None:
        topic = self.store.create_study_topic(
            subject="Chemistry",
            topic="Stoichiometry",
            context="Mole ratios and limiting reagents",
        )
        folder = self.store.create_topic_folder(
            subject="Chemistry", name="Review", skill_ids=[topic["id"]]
        )
        self.store.record_event(
            LearningEvent(
                skill_id=topic["id"],
                outcome=Outcome.INCORRECT,
                misconception="Used mass as though it were moles.",
                evidence="The conversion skipped molar mass.",
                confidence=1.0,
                problem="Convert 18 g H2O to moles.",
                hints_used=0,
                solution_revealed=False,
                tutor_turns=1,
            ),
            now=NOW,
        )

        deletion = self.store.delete_study_topic(topic["id"])

        self.assertEqual(topic["id"], deletion["skill_id"])
        self.assertEqual(1, deletion["deleted_attempts"])
        self.assertEqual(0, self.store.profile()["attempts"])
        for table in ("skills", "attempts", "misconceptions", "mastery"):
            count = self.store.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE "
                + ("id = ?" if table == "skills" else "skill_id = ?"),
                (topic["id"],),
            ).fetchone()[0]
            self.assertEqual(0, count, table)
        self.assertEqual(
            0,
            self.store.connection.execute("SELECT COUNT(*) FROM xp_events").fetchone()[0],
        )
        self.assertEqual([], self.store.topic_folders()[0]["topic_ids"])
        self.assertEqual(folder["id"], self.store.topic_folders()[0]["id"])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.study_topic(topic["id"])

    def test_restart_topic_clears_its_progress_but_preserves_topic_and_folder(self) -> None:
        topic = self.store.create_study_topic(
            subject="Chemistry",
            topic="Stoichiometry",
            context="Mole ratios and limiting reagents",
        )
        folder = self.store.create_topic_folder(
            subject="Chemistry", name="Review", skill_ids=[topic["id"]]
        )
        self.store.record_event(event(), now=NOW)
        self.store.record_event(
            LearningEvent(
                skill_id=topic["id"],
                outcome=Outcome.INCORRECT,
                misconception="Used mass as though it were moles.",
                evidence="The conversion skipped molar mass.",
                confidence=1.0,
                problem="Convert 18 g H2O to moles.",
                hints_used=0,
                solution_revealed=False,
                tutor_turns=1,
            ),
            now=NOW,
        )

        restart = self.store.restart_study_topic(topic["id"])

        self.assertEqual(topic["id"], restart["skill_id"])
        self.assertEqual(1, restart["deleted_attempts"])
        self.assertEqual(5, restart["removed_xp"])
        self.assertEqual(folder["id"], self.store.study_topic(topic["id"])["folder_id"])
        progress = next(
            item for item in self.store.study_topics() if item["id"] == topic["id"]
        )
        self.assertEqual(0, progress["attempts_count"])
        self.assertEqual(0.0, progress["mastery_score"])
        self.assertEqual("not started", progress["mastery_label"])
        self.assertEqual(1, self.store.profile()["attempts"])
        self.assertEqual(25, self.store.profile()["total_xp"])
        for table in ("attempts", "misconceptions", "mastery"):
            self.assertEqual(
                0,
                self.store.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE skill_id = ?", (topic["id"],)
                ).fetchone()[0],
                table,
            )
        second_restart = self.store.restart_study_topic(topic["id"])
        self.assertEqual(0, second_restart["deleted_attempts"])
        self.assertEqual(0, second_restart["removed_xp"])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_delete_practiced_catalog_topic_keeps_only_catalog_definition(self) -> None:
        self.store.record_event(event(), now=NOW)

        self.store.delete_study_topic("chain_rule")

        self.assertIn("chain_rule", self.store.skill_names())
        self.assertNotIn(
            "chain_rule", {topic["id"] for topic in self.store.study_topics()}
        )
        self.assertEqual(0, self.store.profile()["attempts"])
        with self.assertRaisesRegex(ValueError, "Atlas topic does not exist"):
            self.store.delete_study_topic("chain_rule")

    def test_record_event_updates_xp_mastery_and_review(self) -> None:
        first = self.store.record_event(event(), now=NOW)
        self.assertEqual(25, first.xp_awarded)
        self.assertEqual(31.62, first.mastery_score)
        self.assertEqual("beginning", first.mastery_label)
        self.assertEqual("2026-08-23", first.next_review_at[:10])

        for _ in range(5):
            self.store.record_event(event(), now=NOW)
        seventh = self.store.record_event(event(), now=NOW)
        self.assertEqual(83.67, seventh.mastery_score)
        self.assertEqual("mastered", seventh.mastery_label)
        self.assertEqual("2026-09-22", seventh.next_review_at[:10])
        profile = self.store.profile()
        self.assertEqual(175, profile["total_xp"])
        self.assertEqual(1, profile["skills_mastered"])

    def test_wrong_answers_lower_mastery_without_deducting_xp(self) -> None:
        for _ in range(5):
            self.store.record_event(event(), now=NOW)
        for _ in range(5):
            update = self.store.record_event(
                event(outcome=Outcome.INCORRECT), now=NOW
            )

        self.assertEqual(50.0, update.mastery_score)
        self.assertEqual("developing", update.mastery_label)
        self.assertEqual(5, update.xp_awarded)
        self.assertEqual(150, update.total_xp)

    def test_record_event_preserves_report_and_verifier_provenance(self) -> None:
        verified = LearningEvent(
            skill_id="chain_rule",
            outcome=Outcome.INCORRECT,
            misconception="Forgot the inner derivative.",
            evidence="The submitted derivative omitted 2x.",
            confidence=1.0,
            problem="Differentiate sin(x^2)",
            hints_used=0,
            solution_revealed=False,
            tutor_turns=1,
            outcome_source="student",
            reported_outcome=Outcome.CORRECT,
            effective_outcome_source="verifier",
            verification_status="verified_incorrect",
            verification_kind="derivative",
            verifier_version="test-verifier-1",
            verification_submitted="cos(x**2)",
            verification_expected="2*x*cos(x**2)",
            verification_detail="Residual difference: -2*x*cos(x**2) + cos(x**2).",
            quest_id="chain-sine-cubic",
        )
        update = self.store.record_event(verified, now=NOW)
        attempt = self.store.connection.execute(
            "SELECT * FROM attempts"
        ).fetchone()
        self.assertEqual(5, update.xp_awarded)
        self.assertEqual("incorrect", attempt["outcome"])
        self.assertEqual("correct", attempt["reported_outcome"])
        self.assertEqual("student", attempt["outcome_source"])
        self.assertEqual("verifier", attempt["effective_outcome_source"])
        self.assertEqual("verified_incorrect", attempt["verification_status"])
        self.assertEqual("test-verifier-1", attempt["verifier_version"])
        self.assertEqual("chain-sine-cubic", attempt["quest_id"])
        recent = self.store.recent_attempts()
        self.assertEqual("chain-sine-cubic", recent[0]["quest_id"])
        self.assertEqual("Chain rule", recent[0]["skill_name"])
        self.assertEqual("calculus", recent[0]["course"])
        self.assertEqual(
            ("Differentiate sin(x^2)",),
            self.store.recent_problems("chain_rule"),
        )

    def test_misconceptions_are_counted_without_duplicate_rows(self) -> None:
        mistaken = event(
            outcome=Outcome.INCORRECT,
            misconception="Forgot the derivative of the inner function.",
        )
        self.store.record_event(mistaken, now=NOW)
        self.store.record_event(mistaken, now=NOW)
        rows = list(self.store.connection.execute("SELECT * FROM misconceptions"))
        self.assertEqual(1, len(rows))
        self.assertEqual(2, rows[0]["occurrence_count"])
        context = self.store.tutor_context()
        self.assertIn("Chain rule: beginning", context)
        self.assertIn("Forgot the derivative", context)
        recommendation = self.store.review_recommendation(now=NOW)
        self.assertEqual("chain_rule", recommendation["id"])

    def test_export_backup_and_confirmed_deletion_primitives(self) -> None:
        self.store.record_event(event(), now=NOW)
        export_path = self.store.export_json(self.root / "export.json")
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(exported["attempts"]))
        self.assertNotIn("messages", exported["attempts"][0])
        self.assertEqual("model", exported["attempts"][0]["outcome_source"])

        backup_path = self.store.backup(self.root / "backup.db")
        backup = sqlite3.connect(backup_path)
        try:
            count = backup.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        finally:
            backup.close()
        self.assertEqual(1, count)

        self.store.delete_learning_data()
        self.assertEqual(0, self.store.profile()["attempts"])
        self.assertEqual(37, len(self.store.skill_names()))


if __name__ == "__main__":
    unittest.main()


from datetime import timedelta  # noqa: E402

from sensei.storage import (  # noqa: E402
    MIGRATION_7,
    MIGRATION_8,
    MIGRATION_9,
    difficulty_tier,
)


class ClassMaterialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = LearningStore(self.root / "sensei.db")

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    @staticmethod
    def _learner_event(skill_id: str, **overrides: object) -> LearningEvent:
        fields: dict[str, object] = dict(
            skill_id=skill_id,
            outcome=Outcome.CORRECT,
            misconception=None,
            evidence="The verifier checked the dashboard answer.",
            confidence=1.0,
            problem="Find dy/dx for the given relation.",
            hints_used=0,
            solution_revealed=False,
            tutor_turns=1,
        )
        fields.update(overrides)
        return LearningEvent(**fields)  # type: ignore[arg-type]

    def _topic(self, name: str = "Related rates") -> str:
        return str(
            self.store.create_study_topic(
                subject="Calculus I", topic=name, context=""
            )["id"]
        )

    def test_schema_v9_database_migrates_to_class_material_tables(self) -> None:
        self.store.close()
        old_database = self.root / "version-nine.db"
        connection = sqlite3.connect(old_database)
        for migration in (
            MIGRATION_1,
            MIGRATION_2,
            MIGRATION_3,
            MIGRATION_4,
            MIGRATION_5,
            MIGRATION_7,
            MIGRATION_8,
            MIGRATION_9,
        ):
            connection.executescript(migration)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(version, NOW.isoformat()) for version in range(1, 10)],
        )
        connection.execute(
            """INSERT INTO skills(
                   id, name, unit, description, prerequisites_json, sort_order,
                   course, source, created_at
               ) VALUES ('legacy-topic', 'Legacy topic', 'Legacy', 'Test', '[]',
                         100, 'Calculus I', 'learner', ?)""",
            (NOW.isoformat(),),
        )
        connection.commit()
        connection.close()

        self.store = LearningStore(old_database)
        version = self.store.connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        self.assertEqual(10, version)
        tables = {
            row["name"]
            for row in self.store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("topic_materials", tables)
        self.assertIn("subject_profiles", tables)
        self.assertEqual(0, self.store.study_topic("legacy-topic")["material_count"])
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_materials_attach_to_topics_survive_restart_and_leave_with_delete(
        self,
    ) -> None:
        skill_id = self._topic()
        added = self.store.add_topic_materials(
            skill_id,
            [
                {
                    "kind": "example_problem",
                    "body": (
                        "A 10 ft ladder slides down a wall.\r\n"
                        "(a) Find dx/dt when x = 6.\r\n(b) Find the rate of the angle."
                    ),
                    "solution": "dx/dt = 3/4 ft/s",
                    "source_label": "  HW 4   #7 ",
                },
                {"body": "Water drains from a cone at 2 L/min.", "solution": ""},
            ],
        )
        self.assertEqual(2, len(added))
        self.assertEqual("HW 4 #7", added[0]["source_label"])
        self.assertIn("(b) Find the rate", added[0]["body"])
        self.assertNotIn("\r", added[0]["body"])
        self.assertIsNone(added[1]["solution"])
        self.assertEqual("example_problem", added[1]["kind"])
        self.assertEqual("", added[1]["source_label"])
        self.assertEqual(2, self.store.study_topic(skill_id)["material_count"])
        self.assertEqual(2, self.store.study_topics()[0]["material_count"])
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.store.add_topic_materials(skill_id, [])
        with self.assertRaisesRegex(ValueError, "kind"):
            self.store.add_topic_materials(skill_id, [{"kind": "video", "body": "x"}])
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.add_topic_materials("missing-topic", [{"body": "x"}])

        self.store.record_event(self._learner_event(skill_id), now=NOW)
        self.store.restart_study_topic(skill_id)
        self.assertEqual(2, len(self.store.topic_materials(skill_id)))

        deleted = self.store.delete_topic_material(added[1]["id"])
        self.assertEqual(added[1]["id"], deleted["id"])
        self.assertEqual(1, len(self.store.topic_materials(skill_id)))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.delete_topic_material(added[1]["id"])

        export = self.store.export_json(self.root / "export.json")
        document = json.loads(export.read_text(encoding="utf-8"))
        self.assertEqual(1, len(document["topic_materials"]))

        self.store.delete_study_topic(skill_id)
        self.assertEqual([], self.store.topic_materials(skill_id))
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )

    def test_material_limits_are_enforced(self) -> None:
        skill_id = self._topic()
        with self.assertRaisesRegex(ValueError, "4000 characters"):
            self.store.add_topic_materials(skill_id, [{"body": "x" * 4_001}])
        with self.assertRaisesRegex(ValueError, "120 characters"):
            self.store.add_topic_materials(
                skill_id, [{"body": "x", "source_label": "y" * 121}]
            )
        self.store.add_topic_materials(
            skill_id, [{"body": f"Problem {index}"} for index in range(40)]
        )
        with self.assertRaisesRegex(ValueError, "at most 40"):
            self.store.add_topic_materials(skill_id, [{"body": "one more"}])

    def test_subject_profiles_match_subjects_case_insensitively(self) -> None:
        self._topic("Limits")
        saved = self.store.set_subject_profile(
            "calculus i",
            "Exams are five free-response problems; no calculator; show all work.",
        )
        self.assertEqual("Calculus I", saved["subject"])
        self.assertEqual({"Calculus I": saved["profile"]}, self.store.subject_profiles())
        self.assertEqual(saved["profile"], self.store.subject_profile("CALCULUS I"))
        self.store.set_subject_profile("Calculus I", "Updated.")
        self.assertEqual({"Calculus I": "Updated."}, self.store.subject_profiles())
        self.store.set_subject_profile("Calculus I", "   ")
        self.assertEqual({}, self.store.subject_profiles())
        self.assertEqual("", self.store.subject_profile("Calculus I"))
        with self.assertRaisesRegex(ValueError, "2000 characters"):
            self.store.set_subject_profile("Calculus I", "p" * 2_001)

    def test_generation_context_adapts_tier_to_recent_outcomes(self) -> None:
        skill_id = self._topic()
        fresh = self.store.generation_context(skill_id)
        self.assertEqual("standard", fresh["difficulty_tier"])
        self.assertEqual([], fresh["recent_outcomes"])
        self.assertEqual("not started", fresh["mastery_label"])
        self.assertEqual([], fresh["misconceptions"])

        for index in range(3):
            self.store.record_event(
                self._learner_event(
                    skill_id,
                    outcome=Outcome.INCORRECT,
                    misconception="Forgot the chain rule on the inner function.",
                ),
                now=NOW + timedelta(minutes=index),
            )
        context = self.store.generation_context(skill_id)
        self.assertEqual("foundational", context["difficulty_tier"])
        self.assertEqual(["incorrect"] * 3, context["recent_outcomes"])
        self.assertEqual(3, context["attempts_count"])
        self.assertEqual(
            ["Forgot the chain rule on the inner function."],
            context["misconceptions"],
        )

    def test_difficulty_tier_rules(self) -> None:
        self.assertEqual("standard", difficulty_tier(0.0, 0, 0, []))
        self.assertEqual("standard", difficulty_tier(0.0, 0, 2, ["incorrect"]))
        self.assertEqual(
            "foundational", difficulty_tier(10.0, 0, 3, ["incorrect"] * 3)
        )
        self.assertEqual(
            "standard",
            difficulty_tier(50.0, 2, 4, ["correct", "incorrect", "correct", "correct"]),
        )
        self.assertEqual(
            "challenging",
            difficulty_tier(50.0, 2, 4, ["incorrect", "correct", "correct", "correct"]),
        )
        self.assertEqual(
            "challenging", difficulty_tier(70.0, 3, 6, ["correct", "incorrect"])
        )
        self.assertEqual(
            "standard", difficulty_tier(70.0, 3, 6, ["incorrect", "incorrect"])
        )
        self.assertEqual("synthesis", difficulty_tier(85.0, 5, 10, ["correct"] * 5))
        self.assertEqual(
            "foundational",
            difficulty_tier(30.0, 1, 5, ["correct", "incorrect", "incorrect"]),
        )

    def test_misconceptions_resolve_after_two_independent_correct_answers(
        self,
    ) -> None:
        skill_id = self._topic()

        def unresolved() -> list[tuple[str, int]]:
            return [
                (str(row["description"]), int(row["occurrence_count"]))
                for row in self.store.connection.execute(
                    """SELECT description, occurrence_count FROM misconceptions
                        WHERE skill_id = ? AND resolved_at IS NULL""",
                    (skill_id,),
                )
            ]

        self.store.record_event(
            self._learner_event(
                skill_id,
                outcome=Outcome.INCORRECT,
                misconception="Dropped the negative sign.",
            ),
            now=NOW,
        )
        self.store.record_event(self._learner_event(skill_id), now=NOW + timedelta(days=1))
        self.assertEqual([("Dropped the negative sign.", 1)], unresolved())
        self.store.record_event(self._learner_event(skill_id), now=NOW + timedelta(days=2))
        self.assertEqual([], unresolved())
        self.assertEqual([], self.store.generation_context(skill_id)["misconceptions"])

        self.store.record_event(
            self._learner_event(
                skill_id,
                outcome=Outcome.INCORRECT,
                misconception="Dropped the negative sign.",
            ),
            now=NOW + timedelta(days=3),
        )
        self.assertEqual([("Dropped the negative sign.", 2)], unresolved())



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
