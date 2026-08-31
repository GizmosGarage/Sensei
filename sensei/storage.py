"""Versioned SQLite learning memory, progression rules, and data controls."""

from __future__ import annotations

import json
import hashlib
import math
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Collection, Mapping

from sensei.learning import LearningEvent, Outcome


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = REPOSITORY_ROOT / "data" / "sensei.db"
DEFAULT_SKILLS_PATH = REPOSITORY_ROOT / "config" / "skills.json"
SCHEMA_VERSION = 9
FULL_MASTERY_PRACTICE_ATTEMPTS = 10


MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    description TEXT NOT NULL,
    prerequisites_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS misconceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id),
    normalized_key TEXT NOT NULL,
    description TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (skill_id, normalized_key)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL REFERENCES skills(id),
    problem TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('correct', 'partial', 'incorrect')),
    outcome_source TEXT NOT NULL CHECK (outcome_source IN ('student', 'model')),
    misconception_id INTEGER REFERENCES misconceptions(id),
    evidence TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    hints_used INTEGER NOT NULL CHECK (hints_used >= 0),
    solution_revealed INTEGER NOT NULL CHECK (solution_revealed IN (0, 1)),
    tutor_turns INTEGER NOT NULL CHECK (tutor_turns >= 1),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mastery (
    skill_id TEXT PRIMARY KEY REFERENCES skills(id),
    mastery_score REAL NOT NULL CHECK (mastery_score >= 0 AND mastery_score <= 100),
    attempts_count INTEGER NOT NULL CHECK (attempts_count >= 0),
    correct_count INTEGER NOT NULL CHECK (correct_count >= 0),
    partial_count INTEGER NOT NULL CHECK (partial_count >= 0),
    incorrect_count INTEGER NOT NULL CHECK (incorrect_count >= 0),
    independent_correct_count INTEGER NOT NULL CHECK (independent_correct_count >= 0),
    success_streak INTEGER NOT NULL CHECK (success_streak >= 0),
    last_practiced_at TEXT NOT NULL,
    next_review_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE CASCADE,
    points INTEGER NOT NULL CHECK (points >= 0),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_skill_created
    ON attempts(skill_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mastery_review
    ON mastery(next_review_at);
CREATE INDEX IF NOT EXISTS idx_misconceptions_skill
    ON misconceptions(skill_id, last_seen_at DESC);
"""

MIGRATION_2 = """
ALTER TABLE attempts ADD COLUMN reported_outcome TEXT
    CHECK (reported_outcome IN ('correct', 'partial', 'incorrect'));
ALTER TABLE attempts ADD COLUMN effective_outcome_source TEXT NOT NULL DEFAULT 'reported'
    CHECK (effective_outcome_source IN ('reported', 'verifier'));
ALTER TABLE attempts ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN (
        'unverified', 'verified_correct', 'verified_incorrect', 'inconclusive'
    ));
ALTER TABLE attempts ADD COLUMN verification_kind TEXT
    CHECK (verification_kind IN ('derivative', 'limit', 'antiderivative', 'equivalent'));
ALTER TABLE attempts ADD COLUMN verifier_version TEXT;
ALTER TABLE attempts ADD COLUMN verification_submitted TEXT;
ALTER TABLE attempts ADD COLUMN verification_expected TEXT;
ALTER TABLE attempts ADD COLUMN verification_detail TEXT;
UPDATE attempts SET reported_outcome = outcome WHERE reported_outcome IS NULL;
"""

MIGRATION_3 = """
ALTER TABLE attempts ADD COLUMN quest_id TEXT;
"""

MIGRATION_4 = """
ALTER TABLE skills ADD COLUMN course TEXT NOT NULL DEFAULT 'calculus'
    CHECK (course IN ('precalculus', 'calculus'));
"""

MIGRATION_5 = """
CREATE TABLE skills_v5 (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    description TEXT NOT NULL,
    prerequisites_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    course TEXT NOT NULL CHECK (length(trim(course)) > 0),
    source TEXT NOT NULL DEFAULT 'catalog'
        CHECK (source IN ('catalog', 'learner')),
    created_at TEXT
);
INSERT INTO skills_v5(
    id, name, unit, description, prerequisites_json, sort_order, course,
    source, created_at
)
SELECT id, name, unit, description, prerequisites_json, sort_order, course,
       'catalog', NULL
FROM skills;
DROP TABLE skills;
ALTER TABLE skills_v5 RENAME TO skills;
"""

MIGRATION_7 = """
CREATE TABLE skills_v7 (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    description TEXT NOT NULL,
    prerequisites_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    course TEXT NOT NULL CHECK (length(trim(course)) > 0),
    source TEXT NOT NULL DEFAULT 'catalog'
        CHECK (source IN ('catalog', 'learner')),
    created_at TEXT
);
INSERT INTO skills_v7(
    id, name, unit, description, prerequisites_json, sort_order, course,
    source, created_at
)
SELECT id, name, unit, description, prerequisites_json, sort_order, course,
       source, created_at
FROM skills;
DROP TABLE skills;
ALTER TABLE skills_v7 RENAME TO skills;
"""

MIGRATION_8 = """
CREATE TABLE atlas_folders (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    normalized_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (subject, normalized_name)
);

CREATE TABLE atlas_folder_topics (
    folder_id TEXT NOT NULL REFERENCES atlas_folders(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL UNIQUE REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (folder_id, skill_id)
);

CREATE INDEX idx_atlas_folders_subject_order
    ON atlas_folders(subject, sort_order);
CREATE INDEX idx_atlas_folder_topics_folder
    ON atlas_folder_topics(folder_id);
"""

MIGRATION_9 = """
ALTER TABLE attempts ADD COLUMN mastery_evidence REAL NOT NULL DEFAULT 0
    CHECK (mastery_evidence >= 0 AND mastery_evidence <= 100);

UPDATE attempts
   SET mastery_evidence = ROUND(
       CASE
           WHEN solution_revealed = 1 THEN 0
           ELSE 50 + (
               MAX(
                   0,
                   CASE outcome
                       WHEN 'correct' THEN 100.0
                       WHEN 'partial' THEN 55.0
                       ELSE 0.0
                   END - 15.0 * hints_used
               ) - 50
           ) * confidence
       END,
       2
   );
"""


@dataclass(frozen=True)
class ProgressUpdate:
    attempt_id: int
    xp_awarded: int
    mastery_evidence: float
    total_xp: int
    level: int
    xp_into_level: int
    xp_for_next_level: int
    mastery_score: float
    mastery_label: str
    next_review_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_misconception(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:120] or "unspecified"


def xp_level(total_xp: int) -> tuple[int, int, int]:
    if total_xp < 0:
        raise ValueError("total_xp cannot be negative")
    level = 1
    remaining = total_xp
    required = 100
    while remaining >= required:
        remaining -= required
        level += 1
        required = level * 100
    return level, remaining, required


def mastery_label(score: float, correct_count: int, attempts_count: int) -> str:
    if attempts_count == 0:
        return "not started"
    if score >= 80 and correct_count >= 3:
        return "mastered"
    if score >= 65 and correct_count >= 2:
        return "proficient"
    if score >= 35:
        return "developing"
    return "beginning"


def mastery_score(total_evidence: float, attempts_count: int) -> float:
    """Combine demonstrated accuracy with confidence earned through repetition.

    Evidence is the quality-adjusted result of each attempt. Its running average
    represents accuracy, while the square-root practice factor keeps a small
    sample from claiming full mastery. Ten attempts provide full sample confidence.
    """

    if attempts_count < 0:
        raise ValueError("attempts_count cannot be negative")
    if attempts_count == 0:
        return 0.0
    bounded_average = max(0.0, min(100.0, total_evidence / attempts_count))
    practice_factor = math.sqrt(
        min(1.0, attempts_count / FULL_MASTERY_PRACTICE_ATTEMPTS)
    )
    return round(bounded_average * practice_factor, 2)


def evidence_score(event: LearningEvent) -> float:
    if event.solution_revealed:
        # Seeing the final answer is useful for learning, but it is not evidence of
        # mastery on this attempt.
        return 0.0
    raw_score = {
        Outcome.CORRECT: 100.0,
        Outcome.PARTIAL: 55.0,
        Outcome.INCORRECT: 0.0,
    }[event.outcome]
    if event.hints_used:
        raw_score = max(0.0, raw_score - 15.0 * event.hints_used)
    confidence_adjusted = 50 + (raw_score - 50) * event.confidence
    return round(confidence_adjusted, 2)


def xp_award(event: LearningEvent) -> tuple[int, str]:
    if event.solution_revealed:
        return 0, "final answer revealed; no experience reward"

    points = 5
    reasons = ["practice effort"]
    if event.outcome is Outcome.CORRECT:
        points += 20
        reasons.append("correct result")
        if event.hints_used == 0:
            reasons.append("independent solution")
    elif event.outcome is Outcome.PARTIAL:
        points += 7
        reasons.append("partial progress")
    if event.hints_used:
        penalty = min(points, 5 * event.hints_used)
        points -= penalty
        reasons.append(
            f"{event.hints_used} Sensei help step{'s' if event.hints_used != 1 else ''} "
            f"(-{penalty} XP)"
        )
    return points, ", ".join(reasons)


def help_reward_preview(
    hints_used: int, *, solution_revealed: bool
) -> dict[str, int | float]:
    """Return the remaining reward ceiling for a correct dashboard answer."""

    if hints_used < 0:
        raise ValueError("Help-step count cannot be negative.")
    if solution_revealed:
        return {"xp_if_correct": 0, "mastery_evidence_if_correct": 0.0}
    return {
        "xp_if_correct": max(0, 25 - 5 * hints_used),
        "mastery_evidence_if_correct": max(0.0, 100.0 - 15.0 * hints_used),
    }


class LearningStore:
    """Owns one local SQLite database and all learning-state mutations."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        skills_path: Path = DEFAULT_SKILLS_PATH,
    ) -> None:
        self.database_path = database_path.resolve()
        self.skills_path = skills_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA journal_mode = WAL")
            self._migrate()
            self._seed_skills()
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "LearningStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]
            for row in self.connection.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            self.connection.executescript(MIGRATION_1)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(1)
        if 2 not in applied:
            self.connection.executescript(MIGRATION_2)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(2)
        if 3 not in applied:
            self.connection.executescript(MIGRATION_3)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(3)
        if 4 not in applied:
            self.connection.executescript(MIGRATION_4)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(4)
        if 5 not in applied:
            self.connection.commit()
            self.connection.execute("PRAGMA foreign_keys = OFF")
            try:
                self.connection.executescript(MIGRATION_5)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (5, utc_now().isoformat()),
                )
                self.connection.commit()
            finally:
                self.connection.execute("PRAGMA foreign_keys = ON")
            applied.add(5)
        if 6 not in applied:
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (6, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(6)
        if 7 not in applied:
            self.connection.commit()
            self.connection.execute("PRAGMA foreign_keys = OFF")
            try:
                self.connection.executescript(MIGRATION_7)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (7, utc_now().isoformat()),
                )
                self.connection.commit()
            finally:
                self.connection.execute("PRAGMA foreign_keys = ON")
            applied.add(7)
        if 8 not in applied:
            self.connection.executescript(MIGRATION_8)
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (8, utc_now().isoformat()),
            )
            self.connection.commit()
            applied.add(8)
        if 9 not in applied:
            self.connection.executescript(MIGRATION_9)
            self._recalculate_mastery_scores()
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (9, utc_now().isoformat()),
            )
            self.connection.commit()
        current = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        if current != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema version {current}; expected {SCHEMA_VERSION}."
            )

    def _recalculate_mastery_scores(self) -> None:
        """Apply the current scoring rule to migrated attempt history."""

        totals = {
            str(row["skill_id"]): (
                float(row["total_evidence"]),
                int(row["attempts_count"]),
            )
            for row in self.connection.execute(
                """SELECT skill_id, SUM(mastery_evidence) AS total_evidence,
                          COUNT(*) AS attempts_count
                     FROM attempts
                    GROUP BY skill_id"""
            )
        }
        for row in self.connection.execute("SELECT skill_id FROM mastery"):
            total_evidence, attempts_count = totals.get(
                str(row["skill_id"]), (0.0, 0)
            )
            self.connection.execute(
                "UPDATE mastery SET mastery_score = ? WHERE skill_id = ?",
                (mastery_score(total_evidence, attempts_count), row["skill_id"]),
            )

    def _load_skills(self) -> list[dict[str, Any]]:
        document = json.loads(self.skills_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 2:
            raise ValueError("Unsupported skill-catalog schema version.")
        skills = document.get("skills")
        if not isinstance(skills, list) or not skills:
            raise ValueError("The skill catalog must contain at least one skill.")
        ids = {skill["id"] for skill in skills}
        if len(ids) != len(skills):
            raise ValueError("Skill IDs must be unique.")
        for skill in skills:
            if skill.get("course") not in {"precalculus", "calculus"}:
                raise ValueError(
                    f"Skill {skill.get('id')!r} has an invalid course."
                )
            unknown = set(skill["prerequisites"]) - ids
            if unknown:
                raise ValueError(
                    f"Skill {skill['id']} has unknown prerequisites: {sorted(unknown)}"
                )
        return skills

    def _seed_skills(self) -> None:
        with self.connection:
            for sort_order, skill in enumerate(self._load_skills()):
                self.connection.execute(
                    """INSERT INTO skills(
                           id, course, name, unit, description,
                           prerequisites_json, sort_order, source
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, 'catalog')
                       ON CONFLICT(id) DO UPDATE SET
                           course = excluded.course,
                           name = excluded.name,
                           unit = excluded.unit,
                           description = excluded.description,
                           prerequisites_json = excluded.prerequisites_json,
                           sort_order = excluded.sort_order""",
                    (
                        skill["id"],
                        skill["course"],
                        skill["name"],
                        skill["unit"],
                        skill["description"],
                        json.dumps(skill["prerequisites"]),
                        sort_order,
                    ),
                )

    def skill_names(self) -> dict[str, str]:
        rows = self.connection.execute(
            "SELECT id, name FROM skills ORDER BY sort_order"
        )
        return {row["id"]: row["name"] for row in rows}

    @staticmethod
    def _study_text(value: str, field: str, maximum: int) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError(f"{field} is required.")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer.")
        return cleaned

    def create_study_topic(
        self,
        *,
        subject: str,
        topic: str,
        context: str = "",
    ) -> dict[str, Any]:
        """Create or refresh one learner-owned topic in the growing skill atlas."""

        subject = self._study_text(subject, "Subject", 80)
        topic = self._study_text(topic, "Topic", 120)
        context = " ".join(context.split())
        if len(context) > 2_000:
            raise ValueError("Study material must be 2,000 characters or fewer.")
        skill_id = self._study_topic_id(subject, topic)
        timestamp = utc_now().isoformat()
        description = context or "No additional practice instructions were provided."
        sort_order = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM skills"
            ).fetchone()["next_order"]
        )
        with self.connection:
            self.connection.execute(
                """INSERT INTO skills(
                       id, course, name, unit, description, prerequisites_json,
                       sort_order, source, created_at
                   ) VALUES (?, ?, ?, ?, ?, '[]', ?, 'learner', ?)
                   ON CONFLICT(id) DO UPDATE SET
                       course = excluded.course,
                       name = excluded.name,
                       description = excluded.description""",
                (
                    skill_id,
                    subject,
                    topic,
                    f"{subject} questline",
                    description,
                    sort_order,
                    timestamp,
                ),
            )
        return self.study_topic(skill_id)

    @staticmethod
    def _study_topic_id(subject: str, topic: str) -> str:
        identity = f"{subject.casefold()}\0{topic.casefold()}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-")[:40]
        return f"focus-{slug or 'topic'}-{digest}"

    def create_topic_collection(
        self,
        *,
        subject: str,
        folder_name: str,
        topics: Collection[Mapping[str, str]],
    ) -> dict[str, Any]:
        """Atomically add an imported topic set and file it in one Atlas folder."""

        subject = self._study_text(subject, "Subject", 80)
        for row in self.connection.execute("SELECT DISTINCT course FROM skills"):
            existing = str(row["course"])
            if existing.casefold() == subject.casefold():
                subject = existing
                break
        folder_name, normalized_name = self._folder_name(folder_name)
        if not topics:
            raise ValueError("An imported folder must contain at least one topic.")
        if len(topics) > 80:
            raise ValueError("An imported folder cannot contain more than 80 topics.")

        prepared: list[tuple[str, str, str]] = []
        seen_names: set[str] = set()
        for topic in topics:
            name = self._study_text(str(topic.get("name", "")), "Topic", 120)
            description = " ".join(str(topic.get("description", "")).split())
            if not description:
                raise ValueError(f"Imported topic {name!r} needs a practice brief.")
            if len(description) > 2_000:
                raise ValueError("Study material must be 2,000 characters or fewer.")
            if name.casefold() in seen_names:
                raise ValueError(f"Imported topic {name!r} appears more than once.")
            seen_names.add(name.casefold())
            prepared.append((self._study_topic_id(subject, name), name, description))

        duplicate = self.connection.execute(
            """SELECT 1 FROM atlas_folders
                WHERE subject = ? COLLATE NOCASE AND normalized_name = ?""",
            (subject, normalized_name),
        ).fetchone()
        if duplicate is not None:
            raise ValueError(
                f'A folder named “{folder_name}” already exists in {subject}.'
            )

        next_skill_order = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM skills"
            ).fetchone()["next_order"]
        )
        next_folder_order = int(
            self.connection.execute(
                """SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
                     FROM atlas_folders WHERE subject = ? COLLATE NOCASE""",
                (subject,),
            ).fetchone()["next_order"]
        )
        folder_id = f"folder-{uuid.uuid4().hex}"
        timestamp = utc_now().isoformat()
        try:
            with self.connection:
                for offset, (skill_id, name, description) in enumerate(prepared):
                    self.connection.execute(
                        """INSERT INTO skills(
                               id, course, name, unit, description,
                               prerequisites_json, sort_order, source, created_at
                           ) VALUES (?, ?, ?, ?, ?, '[]', ?, 'learner', ?)
                           ON CONFLICT(id) DO UPDATE SET
                               course = excluded.course,
                               name = excluded.name,
                               description = excluded.description""",
                        (
                            skill_id,
                            subject,
                            name,
                            f"{subject} questline",
                            description,
                            next_skill_order + offset,
                            timestamp,
                        ),
                    )
                self.connection.execute(
                    """INSERT INTO atlas_folders(
                           id, subject, name, normalized_name, sort_order,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        folder_id,
                        subject,
                        folder_name,
                        normalized_name,
                        next_folder_order,
                        timestamp,
                        timestamp,
                    ),
                )
                self.connection.executemany(
                    """INSERT INTO atlas_folder_topics(folder_id, skill_id)
                       VALUES (?, ?)
                       ON CONFLICT(skill_id) DO UPDATE SET folder_id = excluded.folder_id""",
                    ((folder_id, skill_id) for skill_id, _, _ in prepared),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("The imported Atlas folder could not be created.") from error

        folder = next(
            item for item in self.topic_folders() if item["id"] == folder_id
        )
        return {
            "folder": folder,
            "topics": [self.study_topic(skill_id) for skill_id, _, _ in prepared],
        }

    def study_topic(self, skill_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT s.id, s.course, s.name, s.unit, s.description,
                      s.source, s.created_at, aft.folder_id
                 FROM skills s
                 LEFT JOIN atlas_folder_topics aft ON aft.skill_id = s.id
                WHERE s.id = ?""",
            (skill_id,),
        ).fetchone()
        if row is None:
            raise ValueError("That study topic does not exist.")
        return dict(row)

    def _atlas_topic_for_progress_change(self, skill_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            """SELECT s.id, s.name, s.source,
                      EXISTS(
                          SELECT 1 FROM attempts a WHERE a.skill_id = s.id
                      ) AS has_attempts
                 FROM skills s
                WHERE s.id = ?""",
            (skill_id,),
        ).fetchone()
        if row is None or (row["source"] != "learner" and not row["has_attempts"]):
            raise ValueError("That Atlas topic does not exist.")
        return row

    def _topic_progress_summary(self, skill_id: str) -> tuple[int, int]:
        row = self.connection.execute(
            """SELECT COUNT(a.id) AS attempts,
                      COALESCE(SUM(x.points), 0) AS xp
                 FROM attempts a
                 LEFT JOIN xp_events x ON x.attempt_id = a.id
                WHERE a.skill_id = ?""",
            (skill_id,),
        ).fetchone()
        return int(row["attempts"]), int(row["xp"])

    def _clear_topic_progress(self, skill_id: str) -> None:
        self.connection.execute(
            """DELETE FROM xp_events
                WHERE attempt_id IN (
                    SELECT id FROM attempts WHERE skill_id = ?
                )""",
            (skill_id,),
        )
        self.connection.execute(
            "DELETE FROM attempts WHERE skill_id = ?", (skill_id,)
        )
        self.connection.execute(
            "DELETE FROM misconceptions WHERE skill_id = ?", (skill_id,)
        )
        self.connection.execute(
            "DELETE FROM mastery WHERE skill_id = ?", (skill_id,)
        )

    def restart_study_topic(self, skill_id: str) -> dict[str, Any]:
        """Reset one Atlas topic's progress while preserving the topic itself."""

        row = self._atlas_topic_for_progress_change(skill_id)
        deleted_attempts, removed_xp = self._topic_progress_summary(skill_id)
        with self.connection:
            self._clear_topic_progress(skill_id)
        return {
            "skill_id": str(row["id"]),
            "topic": str(row["name"]),
            "deleted_attempts": deleted_attempts,
            "removed_xp": removed_xp,
        }

    def delete_study_topic(self, skill_id: str) -> dict[str, Any]:
        """Permanently remove one Atlas topic and all learner data tied to it."""

        row = self._atlas_topic_for_progress_change(skill_id)
        deleted_attempts, removed_xp = self._topic_progress_summary(skill_id)
        with self.connection:
            self._clear_topic_progress(skill_id)
            if row["source"] == "learner":
                self.connection.execute("DELETE FROM skills WHERE id = ?", (skill_id,))

        return {
            "skill_id": str(row["id"]),
            "topic": str(row["name"]),
            "deleted_attempts": deleted_attempts,
            "removed_xp": removed_xp,
        }

    def _upsert_misconception(
        self, event: LearningEvent, timestamp: str
    ) -> int | None:
        if not event.misconception:
            return None
        key = normalize_misconception(event.misconception)
        self.connection.execute(
            """INSERT INTO misconceptions(
                   skill_id, normalized_key, description, first_seen_at, last_seen_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(skill_id, normalized_key) DO UPDATE SET
                   description = excluded.description,
                   occurrence_count = occurrence_count + 1,
                   last_seen_at = excluded.last_seen_at,
                   resolved_at = NULL""",
            (event.skill_id, key, event.misconception, timestamp, timestamp),
        )
        row = self.connection.execute(
            "SELECT id FROM misconceptions WHERE skill_id = ? AND normalized_key = ?",
            (event.skill_id, key),
        ).fetchone()
        return int(row["id"])

    @staticmethod
    def _review_date(
        event: LearningEvent, now: datetime, success_streak: int
    ) -> datetime:
        if (
            event.outcome is Outcome.CORRECT
            and event.hints_used == 0
            and not event.solution_revealed
        ):
            days = min(32, 2 ** min(success_streak, 5))
        elif event.outcome is Outcome.CORRECT:
            days = 2
        else:
            days = 1
        return now + timedelta(days=days)

    def record_event(
        self, event: LearningEvent, *, now: datetime | None = None
    ) -> ProgressUpdate:
        now = now or utc_now()
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        timestamp = now.astimezone(timezone.utc).isoformat()
        score = evidence_score(event)

        with self.connection:
            misconception_id = self._upsert_misconception(event, timestamp)
            cursor = self.connection.execute(
                """INSERT INTO attempts(
                       skill_id, problem, outcome, outcome_source, reported_outcome,
                       effective_outcome_source, verification_status,
                       verification_kind, verifier_version, verification_submitted,
                       verification_expected, verification_detail,
                       quest_id, misconception_id, evidence,
                       confidence, hints_used, solution_revealed, tutor_turns,
                       created_at, mastery_evidence
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   )""",
                (
                    event.skill_id,
                    event.problem,
                    event.outcome.value,
                    event.outcome_source,
                    (event.reported_outcome or event.outcome).value,
                    event.effective_outcome_source,
                    event.verification_status,
                    event.verification_kind,
                    event.verifier_version,
                    event.verification_submitted,
                    event.verification_expected,
                    event.verification_detail,
                    event.quest_id,
                    misconception_id,
                    event.evidence,
                    event.confidence,
                    event.hints_used,
                    int(event.solution_revealed),
                    event.tutor_turns,
                    timestamp,
                    score,
                ),
            )
            attempt_id = int(cursor.lastrowid)
            previous = self.connection.execute(
                "SELECT * FROM mastery WHERE skill_id = ?", (event.skill_id,)
            ).fetchone()
            prior_attempts = int(previous["attempts_count"]) if previous else 0
            prior_correct = int(previous["correct_count"]) if previous else 0
            prior_partial = int(previous["partial_count"]) if previous else 0
            prior_incorrect = int(previous["incorrect_count"]) if previous else 0
            prior_independent = (
                int(previous["independent_correct_count"]) if previous else 0
            )
            prior_streak = int(previous["success_streak"]) if previous else 0

            independent_correct = (
                event.outcome is Outcome.CORRECT
                and event.hints_used == 0
                and not event.solution_revealed
            )
            attempts_count = prior_attempts + 1
            total_evidence = float(
                self.connection.execute(
                    """SELECT COALESCE(SUM(mastery_evidence), 0) AS total
                         FROM attempts WHERE skill_id = ?""",
                    (event.skill_id,),
                ).fetchone()["total"]
            )
            updated_score = mastery_score(total_evidence, attempts_count)
            correct_count = prior_correct + int(event.outcome is Outcome.CORRECT)
            partial_count = prior_partial + int(event.outcome is Outcome.PARTIAL)
            incorrect_count = prior_incorrect + int(event.outcome is Outcome.INCORRECT)
            independent_count = prior_independent + int(independent_correct)
            success_streak = prior_streak + 1 if independent_correct else 0
            review_at = self._review_date(event, now, success_streak)
            review_timestamp = review_at.astimezone(timezone.utc).isoformat()

            self.connection.execute(
                """INSERT INTO mastery(
                       skill_id, mastery_score, attempts_count, correct_count,
                       partial_count, incorrect_count, independent_correct_count,
                       success_streak, last_practiced_at, next_review_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                       mastery_score = excluded.mastery_score,
                       attempts_count = excluded.attempts_count,
                       correct_count = excluded.correct_count,
                       partial_count = excluded.partial_count,
                       incorrect_count = excluded.incorrect_count,
                       independent_correct_count = excluded.independent_correct_count,
                       success_streak = excluded.success_streak,
                       last_practiced_at = excluded.last_practiced_at,
                       next_review_at = excluded.next_review_at,
                       updated_at = excluded.updated_at""",
                (
                    event.skill_id,
                    updated_score,
                    attempts_count,
                    correct_count,
                    partial_count,
                    incorrect_count,
                    independent_count,
                    success_streak,
                    timestamp,
                    review_timestamp,
                    timestamp,
                ),
            )
            points, reason = xp_award(event)
            self.connection.execute(
                "INSERT INTO xp_events(attempt_id, points, reason, created_at) "
                "VALUES (?, ?, ?, ?)",
                (attempt_id, points, reason, timestamp),
            )
            total_xp = int(
                self.connection.execute(
                    "SELECT COALESCE(SUM(points), 0) AS total FROM xp_events"
                ).fetchone()["total"]
            )

        level, into_level, for_next = xp_level(total_xp)
        return ProgressUpdate(
            attempt_id=attempt_id,
            xp_awarded=points,
            mastery_evidence=score,
            total_xp=total_xp,
            level=level,
            xp_into_level=into_level,
            xp_for_next_level=for_next,
            mastery_score=updated_score,
            mastery_label=mastery_label(
                updated_score, correct_count, attempts_count
            ),
            next_review_at=review_timestamp,
        )

    def profile(self) -> dict[str, Any]:
        total_xp = int(
            self.connection.execute(
                "SELECT COALESCE(SUM(points), 0) AS total FROM xp_events"
            ).fetchone()["total"]
        )
        attempts = int(
            self.connection.execute(
                "SELECT COUNT(*) AS count FROM attempts"
            ).fetchone()["count"]
        )
        rows = list(self.connection.execute("SELECT * FROM mastery"))
        mastered = sum(
            mastery_label(
                row["mastery_score"], row["correct_count"], row["attempts_count"]
            )
            == "mastered"
            for row in rows
        )
        level, into_level, for_next = xp_level(total_xp)
        return {
            "total_xp": total_xp,
            "level": level,
            "xp_into_level": into_level,
            "xp_for_next_level": for_next,
            "attempts": attempts,
            "skills_practiced": len(rows),
            "skills_mastered": mastered,
        }

    def skill_progress(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT s.id, s.course, s.name, s.unit, s.description,
                      s.source, s.created_at, s.sort_order,
                      aft.folder_id,
                      COALESCE(m.mastery_score, 0) AS mastery_score,
                      COALESCE(m.attempts_count, 0) AS attempts_count,
                      COALESCE(m.correct_count, 0) AS correct_count,
                      m.next_review_at
               FROM skills s
               LEFT JOIN mastery m ON m.skill_id = s.id
               LEFT JOIN atlas_folder_topics aft ON aft.skill_id = s.id
               ORDER BY s.sort_order"""
        )
        return [
            {
                **dict(row),
                "mastery_label": mastery_label(
                    row["mastery_score"], row["correct_count"], row["attempts_count"]
                ),
            }
            for row in rows
        ]

    def study_topics(self) -> list[dict[str, Any]]:
        """Return the learner-built atlas plus any legacy skill already practiced."""

        return [
            skill
            for skill in self.skill_progress()
            if skill["source"] == "learner" or skill["attempts_count"] > 0
        ]

    @staticmethod
    def _folder_name(value: str) -> tuple[str, str]:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Folder name cannot be empty.")
        if len(name) > 80:
            raise ValueError("Folder name must be 80 characters or fewer.")
        return name, name.casefold()

    def _atlas_subject(self, value: str) -> str:
        subject = self._study_text(value, "Subject", 80)
        rows = self.connection.execute(
            """SELECT DISTINCT s.course
                 FROM skills s
                WHERE s.source = 'learner'
                   OR EXISTS(SELECT 1 FROM attempts a WHERE a.skill_id = s.id)"""
        )
        for row in rows:
            course = str(row["course"])
            if course.casefold() == subject.casefold():
                return course
        raise ValueError("A folder's subject must already exist in the Atlas.")

    def topic_folders(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT f.id, f.subject, f.name, f.sort_order,
                      f.created_at, f.updated_at,
                      COUNT(aft.skill_id) AS topic_count
                 FROM atlas_folders f
                 LEFT JOIN atlas_folder_topics aft ON aft.folder_id = f.id
                GROUP BY f.id
                ORDER BY f.subject COLLATE NOCASE, f.sort_order, f.name COLLATE NOCASE"""
        )
        folders = [dict(row) for row in rows]
        topic_rows = self.connection.execute(
            """SELECT folder_id, skill_id
                 FROM atlas_folder_topics
                ORDER BY rowid"""
        )
        topic_ids: dict[str, list[str]] = {}
        for row in topic_rows:
            topic_ids.setdefault(str(row["folder_id"]), []).append(str(row["skill_id"]))
        for folder in folders:
            folder["topic_ids"] = topic_ids.get(str(folder["id"]), [])
        return folders

    def _validate_folder_topics(self, subject: str, skill_ids: Collection[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(skill_ids))
        if len(unique_ids) > 250:
            raise ValueError("A folder cannot contain more than 250 topics.")
        if not unique_ids:
            return []
        placeholders = ",".join("?" for _ in unique_ids)
        rows = list(
            self.connection.execute(
                f"""SELECT s.id, s.course, s.source,
                           EXISTS(SELECT 1 FROM attempts a WHERE a.skill_id = s.id) AS practiced
                      FROM skills s
                     WHERE s.id IN ({placeholders})""",
                unique_ids,
            )
        )
        by_id = {str(row["id"]): row for row in rows}
        if len(by_id) != len(unique_ids):
            raise ValueError("One or more selected topics do not exist in the Atlas.")
        for skill_id in unique_ids:
            row = by_id[skill_id]
            if row["source"] != "learner" and not row["practiced"]:
                raise ValueError("Only topics in the learner's Atlas can be filed.")
            if str(row["course"]).casefold() != subject.casefold():
                raise ValueError("Every topic in a folder must belong to its subject.")
        return unique_ids

    def create_topic_folder(
        self, *, subject: str, name: str, skill_ids: Collection[str]
    ) -> dict[str, Any]:
        subject = self._atlas_subject(subject)
        name, normalized_name = self._folder_name(name)
        topic_ids = self._validate_folder_topics(subject, skill_ids)
        folder_id = f"folder-{uuid.uuid4().hex}"
        timestamp = utc_now().isoformat()
        sort_order = int(
            self.connection.execute(
                """SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
                     FROM atlas_folders WHERE subject = ? COLLATE NOCASE""",
                (subject,),
            ).fetchone()["next_order"]
        )
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO atlas_folders(
                           id, subject, name, normalized_name, sort_order, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (folder_id, subject, name, normalized_name, sort_order, timestamp, timestamp),
                )
                self.connection.executemany(
                    """INSERT INTO atlas_folder_topics(folder_id, skill_id)
                       VALUES (?, ?)
                       ON CONFLICT(skill_id) DO UPDATE SET folder_id = excluded.folder_id""",
                    ((folder_id, skill_id) for skill_id in topic_ids),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f'A folder named “{name}” already exists in {subject}.') from error
        return next(folder for folder in self.topic_folders() if folder["id"] == folder_id)

    def update_topic_folder(
        self, folder_id: str, *, name: str, skill_ids: Collection[str]
    ) -> dict[str, Any]:
        folder = self.connection.execute(
            "SELECT id, subject FROM atlas_folders WHERE id = ?", (folder_id,)
        ).fetchone()
        if folder is None:
            raise ValueError("That Atlas folder does not exist.")
        name, normalized_name = self._folder_name(name)
        topic_ids = self._validate_folder_topics(str(folder["subject"]), skill_ids)
        try:
            with self.connection:
                self.connection.execute(
                    """UPDATE atlas_folders
                          SET name = ?, normalized_name = ?, updated_at = ?
                        WHERE id = ?""",
                    (name, normalized_name, utc_now().isoformat(), folder_id),
                )
                self.connection.execute(
                    "DELETE FROM atlas_folder_topics WHERE folder_id = ?", (folder_id,)
                )
                self.connection.executemany(
                    """INSERT INTO atlas_folder_topics(folder_id, skill_id)
                       VALUES (?, ?)
                       ON CONFLICT(skill_id) DO UPDATE SET folder_id = excluded.folder_id""",
                    ((folder_id, skill_id) for skill_id in topic_ids),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f'A folder named “{name}” already exists in {folder["subject"]}.'
            ) from error
        return next(folder for folder in self.topic_folders() if folder["id"] == folder_id)

    def delete_topic_folder(self, folder_id: str) -> dict[str, Any]:
        folder = self.connection.execute(
            """SELECT f.id, f.subject, f.name, COUNT(aft.skill_id) AS topic_count
                 FROM atlas_folders f
                 LEFT JOIN atlas_folder_topics aft ON aft.folder_id = f.id
                WHERE f.id = ?
                GROUP BY f.id""",
            (folder_id,),
        ).fetchone()
        if folder is None:
            raise ValueError("That Atlas folder does not exist.")
        with self.connection:
            self.connection.execute("DELETE FROM atlas_folders WHERE id = ?", (folder_id,))
        return dict(folder)

    def _practiced_skill_rows(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """SELECT s.id, s.course, s.name,
                          m.mastery_score, m.attempts_count,
                          m.correct_count, m.next_review_at,
                          (SELECT mc.description
                             FROM misconceptions mc
                            WHERE mc.skill_id = s.id AND mc.resolved_at IS NULL
                            ORDER BY mc.occurrence_count DESC, mc.last_seen_at DESC
                            LIMIT 1) AS misconception
                     FROM mastery m
                     JOIN skills s ON s.id = m.skill_id
                    ORDER BY m.mastery_score ASC, m.next_review_at ASC"""
            )
        )

    def tutor_context(self, limit: int = 5) -> str | None:
        if limit < 1:
            raise ValueError("Tutor-context limit must be positive.")
        rows = self._practiced_skill_rows()[:limit]
        if not rows:
            return None
        lines = []
        for row in rows:
            label = mastery_label(
                row["mastery_score"], row["correct_count"], row["attempts_count"]
            )
            line = f"- {row['name']}: {label} ({row['mastery_score']:.0f}/100)"
            if row["misconception"]:
                line += f"; watch for: {row['misconception']}"
            lines.append(line)
        return "\n".join(lines)

    def review_recommendation(
        self,
        *,
        now: datetime | None = None,
        skill_ids: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        rows = self._practiced_skill_rows()
        if skill_ids is not None:
            allowed = set(skill_ids)
            rows = [row for row in rows if row["id"] in allowed]
        if not rows:
            return None
        now = now or utc_now()
        now_text = now.astimezone(timezone.utc).isoformat()
        rows.sort(
            key=lambda row: (
                0 if row["next_review_at"] <= now_text else 1,
                row["next_review_at"],
                row["mastery_score"],
            )
        )
        row = rows[0]
        result = dict(row)
        result["mastery_label"] = mastery_label(
            row["mastery_score"], row["correct_count"], row["attempts_count"]
        )
        result["due"] = row["next_review_at"] <= now_text
        return result

    def recent_attempts(self, limit: int = 6) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50:
            raise ValueError("Recent-attempt limit must be from 1 to 50.")
        rows = self.connection.execute(
            """SELECT a.id, a.problem, a.outcome, a.reported_outcome,
                      a.effective_outcome_source, a.verification_status,
                      a.quest_id, a.created_at, s.id AS skill_id, s.course AS course,
                      s.name AS skill_name
                 FROM attempts a
                 JOIN skills s ON s.id = a.skill_id
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in rows]

    def recent_problems(self, skill_id: str, limit: int = 8) -> tuple[str, ...]:
        """Return recent issued-and-recorded problems for duplicate avoidance."""

        if not 1 <= limit <= 50:
            raise ValueError("Recent-problem limit must be from 1 to 50.")
        rows = self.connection.execute(
            """SELECT problem
                 FROM attempts
                WHERE skill_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?""",
            (skill_id, limit),
        )
        return tuple(str(row["problem"]) for row in rows)

    def export_json(self, path: Path) -> Path:
        destination = path.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Export destination already exists: {destination}")

        def rows(query: str) -> list[dict[str, Any]]:
            return [dict(row) for row in self.connection.execute(query)]

        document = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": utc_now().isoformat(),
            "profile": self.profile(),
            "skills": self.skill_progress(),
            "topic_folders": self.topic_folders(),
            "attempts": rows("SELECT * FROM attempts ORDER BY id"),
            "misconceptions": rows("SELECT * FROM misconceptions ORDER BY id"),
            "xp_events": rows("SELECT * FROM xp_events ORDER BY id"),
        }
        destination.write_text(
            json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return destination

    def backup(self, path: Path) -> Path:
        destination = path.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Backup destination already exists: {destination}")
        backup_connection = sqlite3.connect(destination)
        try:
            self.connection.backup(backup_connection)
        finally:
            backup_connection.close()
        return destination

    def delete_learning_data(self) -> int:
        deleted = int(
            self.connection.execute(
                "SELECT COUNT(*) AS count FROM attempts"
            ).fetchone()["count"]
        )
        with self.connection:
            self.connection.execute("DELETE FROM xp_events")
            self.connection.execute("DELETE FROM attempts")
            self.connection.execute("DELETE FROM misconceptions")
            self.connection.execute("DELETE FROM mastery")
        return deleted


def timestamped_data_path(directory: Path, prefix: str, suffix: str) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    return directory / f"{prefix}-{stamp}{suffix}"
