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
DEFAULT_DATABASE_PATH = REPOSITORY_ROOT / "data" / "study.db"
LESSON_STATUS_COLUMNS = """
    CASE
        WHEN tl.id IS NULL THEN 'none'
        WHEN tl.completed_at IS NOT NULL THEN 'complete'
        ELSE 'in_progress'
    END AS lesson_status,
    COALESCE(tl.current_step, 0) AS lesson_step,
    COALESCE(tl.step_count, 0) AS lesson_step_count
"""
FULL_MASTERY_PRACTICE_ATTEMPTS = 10
MATERIAL_KINDS = ("example_problem", "worked_example", "notes")
MAX_TOPIC_MATERIALS = 40
MAX_MATERIAL_CHARACTERS = 4_000
MAX_SOURCE_LABEL_CHARACTERS = 120
MAX_SUBJECT_PROFILE_CHARACTERS = 2_000
MAX_PLAN_TOPICS = 40
MAX_STUDY_CONTEXT_CHARACTERS = 2_000
DIFFICULTY_TIERS = ("foundational", "standard", "challenging", "synthesis")
DIFFICULTY_TIER_GUIDANCE = {
    "foundational": (
        "a one-concept problem that isolates this skill; shorter than a full "
        "exam problem"
    ),
    "standard": (
        "a typical exam problem for this class, matching the class examples' "
        "length, depth, and method"
    ),
    "challenging": (
        "harder than a typical exam problem: an extra step, less scaffolding, or "
        "a less common form, still in this class's style"
    ),
    "synthesis": (
        "the hardest problem this class would ask: combine this skill with its "
        "prerequisites, usually as a multi-part problem"
    ),
}


@dataclass(frozen=True)
class ProgressUpdate:
    attempt_id: int
    mastery_evidence: float
    mastery_score: float
    mastery_label: str
    next_review_at: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_misconception(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:120] or "unspecified"


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


def difficulty_tier(
    score: float,
    correct_count: int,
    attempts_count: int,
    recent_outcomes: Collection[str],
) -> str:
    """Choose how demanding the next generated problem should be.

    The base tier follows the mastery label. Two consecutive wrong answers step
    the tier down; three consecutive correct answers step it up. A learner with
    no history starts at the class's normal exam level rather than an easy one.
    """

    label = mastery_label(score, correct_count, attempts_count)
    if label == "beginning" and attempts_count >= 3:
        index = 0
    elif label == "proficient":
        index = 2
    elif label == "mastered":
        index = 3
    else:
        index = 1
    outcomes = [str(outcome) for outcome in recent_outcomes]
    if len(outcomes) >= 2 and all(outcome == "incorrect" for outcome in outcomes[-2:]):
        index -= 1
    elif len(outcomes) >= 3 and all(outcome == "correct" for outcome in outcomes[-3:]):
        index += 1
    return DIFFICULTY_TIERS[max(0, min(len(DIFFICULTY_TIERS) - 1, index))]


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


class LearningStore:
    """Owns one local SQLite database and all learning-state mutations."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
    ) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA journal_mode = WAL")
            if self.connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_migrations'").fetchone():
                raise RuntimeError("This is an old Sensei database. Remove it to start fresh with study guides.")
            self.connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "LearningStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()


    @staticmethod
    def _study_text(value: str, field: str, maximum: int) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError(f"{field} is required.")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer.")
        return cleaned

    @staticmethod
    def _study_topic_id(subject: str, topic: str, guide_id: str) -> str:
        identity = f"{guide_id}\0{subject.casefold()}\0{topic.casefold()}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-")[:40]
        return f"focus-{slug or 'topic'}-{digest}"

    def _upsert_study_topic(
        self,
        *,
        subject: str,
        topic: str,
        context: str,
        guide_id: str,
        unit: str | None = None,
    ) -> tuple[str, bool]:
        """Insert or refresh one learner topic inside the caller's transaction."""

        subject = self._study_text(subject, "Subject", 80)
        topic = self._study_text(topic, "Topic", 120)
        context = " ".join(context.split())
        if len(context) > MAX_STUDY_CONTEXT_CHARACTERS:
            raise ValueError("Study material must be 2,000 characters or fewer.")
        skill_id = self._study_topic_id(subject, topic, guide_id)
        existing = self.connection.execute(
            "SELECT 1 FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        description = context or "No additional practice instructions were provided."
        sort_order = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM skills"
            ).fetchone()["next_order"]
        )
        self.connection.execute(
            """INSERT INTO skills(
                   id, course, name, unit, description,
                   sort_order, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   course = excluded.course,
                   name = excluded.name,
                   unit = excluded.unit,
                   description = excluded.description""",
            (
                skill_id,
                subject,
                topic,
                unit or subject,
                description,
                sort_order,
                utc_now().isoformat(),
            ),
        )
        return skill_id, existing is None


    def study_topic(self, skill_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            f"""SELECT s.id, s.course, s.name, s.unit, s.description,
                      s.created_at, aft.folder_id,
                      (SELECT COUNT(*) FROM topic_materials tm
                        WHERE tm.skill_id = s.id) AS material_count,
                      {LESSON_STATUS_COLUMNS}
                 FROM skills s
                 LEFT JOIN guide_concepts aft ON aft.skill_id = s.id
                 LEFT JOIN topic_lessons tl ON tl.skill_id = s.id
                WHERE s.id = ?""",
            (skill_id,),
        ).fetchone()
        if row is None:
            raise ValueError("That study topic does not exist.")
        return dict(row)


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
            if success_streak >= 2:
                # Two independent correct answers in a row are the evidence that
                # this topic's recorded mistakes no longer need targeting.
                self.connection.execute(
                    """UPDATE misconceptions SET resolved_at = ?
                        WHERE skill_id = ? AND resolved_at IS NULL""",
                    (timestamp, event.skill_id),
                )
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
        return ProgressUpdate(
            attempt_id=attempt_id,
            mastery_evidence=score,
            mastery_score=updated_score,
            mastery_label=mastery_label(
                updated_score, correct_count, attempts_count
            ),
            next_review_at=review_timestamp,
        )


    def skill_progress(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            f"""SELECT s.id, s.course, s.name, s.unit, s.description,
                      s.created_at, s.sort_order,
                      aft.folder_id,
                      (SELECT COUNT(*) FROM topic_materials tm
                        WHERE tm.skill_id = s.id) AS material_count,
                      COALESCE(m.mastery_score, 0) AS mastery_score,
                      COALESCE(m.attempts_count, 0) AS attempts_count,
                      COALESCE(m.correct_count, 0) AS correct_count,
                      m.next_review_at,
                      {LESSON_STATUS_COLUMNS}
               FROM skills s
               LEFT JOIN mastery m ON m.skill_id = s.id
               LEFT JOIN guide_concepts aft ON aft.skill_id = s.id
               LEFT JOIN topic_lessons tl ON tl.skill_id = s.id
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
        """Return the concepts extracted from saved guides."""
        return self.skill_progress()

    @staticmethod
    def _folder_name(value: str) -> tuple[str, str]:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Folder name cannot be empty.")
        if len(name) > 80:
            raise ValueError("Folder name must be 80 characters or fewer.")
        return name, name.casefold()


    def topic_folders(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT f.id, f.subject, f.name, f.sort_order,
                      f.created_at, f.updated_at,
                      COUNT(aft.skill_id) AS topic_count
                 FROM study_guides f
                 LEFT JOIN guide_concepts aft ON aft.folder_id = f.id
                GROUP BY f.id
                ORDER BY f.subject COLLATE NOCASE, f.sort_order, f.name COLLATE NOCASE"""
        )
        folders = [dict(row) for row in rows]
        topic_rows = self.connection.execute(
            """SELECT folder_id, skill_id
                 FROM guide_concepts
                ORDER BY rowid"""
        )
        topic_ids: dict[str, list[str]] = {}
        for row in topic_rows:
            topic_ids.setdefault(str(row["folder_id"]), []).append(str(row["skill_id"]))
        for folder in folders:
            folder["topic_ids"] = topic_ids.get(str(folder["id"]), [])
        return folders


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

    @staticmethod
    def _material_text(
        value: object, field: str, maximum: int, *, required: bool
    ) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text.")
        lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        cleaned = "\n".join(line.rstrip() for line in lines).strip()
        if required and not cleaned:
            raise ValueError(f"{field} is required.")
        if len(cleaned) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer.")
        return cleaned

    def topic_materials(self, skill_id: str) -> list[dict[str, Any]]:
        """Return one topic's class material, oldest first."""

        rows = self.connection.execute(
            """SELECT id, skill_id, kind, body, solution, source_label, created_at
                 FROM topic_materials
                WHERE skill_id = ?
                ORDER BY created_at, rowid""",
            (skill_id,),
        )
        return [dict(row) for row in rows]

    def _prepared_materials(
        self, materials: Collection[Mapping[str, object]]
    ) -> list[tuple[str, str, str | None, str]]:
        prepared: list[tuple[str, str, str | None, str]] = []
        for material in materials:
            if not isinstance(material, Mapping):
                raise ValueError("Each class material must be an object.")
            kind = str(material.get("kind") or "example_problem")
            if kind not in MATERIAL_KINDS:
                raise ValueError(
                    "Material kind must be example_problem, worked_example, or notes."
                )
            body = self._material_text(
                material.get("body"),
                "Material text",
                MAX_MATERIAL_CHARACTERS,
                required=True,
            )
            solution = self._material_text(
                material.get("solution"),
                "Material solution",
                MAX_MATERIAL_CHARACTERS,
                required=False,
            ) or None
            source_label = " ".join(str(material.get("source_label") or "").split())
            if len(source_label) > MAX_SOURCE_LABEL_CHARACTERS:
                raise ValueError(
                    f"Source label must be {MAX_SOURCE_LABEL_CHARACTERS} "
                    "characters or fewer."
                )
            prepared.append((kind, body, solution, source_label))
        return prepared

    def _insert_materials(
        self,
        skill_id: str,
        prepared: Collection[tuple[str, str, str | None, str]],
        *,
        merge: bool,
    ) -> set[str]:
        """Insert prepared rows inside the caller's transaction.

        With ``merge`` the call skips bodies already stored for the topic and
        stops quietly at the per-topic limit; otherwise the limit is an error.
        """

        existing_rows = self.connection.execute(
            "SELECT body FROM topic_materials WHERE skill_id = ?", (skill_id,)
        ).fetchall()
        existing_bodies = {
            " ".join(str(row["body"]).split()).casefold() for row in existing_rows
        }
        if not merge and len(existing_rows) + len(prepared) > MAX_TOPIC_MATERIALS:
            raise ValueError(
                f"A topic can keep at most {MAX_TOPIC_MATERIALS} class materials."
            )
        timestamp = utc_now().isoformat()
        created: set[str] = set()
        count = len(existing_rows)
        for kind, body, solution, source_label in prepared:
            fingerprint = " ".join(body.split()).casefold()
            if merge and (fingerprint in existing_bodies or count >= MAX_TOPIC_MATERIALS):
                continue
            material_id = f"material-{uuid.uuid4().hex}"
            self.connection.execute(
                """INSERT INTO topic_materials(
                       id, skill_id, kind, body, solution, source_label,
                       created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    material_id,
                    skill_id,
                    kind,
                    body,
                    solution,
                    source_label,
                    timestamp,
                ),
            )
            created.add(material_id)
            existing_bodies.add(fingerprint)
            count += 1
        return created


    def subject_profiles(self) -> dict[str, str]:
        rows = self.connection.execute(
            "SELECT subject, profile FROM subject_profiles "
            "ORDER BY subject COLLATE NOCASE"
        )
        return {str(row["subject"]): str(row["profile"]) for row in rows}

    def subject_profile(self, subject: str) -> str:
        row = self.connection.execute(
            "SELECT profile FROM subject_profiles WHERE subject = ? COLLATE NOCASE",
            (subject,),
        ).fetchone()
        return str(row["profile"]) if row else ""


    def _write_subject_profile(self, subject: str, profile: str) -> None:
        existing = self.connection.execute(
            "SELECT subject FROM subject_profiles WHERE subject = ? COLLATE NOCASE",
            (subject,),
        ).fetchone()
        if existing is not None:
            self.connection.execute(
                "DELETE FROM subject_profiles WHERE subject = ?",
                (existing["subject"],),
            )
        if profile:
            self.connection.execute(
                """INSERT INTO subject_profiles(subject, profile, updated_at)
                   VALUES (?, ?, ?)""",
                (subject, profile, utc_now().isoformat()),
            )

    def _canonical_subject(self, subject: str) -> str:
        for row in self.connection.execute("SELECT DISTINCT course FROM skills"):
            if str(row["course"]).casefold() == subject.casefold():
                return str(row["course"])
        return subject

    def create_study_plan(
        self,
        *,
        subject: str,
        set_name: str,
        course_profile: str = "",
        topics: Collection[Mapping[str, object]],
    ) -> dict[str, Any]:
        """Atomically turn an analyzed study guide into a folder of ready topics.

        Re-importing the same guide merges: the folder is reused, topics are
        refreshed in place, and example problems already stored are skipped.
        """

        subject = self._canonical_subject(self._study_text(subject, "Subject", 80))
        folder_name, normalized_name = self._folder_name(set_name)
        profile = self._material_text(
            course_profile,
            "Course profile",
            MAX_SUBJECT_PROFILE_CHARACTERS,
            required=False,
        )
        topic_list = list(topics)
        if not 1 <= len(topic_list) <= MAX_PLAN_TOPICS:
            raise ValueError(f"A study plan needs from 1 to {MAX_PLAN_TOPICS} topics.")
        prepared: list[tuple[str, str, str, list[tuple[str, str, str | None, str]]]] = []
        seen: set[str] = set()
        for raw_topic in topic_list:
            if not isinstance(raw_topic, Mapping):
                raise ValueError("Each study-plan topic must be an object.")
            name = self._study_text(str(raw_topic.get("name") or ""), "Topic", 120)
            if name.casefold() in seen:
                raise ValueError(f"Topic {name!r} appears more than once in the plan.")
            seen.add(name.casefold())
            description = " ".join(str(raw_topic.get("description") or "").split())
            if len(description) > MAX_STUDY_CONTEXT_CHARACTERS:
                raise ValueError("Study material must be 2,000 characters or fewer.")
            section = " ".join(str(raw_topic.get("section") or "").split())[:40]
            raw_materials = raw_topic.get("materials") or []
            if not isinstance(raw_materials, (list, tuple)):
                raise ValueError("Study-plan materials must be a list.")
            prepared.append(
                (name, description, section, self._prepared_materials(raw_materials))
            )

        timestamp = utc_now().isoformat()
        created_topics = updated_topics = added_materials = 0
        profile_saved = False
        skill_ids: list[str] = []
        try:
            with self.connection:
                folder = self.connection.execute(
                    """SELECT id FROM study_guides
                        WHERE subject = ? COLLATE NOCASE AND normalized_name = ?""",
                    (subject, normalized_name),
                ).fetchone()
                if folder is None:
                    folder_id = f"folder-{uuid.uuid4().hex}"
                    sort_order = int(
                        self.connection.execute(
                            """SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
                                 FROM study_guides WHERE subject = ? COLLATE NOCASE""",
                            (subject,),
                        ).fetchone()["next_order"]
                    )
                    self.connection.execute(
                        """INSERT INTO study_guides(
                               id, subject, name, normalized_name, sort_order,
                               created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            folder_id,
                            subject,
                            folder_name,
                            normalized_name,
                            sort_order,
                            timestamp,
                            timestamp,
                        ),
                    )
                else:
                    folder_id = str(folder["id"])
                    self.connection.execute(
                        "UPDATE study_guides SET updated_at = ? WHERE id = ?",
                        (timestamp, folder_id),
                    )
                for name, description, section, materials in prepared:
                    skill_id, created = self._upsert_study_topic(
                        subject=subject,
                        topic=name,
                        context=description,
                        guide_id=folder_id,
                        unit=(f"Section {section}" if section else None),
                    )
                    created_topics += int(created)
                    updated_topics += int(not created)
                    self.connection.execute(
                        """INSERT INTO guide_concepts(folder_id, skill_id)
                           VALUES (?, ?)
                           ON CONFLICT(skill_id) DO UPDATE SET
                               folder_id = excluded.folder_id""",
                        (folder_id, skill_id),
                    )
                    added_materials += len(
                        self._insert_materials(skill_id, materials, merge=True)
                    )
                    skill_ids.append(skill_id)
                if profile and not self.subject_profile(subject):
                    self._write_subject_profile(subject, profile)
                    profile_saved = True
        except sqlite3.IntegrityError as error:
            raise ValueError("The study plan could not be saved.") from error
        folder_document = next(
            item for item in self.topic_folders() if item["id"] == folder_id
        )
        return {
            "folder": folder_document,
            "topics": [self.study_topic(skill_id) for skill_id in skill_ids],
            "created_topics": created_topics,
            "updated_topics": updated_topics,
            "added_materials": added_materials,
            "profile_saved": profile_saved,
        }

    # Guided lessons

    def _lesson_row(self, skill_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM topic_lessons WHERE skill_id = ?", (skill_id,)
        ).fetchone()

    @staticmethod
    def _lesson_progress_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {
                "status": "none",
                "current_step": 0,
                "step_count": 0,
                "completed_at": None,
            }
        return {
            "status": "complete" if row["completed_at"] else "in_progress",
            "current_step": int(row["current_step"]),
            "step_count": int(row["step_count"]),
            "completed_at": row["completed_at"],
        }


    def lesson_for_topic(self, skill_id: str) -> dict[str, Any] | None:
        """Return the stored lesson document and its progress, or None."""

        row = self._lesson_row(skill_id)
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "skill_id": str(row["skill_id"]),
            "document": json.loads(str(row["document_json"])),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **self._lesson_progress_dict(row),
        }

    def save_lesson(
        self,
        skill_id: str,
        lesson_id: str,
        document: Mapping[str, Any],
        step_count: int,
    ) -> dict[str, Any]:
        """Store a validated lesson, replacing earlier lesson progress."""

        self.study_topic(skill_id)
        if int(step_count) < 1:
            raise ValueError("A lesson needs at least one step.")
        timestamp = utc_now().isoformat()
        with self.connection:
            self.connection.execute(
                """INSERT INTO topic_lessons(
                       id, skill_id, document_json, step_count, current_step,
                       completed_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                       document_json = excluded.document_json,
                       step_count = excluded.step_count,
                       current_step = 0,
                       completed_at = NULL,
                       updated_at = excluded.updated_at""",
                (
                    lesson_id,
                    skill_id,
                    json.dumps(dict(document), ensure_ascii=False),
                    int(step_count),
                    timestamp,
                    timestamp,
                ),
            )
        record = self.lesson_for_topic(skill_id)
        assert record is not None
        return record

    def advance_lesson(
        self, skill_id: str, step_index: int, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Advance the current lesson step without changing mastery evidence."""

        now = now or utc_now()
        timestamp = now.astimezone(timezone.utc).isoformat()
        with self.connection:
            row = self._lesson_row(skill_id)
            if row is None:
                raise ValueError("Start the lesson before checking a step.")
            current = int(row["current_step"])
            step_count = int(row["step_count"])
            if int(step_index) == current and current < step_count:
                next_step = current + 1
                completed_at = row["completed_at"]
                if next_step >= step_count:
                    completed_at = completed_at or timestamp
                self.connection.execute(
                    """UPDATE topic_lessons
                          SET current_step = ?, completed_at = ?,
                              updated_at = ?
                        WHERE id = ?""",
                    (next_step, completed_at, timestamp, row["id"]),
                )
                row = self._lesson_row(skill_id)
        return self._lesson_progress_dict(row)


    def generation_context(self, skill_id: str) -> dict[str, Any]:
        """Summarize one topic's evidence so practice generation can adapt."""

        mastery = self.connection.execute(
            """SELECT mastery_score, attempts_count, correct_count, success_streak
                 FROM mastery WHERE skill_id = ?""",
            (skill_id,),
        ).fetchone()
        score = float(mastery["mastery_score"]) if mastery else 0.0
        attempts = int(mastery["attempts_count"]) if mastery else 0
        correct = int(mastery["correct_count"]) if mastery else 0
        streak = int(mastery["success_streak"]) if mastery else 0
        recent = [
            str(row["outcome"])
            for row in self.connection.execute(
                """SELECT outcome FROM attempts
                    WHERE skill_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5""",
                (skill_id,),
            )
        ]
        recent.reverse()
        latest_support = self.connection.execute(
            """SELECT hints_used, solution_revealed FROM attempts
               WHERE skill_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (skill_id,),
        ).fetchone()
        misconceptions = [
            str(row["description"])
            for row in self.connection.execute(
                """SELECT description FROM misconceptions
                    WHERE skill_id = ? AND resolved_at IS NULL
                    ORDER BY occurrence_count DESC, last_seen_at DESC
                    LIMIT 3""",
                (skill_id,),
            )
        ]
        return {
            "mastery_score": score,
            "mastery_label": mastery_label(score, correct, attempts),
            "attempts_count": attempts,
            "success_streak": streak,
            "recent_outcomes": recent,
            "last_attempt_supported": bool(latest_support and (
                latest_support["hints_used"] or latest_support["solution_revealed"]
            )),
            "misconceptions": misconceptions,
            "difficulty_tier": difficulty_tier(score, correct, attempts, recent),
        }
