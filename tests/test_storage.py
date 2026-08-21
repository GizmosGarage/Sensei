import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sensei.learning import LearningEvent, Outcome
from sensei.storage import LearningStore, evidence_score, xp_award, xp_level


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
        self.assertEqual(1, version)
        self.assertEqual(17, len(self.store.skill_names()))
        self.store.close()
        self.store = LearningStore(self.database)
        migration_count = self.store.connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]
        self.assertEqual(1, migration_count)

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
        self.assertEqual(17, len(self.store.skill_names()))


if __name__ == "__main__":
    unittest.main()
