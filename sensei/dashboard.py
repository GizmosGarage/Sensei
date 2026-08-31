"""Loopback-only browser dashboard with local learning memory and hosted inference."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from collections import deque
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Collection
from urllib.parse import urlsplit

from sensei.errorlog import DEFAULT_ERROR_LOG_PATH, ErrorRecorder, error_reference
from sensei.generation import GENERATED_SKILL_IDS, GeneratedQuestFactory
from sensei.imports import (
    MAX_PDF_BYTES,
    PDFCurriculumScanner,
)
from sensei.learning import LearningEvent, Outcome
from sensei.practice import (
    AdaptiveQuest,
    AdaptiveQuestFactory,
    PracticeGenerationError,
    adaptive_quest_fingerprint,
)
from sensei.providers import (
    APISettings,
    DEFAULT_API_BASE_URL,
    DEFAULT_API_MODEL,
    ResponsesAPIProvider,
    api_settings_from_environment,
)
from sensei.quests import DEFAULT_QUESTS_PATH, QuestDeck, QuestTemplate
from sensei.storage import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SKILLS_PATH,
    LearningStore,
    help_reward_preview,
    utc_now,
)
from sensei.verification import (
    CalculusVerifier,
    MathInputError,
    VerificationResult,
    VerificationStatus,
    math_expression_latex,
)


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_REQUEST_BYTES = 4_096
MAX_PDF_REQUEST_BYTES = (MAX_PDF_BYTES * 4 // 3) + 16_384
ATTEMPT_TOKEN_LIFETIME_SECONDS = 15 * 60
CHALLENGE_TOKEN_LIFETIME_SECONDS = 60 * 60
ADAPTIVE_PROMPT_HISTORY = 8
ADAPTIVE_DISTINCT_ATTEMPTS = 3
WEB_DIRECTORY = Path(__file__).resolve().parent / "web"
KATEX_DIRECTORY = WEB_DIRECTORY / "vendor" / "katex"
PracticeQuest = QuestTemplate | AdaptiveQuest
ASSETS = {
    "/": (WEB_DIRECTORY / "index.html", "text/html; charset=utf-8"),
    "/assets/app.js": (
        WEB_DIRECTORY / "app.js",
        "text/javascript; charset=utf-8",
    ),
    "/assets/styles.css": (
        WEB_DIRECTORY / "styles.css",
        "text/css; charset=utf-8",
    ),
}
for katex_asset in KATEX_DIRECTORY.rglob("*"):
    if not katex_asset.is_file():
        continue
    content_type = {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".woff2": "font/woff2",
    }.get(katex_asset.suffix, "text/plain; charset=utf-8")
    relative_asset = katex_asset.relative_to(KATEX_DIRECTORY).as_posix()
    ASSETS[f"/assets/vendor/katex/{relative_asset}"] = (
        katex_asset,
        content_type,
    )

SCANNER_MODEL_ENVIRONMENT = "SENSEI_PDF_SCANNER_MODEL"
MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}")


def model_name(value: object, *, fallback: str) -> str:
    """Validate a request-selected provider model without constraining vendors."""

    selected = str(value or fallback).strip()
    if not MODEL_NAME_PATTERN.fullmatch(selected):
        raise ValueError(
            "Model names may contain letters, numbers, dots, dashes, underscores, "
            "colons, and slashes (120 characters maximum)."
        )
    return selected


@dataclass(frozen=True)
class HostedModelRouter:
    """Builds isolated practice and PDF-scanning clients from shared credentials."""

    settings: APISettings
    default_scanner_model: str

    @property
    def default_practice_model(self) -> str:
        return self.settings.model

    def practice_factory(self, requested_model: object) -> AdaptiveQuestFactory:
        selected = model_name(requested_model, fallback=self.default_practice_model)
        return AdaptiveQuestFactory(
            ResponsesAPIProvider(
                self.settings.api_key,
                selected,
                base_url=self.settings.base_url,
                max_output_tokens=1_536,
                json_mode=True,
            )
        )

    def curriculum_scanner(self, requested_model: object) -> PDFCurriculumScanner:
        selected = model_name(requested_model, fallback=self.default_scanner_model)
        return PDFCurriculumScanner(
            ResponsesAPIProvider(
                self.settings.api_key,
                selected,
                base_url=self.settings.base_url,
                timeout_seconds=300,
                max_output_tokens=5_000,
                json_mode=True,
            )
        )


def rank_name(level: int) -> str:
    if level >= 10:
        return "Grand Sensei"
    if level >= 7:
        return "Realm Scholar"
    if level >= 4:
        return "Dojo Adept"
    if level >= 2:
        return "Quest Initiate"
    return "Dojo Novice"


def _answer_latex(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return math_expression_latex(value)
    except MathInputError:
        return None


def verification_document(result: VerificationResult) -> dict[str, str | None]:
    return {
        "kind": result.kind.value,
        "status": result.status.value,
        "submitted": result.submitted,
        "submitted_latex": _answer_latex(result.submitted),
        "expected": result.expected,
        "expected_latex": _answer_latex(result.expected),
        "detail": result.detail,
        "verifier_version": result.verifier_version,
    }


@dataclass(frozen=True)
class PendingAttempt:
    quest: PracticeQuest
    result: VerificationResult
    hints_used: int
    solution_revealed: bool
    issued_at: float


class PendingAttemptStore:
    """Keeps checked browser attempts one-time and process-local until recorded."""

    def __init__(self) -> None:
        self._attempts: dict[str, PendingAttempt] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        quest: PracticeQuest,
        result: VerificationResult,
        *,
        hints_used: int = 0,
        solution_revealed: bool = False,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._attempts[token] = PendingAttempt(
                quest,
                result,
                hints_used,
                solution_revealed,
                now,
            )
        return token

    def consume(self, token: str) -> PendingAttempt:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            try:
                return self._attempts.pop(token)
            except KeyError as error:
                raise ValueError(
                    "This checked attempt is missing, expired, or already recorded."
                ) from error

    def discard_skill(self, skill_id: str) -> None:
        """Forget every checked, unrecorded attempt for one deleted topic."""

        with self._lock:
            tokens = [
                token
                for token, attempt in self._attempts.items()
                if attempt.quest.skill_id == skill_id
            ]
            for token in tokens:
                del self._attempts[token]

    def _prune(self, now: float) -> None:
        expired = [
            token
            for token, attempt in self._attempts.items()
            if now - attempt.issued_at > ATTEMPT_TOKEN_LIFETIME_SECONDS
        ]
        for token in expired:
            del self._attempts[token]


def quest_help_steps(quest: PracticeQuest) -> tuple[str, ...]:
    """Build the private, ordered help sequence for one generated problem."""

    if isinstance(quest, AdaptiveQuest):
        steps = quest.help_steps
        if quest.answer_type == "multiple_choice":
            index = ord(quest.answer) - ord("A")
            final = f"Final answer: {quest.answer}. {quest.options[index]}"
        else:
            final = f"Final answer: \\({math_expression_latex(quest.answer)}\\)"
        return (*steps, final)

    first_moves = {
        "derivative": (
            "Identify the outermost operation, then apply its derivative rule before "
            "simplifying."
        ),
        "limit": (
            "Try direct substitution first. If it is indeterminate, simplify the "
            "expression before evaluating the limit again."
        ),
        "antiderivative": (
            "Choose the matching antiderivative rule term by term, then include the "
            "constant of integration."
        ),
        "equivalent": (
            "Rewrite the expression into a common form and simplify one operation at "
            "a time."
        ),
    }
    first = first_moves.get(
        quest.kind.value,
        "Identify the rule that matches the requested operation and apply it first.",
    )
    return first, f"Final answer: \\({math_expression_latex(quest.sample_answer)}\\)"


@dataclass(frozen=True)
class HelpReveal:
    step: str
    step_number: int
    total_steps: int
    hints_used: int
    final_answer: bool


@dataclass
class PendingChallenge:
    quest: PracticeQuest
    issued_at: float
    help_used: int = 0


class ChallengeStore:
    """Keeps generated answer targets server-side and avoids immediate repeats."""

    def __init__(
        self,
        factory: GeneratedQuestFactory | None = None,
        adaptive_factory: AdaptiveQuestFactory | None = None,
    ) -> None:
        self.factory = factory or GeneratedQuestFactory()
        self.adaptive_factory = adaptive_factory
        self._challenges: dict[str, PendingChallenge] = {}
        self._last_prompts: dict[str, str] = {}
        self._adaptive_prompts: dict[str, deque[str]] = {}
        self._adaptive_fingerprints: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    def issue(self, skill_id: str) -> tuple[str, QuestTemplate]:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            last_prompt = self._last_prompts.get(skill_id)
            quest = self.factory.generate(skill_id)
            for _ in range(19):
                if quest.prompt != last_prompt:
                    break
                quest = self.factory.generate(skill_id)
            if quest.prompt == last_prompt:
                raise RuntimeError("A distinct question could not be generated.")
            token = secrets.token_urlsafe(32)
            self._challenges[token] = PendingChallenge(quest, now)
            self._last_prompts[skill_id] = quest.prompt
            return token, quest

    def issue_adaptive(
        self,
        skill: dict[str, Any],
        *,
        avoid_prompts: Collection[str] = (),
        adaptive_factory: AdaptiveQuestFactory | None = None,
    ) -> tuple[str, AdaptiveQuest]:
        factory = adaptive_factory or self.adaptive_factory
        if factory is None:
            raise RuntimeError(
                "Adaptive generation is unavailable. Restart the dashboard with a "
                "valid hosted LLM API connection."
            )
        skill_id = str(skill["id"])
        for _ in range(ADAPTIVE_DISTINCT_ATTEMPTS):
            with self._lock:
                session_recent = tuple(self._adaptive_prompts.get(skill_id, ()))
                session_fingerprints = tuple(
                    self._adaptive_fingerprints.get(skill_id, ())
                )
            recent = tuple(dict.fromkeys((*avoid_prompts, *session_recent)))[
                -ADAPTIVE_PROMPT_HISTORY:
            ]
            quest = factory.generate(
                skill,
                avoid_prompts=recent,
                avoid_fingerprints=session_fingerprints,
            )
            now = time.monotonic()
            with self._lock:
                self._prune(now)
                history = self._adaptive_prompts.setdefault(
                    skill_id,
                    deque(maxlen=ADAPTIVE_PROMPT_HISTORY),
                )
                fingerprint_history = self._adaptive_fingerprints.setdefault(
                    skill_id,
                    deque(maxlen=ADAPTIVE_PROMPT_HISTORY),
                )
                fingerprint = adaptive_quest_fingerprint(quest)
                if fingerprint in fingerprint_history:
                    continue
                token = secrets.token_urlsafe(32)
                self._challenges[token] = PendingChallenge(quest, now)
                self._last_prompts[skill_id] = quest.prompt
                history.append(quest.prompt)
                fingerprint_history.append(fingerprint)
                return token, quest
        raise RuntimeError(
            "Sensei could not produce a distinct new encounter for this topic."
        )

    def get(self, token: str) -> PracticeQuest:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            try:
                return self._challenges[token].quest
            except KeyError as error:
                raise ValueError(
                    "This generated question is missing or expired. Request a new one."
                ) from error

    def reveal_help(self, token: str) -> HelpReveal:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            try:
                challenge = self._challenges[token]
            except KeyError as error:
                raise ValueError(
                    "This generated question is missing or expired. Request a new one."
                ) from error
            steps = quest_help_steps(challenge.quest)
            if challenge.help_used >= len(steps):
                raise ValueError("Sensei has already revealed every step for this problem.")
            challenge.help_used += 1
            return HelpReveal(
                step=steps[challenge.help_used - 1],
                step_number=challenge.help_used,
                total_steps=len(steps),
                hints_used=challenge.help_used,
                final_answer=challenge.help_used == len(steps),
            )

    def attempt_context(self, token: str) -> tuple[PracticeQuest, int, bool]:
        """Return server-authoritative help use when the learner checks an answer."""

        now = time.monotonic()
        with self._lock:
            self._prune(now)
            try:
                challenge = self._challenges[token]
            except KeyError as error:
                raise ValueError(
                    "This generated question is missing or expired. Request a new one."
                ) from error
            solution_revealed = challenge.help_used >= len(
                quest_help_steps(challenge.quest)
            )
            return challenge.quest, challenge.help_used, solution_revealed

    def discard_skill(self, skill_id: str) -> None:
        """Forget generated questions and duplicate history for one deleted topic."""

        with self._lock:
            tokens = [
                token
                for token, challenge in self._challenges.items()
                if challenge.quest.skill_id == skill_id
            ]
            for token in tokens:
                del self._challenges[token]
            self._last_prompts.pop(skill_id, None)
            self._adaptive_prompts.pop(skill_id, None)
            self._adaptive_fingerprints.pop(skill_id, None)

    def _prune(self, now: float) -> None:
        expired = [
            token
            for token, challenge in self._challenges.items()
            if now - challenge.issued_at > CHALLENGE_TOKEN_LIFETIME_SECONDS
        ]
        for token in expired:
            del self._challenges[token]


class DashboardService:
    """Builds a public, answer-key-free snapshot from local application state."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        *,
        skills_path: Path = DEFAULT_SKILLS_PATH,
        quests_path: Path = DEFAULT_QUESTS_PATH,
    ) -> None:
        self.database_path = database_path.resolve()
        self.skills_path = skills_path.resolve()
        self.quests_path = quests_path.resolve()

    def state(self) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            deck = QuestDeck.load(
                self.quests_path,
                skills_path=self.skills_path,
            )
            profile = store.profile()
            profile["rank_name"] = rank_name(int(profile["level"]))
            skills = store.skill_progress()
            study_topics = store.study_topics()
            return {
                "generated_at": utc_now().astimezone(timezone.utc).isoformat(),
                "profile": profile,
                "quests": deck.public_quests(),
                "skills": skills,
                "study_topics": study_topics,
                "topic_folders": store.topic_folders(),
                "recent_attempts": store.recent_attempts(limit=50),
                "catalog": {
                    "quest_count": len(deck.quests),
                    "quest_skill_count": len(deck.eligible_skill_ids),
                    "generated_skill_count": len(GENERATED_SKILL_IDS),
                    "generated_skill_ids": list(GENERATED_SKILL_IDS),
                    "courses": {
                        course: sum(
                            skill["course"] == course for skill in skills
                        )
                        for course in ("precalculus", "calculus")
                    },
                },
                "runtime": {
                    "host": LOOPBACK_HOST,
                    "storage": "Local SQLite",
                    "model_access": "Hosted Responses API",
                    "practice_api_version": 5,
                },
            }

    def create_study_topic(
        self,
        *,
        subject: str,
        topic: str,
        context: str,
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.create_study_topic(
                subject=subject,
                topic=topic,
                context=context,
            )

    def study_topic(self, skill_id: str) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.study_topic(skill_id)

    def delete_study_topic(self, skill_id: str) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.delete_study_topic(skill_id)

    def create_topic_folder(
        self, *, subject: str, name: str, skill_ids: Collection[str]
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.create_topic_folder(
                subject=subject, name=name, skill_ids=skill_ids
            )

    def create_topic_collection(
        self,
        *,
        subject: str,
        folder_name: str,
        topics: Collection[dict[str, str]],
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.create_topic_collection(
                subject=subject,
                folder_name=folder_name,
                topics=topics,
            )

    def update_topic_folder(
        self, folder_id: str, *, name: str, skill_ids: Collection[str]
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.update_topic_folder(
                folder_id, name=name, skill_ids=skill_ids
            )

    def delete_topic_folder(self, folder_id: str) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.delete_topic_folder(folder_id)

    def recent_topic_prompts(self, skill_id: str) -> tuple[str, ...]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.recent_problems(skill_id, limit=ADAPTIVE_PROMPT_HISTORY)

    def public_generated_quest(self, quest: QuestTemplate) -> dict[str, str]:
        deck = QuestDeck.load(
            self.quests_path,
            skills_path=self.skills_path,
        )
        try:
            return quest.public_dict(
                skill_name=deck.skill_names[quest.skill_id],
                course=deck.skill_courses[quest.skill_id],
            )
        except KeyError as error:
            raise ValueError(
                f"Generated question has unknown skill {quest.skill_id!r}."
            ) from error

    @staticmethod
    def public_adaptive_quest(quest: AdaptiveQuest) -> dict[str, Any]:
        return quest.public_dict()

    def check_quest(
        self,
        quest: PracticeQuest,
        answer: str,
    ) -> VerificationResult:
        if isinstance(quest, AdaptiveQuest):
            return quest.check(answer)
        return quest.check(answer, CalculusVerifier())

    def record_attempt(
        self,
        attempt: PendingAttempt,
    ) -> dict[str, Any]:
        result = attempt.result
        if result.status is VerificationStatus.INCONCLUSIVE:
            raise ValueError("An inconclusive check cannot be recorded as a quest result.")
        outcome = (
            Outcome.CORRECT
            if result.status is VerificationStatus.VERIFIED_CORRECT
            else Outcome.INCORRECT
        )
        evidence = (
            "The local verifier confirmed the submitted dashboard quest answer."
            if outcome is Outcome.CORRECT
            else "The local verifier rejected the submitted dashboard quest answer."
        )
        event = LearningEvent(
            skill_id=attempt.quest.skill_id,
            outcome=outcome,
            misconception=None,
            evidence=evidence,
            confidence=1.0,
            problem=attempt.quest.prompt,
            hints_used=attempt.hints_used,
            solution_revealed=attempt.solution_revealed,
            tutor_turns=1 + attempt.hints_used,
            outcome_source="student",
            reported_outcome=outcome,
            effective_outcome_source="verifier",
            verification_status=result.status.value,
            verification_kind=result.kind.value,
            verifier_version=result.verifier_version,
            verification_submitted=result.submitted,
            verification_expected=result.expected,
            verification_detail=result.detail,
            quest_id=attempt.quest.id,
        )
        with LearningStore(self.database_path, self.skills_path) as store:
            update = store.record_event(event)
            return {
                "progress": asdict(update),
                "profile": store.profile(),
            }


class SenseiDashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: DashboardService,
        quest_factory: GeneratedQuestFactory | None = None,
        adaptive_factory: AdaptiveQuestFactory | None = None,
        model_router: HostedModelRouter | None = None,
        pdf_scanner: PDFCurriculumScanner | None = None,
        error_recorder: ErrorRecorder | None = None,
    ) -> None:
        self.service = service
        self.error_recorder = error_recorder or ErrorRecorder()
        self.csrf_token = secrets.token_urlsafe(32)
        self.challenges = ChallengeStore(quest_factory, adaptive_factory)
        self.model_router = model_router
        self.pdf_scanner = pdf_scanner
        self.adaptive_available = adaptive_factory is not None or model_router is not None
        self.pdf_import_available = pdf_scanner is not None or model_router is not None
        self.pending_attempts = PendingAttemptStore()
        self.topic_state_lock = threading.RLock()
        self.assets = {
            path: (asset_path.read_bytes(), content_type)
            for path, (asset_path, content_type) in ASSETS.items()
        }
        super().__init__(server_address, DashboardRequestHandler)

    @property
    def default_practice_model(self) -> str:
        return (
            self.model_router.default_practice_model
            if self.model_router is not None
            else DEFAULT_API_MODEL
        )

    @property
    def default_scanner_model(self) -> str:
        return (
            self.model_router.default_scanner_model
            if self.model_router is not None
            else self.default_practice_model
        )

    def practice_factory_for(
        self, requested_model: object
    ) -> AdaptiveQuestFactory | None:
        if self.model_router is None:
            return None
        return self.model_router.practice_factory(requested_model)

    def pdf_scanner_for(self, requested_model: object) -> PDFCurriculumScanner:
        if self.model_router is not None:
            return self.model_router.curriculum_scanner(requested_model)
        if self.pdf_scanner is not None:
            return self.pdf_scanner
        raise RuntimeError(
            "PDF curriculum scanning is unavailable. Restart Sensei with a valid "
            "hosted LLM API connection."
        )

    def handle_error(
        self,
        request: object,
        client_address: tuple[str, int],
    ) -> None:
        """Persist exceptions that escape a request-handler method."""

        error = sys.exception()
        if error is None:
            error_id = self.error_recorder.record_problem(
                "A dashboard request thread stopped without an exception object.",
                component="dashboard.server",
                operation="unhandled request failure",
                context={"client": client_address[0]},
            )
        else:
            error_id = self.error_recorder.record_exception(
                error,
                component="dashboard.server",
                operation="unhandled request failure",
                context={"client": client_address[0]},
            )
        print(
            f"Dashboard request stopped unexpectedly ({error_reference(error_id)}).",
            file=sys.stderr,
        )


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: SenseiDashboardServer

    def _record_exception(
        self,
        error: BaseException,
        operation: str,
        *,
        context: dict[str, object] | None = None,
    ) -> str:
        request_context: dict[str, object] = {
            "method": self.command,
            "path": urlsplit(self.path).path,
            "client": self.client_address[0],
        }
        if context:
            request_context.update(context)
        return self.server.error_recorder.record_exception(
            error,
            component="dashboard.request",
            operation=operation,
            context=request_context,
        )

    def _record_problem(
        self,
        message: str,
        operation: str,
        *,
        context: dict[str, object] | None = None,
    ) -> str:
        request_context: dict[str, object] = {
            "method": self.command,
            "path": urlsplit(self.path).path,
            "client": self.client_address[0],
        }
        if context:
            request_context.update(context)
        return self.server.error_recorder.record_problem(
            message,
            component="dashboard.request",
            operation=operation,
            context=request_context,
        )

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, document: object) -> None:
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _read_json(
        self,
        expected_fields: set[str],
        *,
        optional_fields: set[str] | None = None,
        max_bytes: int = MAX_REQUEST_BYTES,
    ) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            raise ValueError("Requests must use application/json.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ValueError("A valid Content-Length is required.") from error
        if not 1 <= length <= max_bytes:
            raise ValueError(f"Request body must be from 1 to {max_bytes} bytes.")
        try:
            document = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid UTF-8 JSON.") from error
        optional_fields = optional_fields or set()
        supplied_fields = set(document) if isinstance(document, dict) else set()
        if (
            not isinstance(document, dict)
            or not expected_fields.issubset(supplied_fields)
            or not supplied_fields.issubset(expected_fields | optional_fields)
        ):
            raise ValueError(
                f"Request fields must include {sorted(expected_fields)} and may also "
                f"include {sorted(optional_fields)}."
            )
        return document

    def _write_is_allowed(self) -> bool:
        supplied = self.headers.get("X-Sensei-CSRF", "")
        if not secrets.compare_digest(supplied, self.server.csrf_token):
            return False
        origin = self.headers.get("Origin")
        expected_origin = f"http://{LOOPBACK_HOST}:{self.server.server_address[1]}"
        if origin and origin != expected_origin:
            return False
        return self.headers.get("Sec-Fetch-Site", "same-origin") in {
            "same-origin",
            "none",
        }

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "local": True})
            return
        if path == "/api/dashboard":
            try:
                document = self.server.service.state()
            except Exception as error:  # keep request failures inside the server
                error_id = self._record_exception(
                    error,
                    "load dashboard snapshot",
                )
                self.log_error(
                    "Dashboard snapshot failed (%s): %s",
                    error_reference(error_id),
                    error,
                )
                self._send_json(
                    500,
                    {
                        "error": "Dashboard data is unavailable.",
                        "error_id": error_id,
                    },
                )
                return
            document["csrf_token"] = self.server.csrf_token
            document["runtime"]["adaptive_generation"] = (
                "ready" if self.server.adaptive_available else "unavailable"
            )
            document["runtime"]["pdf_import"] = (
                "ready" if self.server.pdf_import_available else "unavailable"
            )
            document["runtime"]["default_practice_model"] = (
                self.server.default_practice_model
            )
            document["runtime"]["default_scanner_model"] = (
                self.server.default_scanner_model
            )
            self._send_json(200, document)
            return
        asset = self.server.assets.get(path)
        if asset is None:
            self._send_json(404, {"error": "Not found."})
            return
        body, content_type = asset
        self._send_bytes(
            200,
            body,
            content_type,
            cache_control="no-cache",
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._write_is_allowed():
            error_id = self._record_problem(
                "Local write authorization failed.",
                "authorize local dashboard write",
            )
            self._send_json(
                403,
                {
                    "error": "Local write authorization failed.",
                    "error_id": error_id,
                },
            )
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/errors":
                document = self._read_json({"message", "stack", "source"})
                message = document["message"]
                stack = document["stack"]
                source = document["source"]
                if (
                    not isinstance(message, str)
                    or not message.strip()
                    or len(message) > 1_000
                    or not isinstance(stack, str)
                    or len(stack) > 2_000
                    or not isinstance(source, str)
                    or not source.strip()
                    or len(source) > 120
                ):
                    raise ValueError("Browser error details are invalid or too large.")
                error_id = self.server.error_recorder.record_problem(
                    message,
                    component="dashboard.browser",
                    operation=source,
                    context={"stack": stack, "client": self.client_address[0]},
                )
                self._send_json(202, {"error_id": error_id})
                return
            if path == "/api/study/focus":
                document = self._read_json({"subject", "topic", "context"})
                if not all(isinstance(value, str) for value in document.values()):
                    raise ValueError("Study-focus fields must be text.")
                with self.server.topic_state_lock:
                    skill = self.server.service.create_study_topic(
                        subject=str(document["subject"]),
                        topic=str(document["topic"]),
                        context=str(document["context"]),
                    )
                self._send_json(200, {"study_topic": skill})
                return
            if path == "/api/study/import-pdf":
                document = self._read_json(
                    {
                        "filename",
                        "pdf_base64",
                        "subject_hint",
                        "folder_hint",
                        "scanner_model",
                    },
                    max_bytes=MAX_PDF_REQUEST_BYTES,
                )
                if not all(
                    isinstance(document[field], str)
                    for field in (
                        "filename",
                        "pdf_base64",
                        "subject_hint",
                        "folder_hint",
                        "scanner_model",
                    )
                ):
                    raise ValueError("PDF import fields must be text.")
                try:
                    pdf_bytes = base64.b64decode(
                        str(document["pdf_base64"]), validate=True
                    )
                except (binascii.Error, ValueError) as error:
                    raise ValueError("The uploaded PDF data is invalid.") from error
                if len(pdf_bytes) > MAX_PDF_BYTES:
                    raise ValueError("PDF files must be 20 MB or smaller.")
                selected_model = model_name(
                    document["scanner_model"],
                    fallback=self.server.default_scanner_model,
                )
                scanner = self.server.pdf_scanner_for(selected_model)
                plan = scanner.scan(
                    pdf_bytes,
                    filename=str(document["filename"]),
                    subject_hint=str(document["subject_hint"]),
                    folder_hint=str(document["folder_hint"]),
                )
                with self.server.topic_state_lock:
                    imported = self.server.service.create_topic_collection(
                        subject=plan.subject,
                        folder_name=plan.folder_name,
                        topics=[
                            {
                                "name": topic.name,
                                "description": topic.description,
                            }
                            for topic in plan.topics
                        ],
                    )
                self._send_json(
                    200,
                    {
                        "topic_folder": imported["folder"],
                        "study_topics": imported["topics"],
                        "scanner_model": selected_model,
                    },
                )
                return
            if path == "/api/study/delete":
                document = self._read_json({"skill_id"})
                skill_id = document["skill_id"]
                if not isinstance(skill_id, str) or len(skill_id) > 80:
                    raise ValueError("Study topic ID must be valid text.")
                with self.server.topic_state_lock:
                    deletion = self.server.service.delete_study_topic(skill_id)
                    self.server.challenges.discard_skill(skill_id)
                    self.server.pending_attempts.discard_skill(skill_id)
                self._send_json(200, {"deleted_topic": deletion})
                return
            if path == "/api/folders/create":
                document = self._read_json({"subject", "name", "skill_ids"})
                subject = document["subject"]
                name = document["name"]
                skill_ids = document["skill_ids"]
                if (
                    not isinstance(subject, str)
                    or not isinstance(name, str)
                    or not isinstance(skill_ids, list)
                    or not all(isinstance(skill_id, str) for skill_id in skill_ids)
                ):
                    raise ValueError("Folder details and topic selections are invalid.")
                with self.server.topic_state_lock:
                    folder = self.server.service.create_topic_folder(
                        subject=subject, name=name, skill_ids=skill_ids
                    )
                self._send_json(200, {"topic_folder": folder})
                return
            if path == "/api/folders/update":
                document = self._read_json({"folder_id", "name", "skill_ids"})
                folder_id = document["folder_id"]
                name = document["name"]
                skill_ids = document["skill_ids"]
                if (
                    not isinstance(folder_id, str)
                    or len(folder_id) > 80
                    or not isinstance(name, str)
                    or not isinstance(skill_ids, list)
                    or not all(isinstance(skill_id, str) for skill_id in skill_ids)
                ):
                    raise ValueError("Folder details and topic selections are invalid.")
                with self.server.topic_state_lock:
                    folder = self.server.service.update_topic_folder(
                        folder_id, name=name, skill_ids=skill_ids
                    )
                self._send_json(200, {"topic_folder": folder})
                return
            if path == "/api/folders/delete":
                document = self._read_json({"folder_id"})
                folder_id = document["folder_id"]
                if not isinstance(folder_id, str) or len(folder_id) > 80:
                    raise ValueError("Folder ID must be valid text.")
                with self.server.topic_state_lock:
                    folder = self.server.service.delete_topic_folder(folder_id)
                self._send_json(200, {"deleted_folder": folder})
                return
            if path == "/api/study/generate":
                document = self._read_json(
                    {"skill_id"}, optional_fields={"model"}
                )
                skill_id = document["skill_id"]
                if not isinstance(skill_id, str) or len(skill_id) > 80:
                    raise ValueError("Study topic ID must be valid text.")
                selected_model = model_name(
                    document.get("model"),
                    fallback=self.server.default_practice_model,
                )
                with self.server.topic_state_lock:
                    skill = self.server.service.study_topic(skill_id)
                    challenge_token, quest = self.server.challenges.issue_adaptive(
                        skill,
                        avoid_prompts=self.server.service.recent_topic_prompts(skill_id),
                        adaptive_factory=self.server.practice_factory_for(
                            selected_model
                        ),
                    )
                self._send_json(
                    200,
                    {
                        "quest": self.server.service.public_adaptive_quest(quest),
                        "challenge_token": challenge_token,
                        "practice_model": selected_model,
                    },
                )
                return
            if path == "/api/quest/generate":
                document = self._read_json({"skill_id"})
                skill_id = document["skill_id"]
                if not isinstance(skill_id, str) or len(skill_id) > 80:
                    raise ValueError("Skill ID must be valid text.")
                with self.server.topic_state_lock:
                    challenge_token, quest = self.server.challenges.issue(skill_id)
                self._send_json(
                    200,
                    {
                        "quest": self.server.service.public_generated_quest(quest),
                        "challenge_token": challenge_token,
                    },
                )
                return
            if path == "/api/quest/help":
                document = self._read_json({"challenge_token"})
                challenge_token = document["challenge_token"]
                if not isinstance(challenge_token, str) or len(challenge_token) > 200:
                    raise ValueError("Challenge token must be valid text.")
                with self.server.topic_state_lock:
                    reveal = self.server.challenges.reveal_help(challenge_token)
                self._send_json(
                    200,
                    {
                        **asdict(reveal),
                        "reward": help_reward_preview(
                            reveal.hints_used,
                            solution_revealed=reveal.final_answer,
                        ),
                    },
                )
                return
            if path == "/api/quest/check":
                document = self._read_json({"challenge_token", "answer"})
                challenge_token = document["challenge_token"]
                answer = document["answer"]
                if (
                    not isinstance(challenge_token, str)
                    or len(challenge_token) > 200
                    or not isinstance(answer, str)
                ):
                    raise ValueError("Challenge token and answer must be text.")
                with self.server.topic_state_lock:
                    quest, hints_used, solution_revealed = (
                        self.server.challenges.attempt_context(challenge_token)
                    )
                    result = self.server.service.check_quest(quest, answer)
                    attempt_token = (
                        None
                        if result.status is VerificationStatus.INCONCLUSIVE
                        else self.server.pending_attempts.issue(
                            quest,
                            result,
                            hints_used=hints_used,
                            solution_revealed=solution_revealed,
                        )
                    )
                self._send_json(
                    200,
                    {
                        "result": verification_document(result),
                        "attempt_token": attempt_token,
                        "solution": (
                            quest.solution if isinstance(quest, AdaptiveQuest) else None
                        ),
                    },
                )
                return
            if path == "/api/quest/record":
                document = self._read_json({"attempt_token"})
                token = document["attempt_token"]
                if not isinstance(token, str) or len(token) > 200:
                    raise ValueError("Attempt token must be valid text.")
                with self.server.topic_state_lock:
                    attempt = self.server.pending_attempts.consume(token)
                    recorded = self.server.service.record_attempt(attempt)
                self._send_json(
                    200,
                    recorded,
                )
                return
        except PracticeGenerationError as error:
            error_id = self._record_exception(
                error,
                "generate and validate adaptive encounter",
            )
            self.log_error(
                "Adaptive generation failed validation (%s): %s",
                error_reference(error_id),
                error,
            )
            self._send_json(
                503,
                {
                    "error": (
                        "Sensei could not finish a valid new encounter. "
                        "Please try again."
                    ),
                    "error_id": error_id,
                },
            )
            return
        except (MathInputError, ValueError) as error:
            error_id = self._record_exception(
                error,
                "validate dashboard request",
            )
            self._send_json(
                400,
                {"error": str(error), "error_id": error_id},
            )
            return
        except (OSError, RuntimeError, sqlite3.Error) as error:
            error_id = self._record_exception(
                error,
                "complete dashboard write",
            )
            self.log_error(
                "Dashboard write failed (%s): %s",
                error_reference(error_id),
                error,
            )
            message = (
                "Sensei could not generate a new encounter. Please try again."
                if path in {"/api/study/generate", "/api/quest/generate"}
                else "The topic and its learning data could not be deleted."
                if path == "/api/study/delete"
                else "The Atlas folder could not be saved."
                if path.startswith("/api/folders/")
                else "The local attempt could not be recorded."
            )
            self._send_json(
                500,
                {"error": message, "error_id": error_id},
            )
            return
        except Exception as error:
            error_id = self._record_exception(
                error,
                "unexpected dashboard request failure",
            )
            self.log_error(
                "Unexpected dashboard request failure (%s): %s",
                error_reference(error_id),
                error,
            )
            self._send_json(
                500,
                {
                    "error": "The dashboard request failed unexpectedly.",
                    "error_id": error_id,
                },
            )
            return
        self._send_json(404, {"error": "Not found."})

    def log_message(self, format: str, *args: object) -> None:
        print(
            f"Dashboard {self.client_address[0]} - {format % args}",
            file=sys.stderr,
        )


def create_server(
    service: DashboardService,
    *,
    port: int = DEFAULT_DASHBOARD_PORT,
    quest_factory: GeneratedQuestFactory | None = None,
    adaptive_factory: AdaptiveQuestFactory | None = None,
    model_router: HostedModelRouter | None = None,
    pdf_scanner: PDFCurriculumScanner | None = None,
    error_recorder: ErrorRecorder | None = None,
) -> SenseiDashboardServer:
    if not 0 <= port <= 65_535:
        raise ValueError("Dashboard port must be from 0 to 65535.")
    return SenseiDashboardServer(
        (LOOPBACK_HOST, port),
        service,
        quest_factory,
        adaptive_factory,
        model_router,
        pdf_scanner,
        error_recorder,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Sensei's local RPG learning dashboard."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="Local SQLite learning-memory path.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DASHBOARD_PORT,
        help=f"Loopback port (default: {DEFAULT_DASHBOARD_PORT}).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the dashboard without opening a browser.",
    )
    parser.add_argument(
        "--model",
        help=(
            f"Hosted model name (default: {DEFAULT_API_MODEL}, or "
            "SENSEI_LLM_MODEL)."
        ),
    )
    parser.add_argument(
        "--api-base-url",
        help=(
            f"Responses-compatible API root (default: {DEFAULT_API_BASE_URL}, "
            "or SENSEI_LLM_BASE_URL)."
        ),
    )
    parser.add_argument(
        "--scanner-model",
        help=(
            "Hosted model used only for PDF curriculum scanning (default: the "
            f"practice model, or {SCANNER_MODEL_ENVIRONMENT})."
        ),
    )
    parser.add_argument(
        "--error-log",
        type=Path,
        default=DEFAULT_ERROR_LOG_PATH,
        help="Local structured error-log path.",
    )
    return parser.parse_args(argv)


def _model_router(
    args: argparse.Namespace,
    stack: ExitStack,
) -> HostedModelRouter:
    del stack
    settings = api_settings_from_environment(
        model=args.model,
        base_url=args.api_base_url,
    )
    scanner_model = model_name(
        args.scanner_model or os.environ.get(SCANNER_MODEL_ENVIRONMENT),
        fallback=settings.model,
    )
    return HostedModelRouter(settings, scanner_model)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    error_recorder = ErrorRecorder(args.error_log)
    with ExitStack() as stack:
        try:
            service = DashboardService(args.database)
            service.state()
            model_router = _model_router(args, stack)
            server = create_server(
                service,
                port=args.port,
                model_router=model_router,
                error_recorder=error_recorder,
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            error_id = error_recorder.record_exception(
                error,
                component="dashboard",
                operation="startup",
            )
            print(
                f"Dashboard could not start: {error} "
                f"({error_reference(error_id)})",
                file=sys.stderr,
            )
            return 1
        except Exception as error:
            error_id = error_recorder.record_exception(
                error,
                component="dashboard",
                operation="unexpected startup failure",
            )
            print(
                f"Dashboard stopped during startup ({error_reference(error_id)}).",
                file=sys.stderr,
            )
            return 1

        host, port = server.server_address
        url = f"http://{host}:{port}/"
        print(f"Sensei dashboard: {url}")
        print("Learning data stays in local SQLite; tutoring uses the configured API.")
        print(f"Structured error log: {error_recorder.path}")
        if not args.no_open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping dashboard.")
        except Exception as error:
            error_id = error_recorder.record_exception(
                error,
                component="dashboard",
                operation="serve dashboard",
            )
            print(
                f"Dashboard stopped unexpectedly ({error_reference(error_id)}).",
                file=sys.stderr,
            )
            return 1
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
