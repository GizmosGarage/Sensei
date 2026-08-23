"""Curated, verifier-backed review quests and deterministic selection rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from sensei.storage import (
    DEFAULT_SKILLS_PATH,
    REPOSITORY_ROOT,
    LearningStore,
)
from sensei.verification import (
    CalculusVerifier,
    VerificationKind,
    VerificationResult,
)


DEFAULT_QUESTS_PATH = REPOSITORY_ROOT / "config" / "quests.json"
QUEST_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
QUEST_FIELDS = {
    "id",
    "skill_id",
    "title",
    "prompt",
    "sample_answer",
    "verification",
}
VERIFICATION_FIELDS = {
    VerificationKind.DERIVATIVE: {"kind", "expression", "variable"},
    VerificationKind.LIMIT: {
        "kind",
        "expression",
        "variable",
        "point",
        "direction",
    },
    VerificationKind.ANTIDERIVATIVE: {"kind", "integrand", "variable"},
    VerificationKind.EQUIVALENT: {"kind", "reference", "variable"},
}


class QuestCatalogError(ValueError):
    """Raised when a curated quest cannot satisfy the catalog contract."""


@dataclass(frozen=True)
class QuestTemplate:
    id: str
    skill_id: str
    title: str
    prompt: str
    sample_answer: str
    verification: Mapping[str, str]

    @property
    def kind(self) -> VerificationKind:
        return VerificationKind(self.verification["kind"])

    def check(
        self,
        answer: str,
        verifier: CalculusVerifier,
    ) -> VerificationResult:
        if not answer.strip():
            raise ValueError("Enter an answer after /answer.")
        variable = self.verification["variable"]
        if self.kind is VerificationKind.DERIVATIVE:
            return verifier.derivative(
                self.verification["expression"],
                answer,
                variable=variable,
            )
        if self.kind is VerificationKind.LIMIT:
            return verifier.limit(
                self.verification["expression"],
                answer,
                variable=variable,
                point=self.verification["point"],
                direction=self.verification["direction"],
            )
        if self.kind is VerificationKind.ANTIDERIVATIVE:
            return verifier.antiderivative(
                self.verification["integrand"],
                answer,
                variable=variable,
            )
        return verifier.equivalent(
            self.verification["reference"],
            answer,
            variable=variable,
        )

    def public_dict(self, *, skill_name: str, course: str) -> dict[str, str]:
        """Return only fields safe to expose before a student answers."""

        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "skill_name": skill_name,
            "course": course,
            "title": self.title,
            "prompt": self.prompt,
            "check_kind": self.kind.value,
            "answer_command": "/answer YOUR_EXPRESSION",
        }


@dataclass(frozen=True)
class QuestRecommendation:
    quest: QuestTemplate
    skill_name: str
    course: str
    due: bool
    reason: str
    mastery_score: float
    mastery_label: str
    next_review_at: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.quest.public_dict(
                skill_name=self.skill_name,
                course=self.course,
            ),
            "due": self.due,
            "reason": self.reason,
            "mastery_score": self.mastery_score,
            "mastery_label": self.mastery_label,
            "next_review_at": self.next_review_at,
        }


def _nonempty_text(document: Mapping[str, object], field: str, limit: int) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise QuestCatalogError(f"Quest {field} must be non-empty text.")
    value = value.strip()
    if len(value) > limit:
        raise QuestCatalogError(f"Quest {field} exceeds {limit} characters.")
    return value


def _load_skill_catalog(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 2:
        raise QuestCatalogError("Unsupported skill-catalog schema version.")
    names = {skill["id"]: skill["name"] for skill in document["skills"]}
    courses = {skill["id"]: skill["course"] for skill in document["skills"]}
    return names, courses


def _parse_quest(
    document: object,
    *,
    skill_names: Mapping[str, str],
) -> QuestTemplate:
    if not isinstance(document, dict) or set(document) != QUEST_FIELDS:
        raise QuestCatalogError(
            f"Quest fields must be exactly {sorted(QUEST_FIELDS)}."
        )
    quest_id = _nonempty_text(document, "id", 80)
    if not QUEST_ID_PATTERN.fullmatch(quest_id):
        raise QuestCatalogError(f"Invalid quest ID: {quest_id!r}.")
    skill_id = _nonempty_text(document, "skill_id", 80)
    if skill_id not in skill_names:
        raise QuestCatalogError(f"Quest {quest_id} has unknown skill {skill_id!r}.")

    raw_verification = document["verification"]
    if not isinstance(raw_verification, dict):
        raise QuestCatalogError(f"Quest {quest_id} verification must be an object.")
    try:
        kind = VerificationKind(raw_verification.get("kind"))
    except (TypeError, ValueError) as error:
        raise QuestCatalogError(
            f"Quest {quest_id} has an unsupported verification kind."
        ) from error
    expected_fields = VERIFICATION_FIELDS[kind]
    if set(raw_verification) != expected_fields:
        raise QuestCatalogError(
            f"Quest {quest_id} verification fields must be exactly "
            f"{sorted(expected_fields)}."
        )
    verification: dict[str, str] = {}
    for field in expected_fields:
        verification[field] = _nonempty_text(raw_verification, field, 500)
    if kind is VerificationKind.LIMIT and verification["direction"] not in {
        "both",
        "left",
        "right",
    }:
        raise QuestCatalogError(f"Quest {quest_id} has an invalid limit direction.")

    return QuestTemplate(
        id=quest_id,
        skill_id=skill_id,
        title=_nonempty_text(document, "title", 100),
        prompt=_nonempty_text(document, "prompt", 500),
        sample_answer=_nonempty_text(document, "sample_answer", 500),
        verification=verification,
    )


class QuestDeck:
    """Loads curated quests and selects the next scheduled challenge."""

    def __init__(
        self,
        quests: list[QuestTemplate],
        skill_names: Mapping[str, str],
        skill_courses: Mapping[str, str],
    ) -> None:
        if not quests:
            raise QuestCatalogError("The quest catalog must contain at least one quest.")
        ids = {quest.id for quest in quests}
        if len(ids) != len(quests):
            raise QuestCatalogError("Quest IDs must be unique.")
        self.quests = tuple(quests)
        self.skill_names = dict(skill_names)
        self.skill_courses = dict(skill_courses)
        self.by_id = {quest.id: quest for quest in self.quests}
        self.by_skill: dict[str, tuple[QuestTemplate, ...]] = {}
        for skill_id in self.skill_names:
            matching = tuple(quest for quest in self.quests if quest.skill_id == skill_id)
            if matching:
                self.by_skill[skill_id] = matching

    @classmethod
    def load(
        cls,
        path: Path = DEFAULT_QUESTS_PATH,
        *,
        skills_path: Path = DEFAULT_SKILLS_PATH,
    ) -> "QuestDeck":
        skill_names, skill_courses = _load_skill_catalog(skills_path.resolve())
        document = json.loads(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "quests",
        }:
            raise QuestCatalogError("Invalid quest-catalog document shape.")
        if document["schema_version"] != 1:
            raise QuestCatalogError("Unsupported quest-catalog schema version.")
        raw_quests = document["quests"]
        if not isinstance(raw_quests, list):
            raise QuestCatalogError("Quest catalog must contain a quest list.")
        quests = [
            _parse_quest(item, skill_names=skill_names) for item in raw_quests
        ]
        return cls(quests, skill_names, skill_courses)

    @property
    def eligible_skill_ids(self) -> frozenset[str]:
        return frozenset(self.by_skill)

    def recommend(
        self,
        store: LearningStore,
        *,
        now: datetime | None = None,
        course: str | None = None,
    ) -> QuestRecommendation:
        if course not in {None, "precalculus", "calculus"}:
            raise ValueError("Course must be precalculus or calculus.")
        eligible = {
            skill_id
            for skill_id in self.eligible_skill_ids
            if course is None or self.skill_courses[skill_id] == course
        }
        review = store.review_recommendation(
            now=now,
            skill_ids=eligible,
        )
        if review is None:
            starting_skill = (
                "precalc_exponent_properties"
                if course == "precalculus"
                else "calculus_foundations"
            )
            quest = self.by_skill.get(starting_skill, self.quests)[0]
            return QuestRecommendation(
                quest=quest,
                skill_name=self.skill_names[quest.skill_id],
                course=self.skill_courses[quest.skill_id],
                due=True,
                reason="Begin your path with a foundation quest.",
                mastery_score=0.0,
                mastery_label="not started",
                next_review_at=None,
            )

        quests = self.by_skill[str(review["id"])]
        quest = quests[int(review["attempts_count"]) % len(quests)]
        due = bool(review["due"])
        reason = (
            "Scheduled review is due now."
            if due
            else "This is the next verifier-backed skill in your review queue."
        )
        return QuestRecommendation(
            quest=quest,
            skill_name=str(review["name"]),
            course=str(review["course"]),
            due=due,
            reason=reason,
            mastery_score=float(review["mastery_score"]),
            mastery_label=str(review["mastery_label"]),
            next_review_at=str(review["next_review_at"]),
        )

    def public_quests(self) -> list[dict[str, str]]:
        return [
            quest.public_dict(
                skill_name=self.skill_names[quest.skill_id],
                course=self.skill_courses[quest.skill_id],
            )
            for quest in self.quests
        ]

    def get(self, quest_id: str) -> QuestTemplate:
        try:
            return self.by_id[quest_id]
        except KeyError as error:
            raise ValueError(f"Unknown quest ID: {quest_id!r}.") from error
