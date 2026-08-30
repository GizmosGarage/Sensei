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
        self.assertEqual((2, 0, 200), xp_level(100))

    def test_low_confidence_pulls_mastery_evidence_toward_neutral(self) -> None:
        self.assertEqual(100.0, evidence_score(event()))
        self.assertEqual(50.0, evidence_score(event(confidence=0.0)))
        self.assertEqual(
            45.0, evidence_score(event(solution_revealed=True, confidence=1.0))
        )


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
        self.assertEqual(7, version)
        self.assertEqual(37, len(self.store.skill_names()))
        self.store.close()
        self.store = LearningStore(self.database)
        migration_count = self.store.connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]
        self.assertEqual(7, migration_count)

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
        self.assertEqual(7, version)
        self.assertIsNone(attempt["quest_id"])

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
        self.assertEqual(7, version)

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
        self.assertEqual(7, version)

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

    def test_delete_learner_topic_removes_every_related_learning_record(self) -> None:
        topic = self.store.create_study_topic(
            subject="Chemistry",
            topic="Stoichiometry",
            context="Mole ratios and limiting reagents",
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
        self.assertEqual(
            [], list(self.store.connection.execute("PRAGMA foreign_key_check"))
        )
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.study_topic(topic["id"])

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
        self.assertEqual(100.0, first.mastery_score)
        self.assertEqual("developing", first.mastery_label)
        self.assertEqual("2026-08-23", first.next_review_at[:10])

        self.store.record_event(event(), now=NOW)
        third = self.store.record_event(event(), now=NOW)
        self.assertEqual("mastered", third.mastery_label)
        self.assertEqual("2026-08-29", third.next_review_at[:10])
        profile = self.store.profile()
        self.assertEqual(75, profile["total_xp"])
        self.assertEqual(1, profile["skills_mastered"])

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
