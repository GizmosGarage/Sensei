"""Versioned SQLite learning memory, progression rules, and data controls."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sensei.learning import LearningEvent, Outcome


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = REPOSITORY_ROOT / "data" / "sensei.db"
DEFAULT_SKILLS_PATH = REPOSITORY_ROOT / "config" / "skills.json"
SCHEMA_VERSION = 2


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


@dataclass(frozen=True)
class ProgressUpdate:
    attempt_id: int
    xp_awarded: int
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


def evidence_score(event: LearningEvent) -> float:
    raw_score = {
        Outcome.CORRECT: 100.0,
        Outcome.PARTIAL: 55.0,
        Outcome.INCORRECT: 10.0,
    }[event.outcome]
    if event.solution_revealed:
        raw_score = min(raw_score, 45.0)
    elif event.hints_used:
        raw_score *= max(0.55, 1 - 0.12 * min(event.hints_used, 4))
    confidence_adjusted = 50 + (raw_score - 50) * event.confidence
    return round(confidence_adjusted, 2)


def xp_award(event: LearningEvent) -> tuple[int, str]:
    points = 5
    reasons = ["practice effort"]
    if event.outcome is Outcome.CORRECT:
        points += 15
        reasons.append("correct result")
        if event.hints_used == 0 and not event.solution_revealed:
            points += 5
            reasons.append("independent solution")
    elif event.outcome is Outcome.PARTIAL:
        points += 7
        reasons.append("partial progress")
    return points, ", ".join(reasons)


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
        current = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        if current != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema version {current}; expected {SCHEMA_VERSION}."
            )

    def _load_skills(self) -> list[dict[str, Any]]:
        document = json.loads(self.skills_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError("Unsupported skill-catalog schema version.")
        skills = document.get("skills")
        if not isinstance(skills, list) or not skills:
            raise ValueError("The skill catalog must contain at least one skill.")
        ids = {skill["id"] for skill in skills}
        if len(ids) != len(skills):
            raise ValueError("Skill IDs must be unique.")
        for skill in skills:
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
                           id, name, unit, description, prerequisites_json, sort_order
                       ) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           name = excluded.name,
                           unit = excluded.unit,
                           description = excluded.description,
                           prerequisites_json = excluded.prerequisites_json,
                           sort_order = excluded.sort_order""",
                    (
                        skill["id"],
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

        with self.connection:
            misconception_id = self._upsert_misconception(event, timestamp)
            cursor = self.connection.execute(
                """INSERT INTO attempts(
                       skill_id, problem, outcome, outcome_source, reported_outcome,
                       effective_outcome_source, verification_status,
                       verification_kind, verifier_version, verification_submitted,
                       verification_expected, verification_detail,
                       misconception_id, evidence,
                       confidence, hints_used, solution_revealed, tutor_turns, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    misconception_id,
                    event.evidence,
                    event.confidence,
                    event.hints_used,
                    int(event.solution_revealed),
                    event.tutor_turns,
                    timestamp,
                ),
            )
            attempt_id = int(cursor.lastrowid)
            previous = self.connection.execute(
                "SELECT * FROM mastery WHERE skill_id = ?", (event.skill_id,)
            ).fetchone()
            prior_attempts = int(previous["attempts_count"]) if previous else 0
            prior_score = float(previous["mastery_score"]) if previous else 0.0
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
            score = evidence_score(event)
            updated_score = score if prior_attempts == 0 else 0.7 * prior_score + 0.3 * score
            updated_score = round(max(0.0, min(100.0, updated_score)), 2)
            attempts_count = prior_attempts + 1
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
            """SELECT s.id, s.name, s.unit, s.sort_order,
                      COALESCE(m.mastery_score, 0) AS mastery_score,
                      COALESCE(m.attempts_count, 0) AS attempts_count,
                      COALESCE(m.correct_count, 0) AS correct_count,
                      m.next_review_at
               FROM skills s
               LEFT JOIN mastery m ON m.skill_id = s.id
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

    def _practiced_skill_rows(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """SELECT s.id, s.name, m.mastery_score, m.attempts_count,
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
        self, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        rows = self._practiced_skill_rows()
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
