"""Loopback-only browser dashboard with local learning memory and hosted inference."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from collections import deque
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Collection, Mapping
from urllib.parse import urlsplit

from sensei.answers import AnswerSpec, answer_key_display, answer_key_latex, submitted_latex
from sensei.curriculum import StudyPlanScanner
from sensei.study import guide_progress
from sensei.errorlog import DEFAULT_ERROR_LOG_PATH, ErrorRecorder, error_reference
from sensei.learning import (
    LearningEvent,
    LearningEventError,
    MisconceptionClassifier,
    MisconceptionFinding,
    Outcome,
)
from sensei.lessons import (
    MAX_LEARNER_ANSWER_CHARACTERS,
    MAX_LEARNER_QUESTION_CHARACTERS,
    Lesson,
    LessonFactory,
)
from sensei.materials import MAX_PDF_BYTES
from sensei.practice import (
    AdaptiveQuest,
    AdaptiveQuestFactory,
    AttemptCheck,
    PracticeGenerationError,
    adaptive_quest_fingerprint,
)
from sensei.providers import (
    DEFAULT_API_BASE_URL,
    DEFAULT_API_MODEL,
    ProviderError,
    ResponsesAPIProvider,
    api_settings_from_environment,
)
from sensei.storage import (
    DEFAULT_DATABASE_PATH,
    LearningStore,
    utc_now,
)
from sensei.verification import MathInputError, VerificationResult, VerificationStatus, math_expression_latex


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_REQUEST_BYTES = 4_096
MAX_UPLOAD_REQUEST_BYTES = (MAX_PDF_BYTES * 4 // 3) + 16_384
MAX_PLAN_REQUEST_BYTES = 256 * 1024
MAX_PLAN_TOPICS_PER_REQUEST = 40
PLAN_SCANNER_MAX_OUTPUT_TOKENS = 16_384
ATTEMPT_TOKEN_LIFETIME_SECONDS = 15 * 60
CHALLENGE_TOKEN_LIFETIME_SECONDS = 60 * 60
ADAPTIVE_PROMPT_HISTORY = 8
ADAPTIVE_DISTINCT_ATTEMPTS = 3
PRACTICE_API_VERSION = 8
PRACTICE_MAX_OUTPUT_TOKENS = 8_192
LESSON_MAX_OUTPUT_TOKENS = 12_000
LESSON_COACH_MAX_OUTPUT_TOKENS = 1_500
MAX_LESSON_STEP_INDEX = 100
LESSON_PROGRESS_FIELDS = (
    "status",
    "current_step",
    "step_count",
    "completed_at",
)
LESSON_FAILURE_MESSAGES = {
    "/api/study/learn/start": (
        "generate and validate guided lesson",
        "Sensei could not finish a valid lesson. Please try again.",
    ),
    "/api/study/learn/check": (
        "grade lesson check-in",
        "Sensei could not read that answer. Please try again.",
    ),
    "/api/study/learn/ask": (
        "answer lesson question",
        "Sensei could not answer that question. Please try again.",
    ),
}
CLASSIFIER_MAX_OUTPUT_TOKENS = 400
SCANNER_MODEL_ENVIRONMENT = "SENSEI_SCANNER_MODEL"
WEB_DIRECTORY = Path(__file__).resolve().parent / "web"
KATEX_DIRECTORY = WEB_DIRECTORY / "vendor" / "katex"
PracticeQuest = AdaptiveQuest
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


def _answer_latex(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return math_expression_latex(value)
    except MathInputError:
        return None


def verification_document(
    result: VerificationResult,
    spec: AnswerSpec | None = None,
) -> dict[str, str | None]:
    if spec is not None and spec.answer_type != "expression":
        submitted_form = submitted_latex(spec, result.submitted)
        expected_form = answer_key_latex(spec)
    else:
        submitted_form = _answer_latex(result.submitted)
        expected_form = _answer_latex(result.expected)
    return {
        "kind": result.kind.value,
        "status": result.status.value,
        "submitted": result.submitted,
        "submitted_latex": submitted_form,
        "expected": result.expected,
        "expected_latex": expected_form,
        "detail": result.detail,
        "verifier_version": result.verifier_version,
    }


def part_documents(
    quest: PracticeQuest, check: AttemptCheck
) -> list[dict[str, object]]:
    """Serialize per-part results for a multi-part adaptive quest."""

    if not check.parts:
        return []
    specs = {part.label: part.spec for part in quest.parts}
    return [
        {
            "label": label,
            "answer_type": specs[label].answer_type,
            **verification_document(result, specs[label]),
        }
        for label, result in check.parts
    ]


@dataclass(frozen=True)
class PendingAttempt:
    quest: PracticeQuest
    result: VerificationResult
    hints_used: int
    solution_revealed: bool
    issued_at: float
    outcome: Outcome = Outcome.INCORRECT
    parts: tuple[tuple[str, VerificationResult], ...] = ()
    misconception: str | None = None
    misconception_evidence: str | None = None


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
        outcome: Outcome | None = None,
        parts: tuple[tuple[str, VerificationResult], ...] = (),
        misconception: str | None = None,
        misconception_evidence: str | None = None,
    ) -> str:
        if outcome is None:
            outcome = (
                Outcome.CORRECT
                if result.status is VerificationStatus.VERIFIED_CORRECT
                else Outcome.INCORRECT
            )
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._attempts[token] = PendingAttempt(
                quest=quest,
                result=result,
                hints_used=hints_used,
                solution_revealed=solution_revealed,
                issued_at=now,
                outcome=outcome,
                parts=parts,
                misconception=misconception,
                misconception_evidence=misconception_evidence,
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


    def _prune(self, now: float) -> None:
        expired = [
            token
            for token, attempt in self._attempts.items()
            if now - attempt.issued_at > ATTEMPT_TOKEN_LIFETIME_SECONDS
        ]
        for token in expired:
            del self._attempts[token]


def quest_help_steps(quest: PracticeQuest) -> tuple[str, ...]:
    """Return validated help followed by the protected answer."""
    if quest.is_multi_part:
        final = "Final answers: " + " ".join(
            f"({part.label}) {answer_key_display(part.spec)}" for part in quest.parts
        )
    else:
        assert quest.spec is not None
        final = f"Final answer: {answer_key_display(quest.spec)}"
    return (*quest.help_steps, final)


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
        adaptive_factory: AdaptiveQuestFactory | None = None,
    ) -> None:
        self.adaptive_factory = adaptive_factory
        self._challenges: dict[str, PendingChallenge] = {}
        self._last_prompts: dict[str, str] = {}
        self._adaptive_prompts: dict[str, deque[str]] = {}
        self._adaptive_fingerprints: dict[str, deque[str]] = {}
        self._anchor_cursor: dict[str, int] = {}
        self._lock = threading.Lock()


    def issue_adaptive(
        self,
        skill: dict[str, Any],
        *,
        avoid_prompts: Collection[str] = (),
        materials: Collection[dict[str, Any]] = (),
        subject_profile: str = "",
        learner_signal: dict[str, Any] | None = None,
    ) -> tuple[str, AdaptiveQuest]:
        if self.adaptive_factory is None:
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
                anchor_index = self._anchor_cursor.get(skill_id, 0)
            recent = tuple(dict.fromkeys((*avoid_prompts, *session_recent)))[
                -ADAPTIVE_PROMPT_HISTORY:
            ]
            quest = self.adaptive_factory.generate(
                skill,
                avoid_prompts=recent,
                avoid_fingerprints=session_fingerprints,
                materials=tuple(materials),
                subject_profile=subject_profile,
                learner_signal=learner_signal,
                anchor_index=anchor_index,
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
                self._last_prompts[skill_id] = quest.full_text
                history.append(quest.full_text)
                fingerprint_history.append(fingerprint)
                self._anchor_cursor[skill_id] = anchor_index + 1
                return token, quest
        raise RuntimeError(
            "Sensei could not produce a distinct new question for this topic."
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
    ) -> None:
        self.database_path = database_path.resolve()

    def state(self) -> dict[str, Any]:
        with LearningStore(self.database_path) as store:
            topics = store.study_topics()
            folders = store.topic_folders()
            contexts = {topic["id"]: store.generation_context(topic["id"]) for topic in topics}
            guides = [
                {**folder, **guide_progress(
                    [topic for topic in topics if topic.get("folder_id") == folder["id"]], contexts
                )} for folder in folders
            ]
            return {
                "generated_at": utc_now().isoformat(),
                "study_topics": topics,
                "study_guides": guides,
                "recent_attempts": store.recent_attempts(limit=50),
                "runtime": {"host": LOOPBACK_HOST, "storage": "Local SQLite",
                            "practice_api_version": PRACTICE_API_VERSION},
            }


    def study_topic(self, skill_id: str) -> dict[str, Any]:
        with LearningStore(self.database_path) as store:
            return store.study_topic(skill_id)


    def create_study_plan(
        self,
        *,
        subject: str,
        set_name: str,
        course_profile: str,
        topics: Collection[dict[str, Any]],
    ) -> dict[str, Any]:
        with LearningStore(self.database_path) as store:
            return store.create_study_plan(
                subject=subject,
                set_name=set_name,
                course_profile=course_profile,
                topics=topics,
            )

    def generation_brief(self, skill_id: str) -> dict[str, Any]:
        """Collect everything one adaptive generation needs in one store session."""

        with LearningStore(self.database_path) as store:
            skill = store.study_topic(skill_id)
            return {
                "skill": skill,
                "avoid_prompts": store.recent_problems(
                    skill_id, limit=ADAPTIVE_PROMPT_HISTORY
                ),
                "materials": store.topic_materials(skill_id),
                "subject_profile": store.subject_profile(str(skill["course"])),
                "learner_signal": store.generation_context(skill_id),
            }

    def lesson_brief(self, skill_id: str) -> dict[str, Any]:
        """Collect everything one guided lesson needs in one store session."""

        with LearningStore(self.database_path) as store:
            skill = store.study_topic(skill_id)
            return {
                "skill": skill,
                "materials": store.topic_materials(skill_id),
                "subject_profile": store.subject_profile(str(skill["course"])),
                "learner_signal": store.generation_context(skill_id),
            }

    def lesson_for_topic(self, skill_id: str) -> dict[str, Any] | None:
        with LearningStore(self.database_path) as store:
            return store.lesson_for_topic(skill_id)

    def save_lesson(self, lesson: Lesson) -> dict[str, Any]:
        with LearningStore(self.database_path) as store:
            return store.save_lesson(
                lesson.skill_id, lesson.id, lesson.private_dict(), lesson.step_count
            )

    def advance_lesson(self, skill_id: str, step_index: int) -> dict[str, Any]:
        with LearningStore(self.database_path) as store:
            return store.advance_lesson(skill_id, step_index)


    @staticmethod
    def public_lesson(record: Mapping[str, Any]) -> dict[str, Any]:
        """Return the learner-facing lesson without any check-in answer keys."""

        lesson = Lesson.from_private_dict(
            record["document"],
            lesson_id=str(record["id"]),
            skill_id=str(record["skill_id"]),
        )
        return lesson.public_dict()

    @staticmethod
    def lesson_progress_document(record: Mapping[str, Any]) -> dict[str, Any]:
        return {field: record[field] for field in LESSON_PROGRESS_FIELDS}


    @staticmethod
    def public_adaptive_quest(quest: AdaptiveQuest) -> dict[str, Any]:
        return quest.public_dict()


    def evaluate_quest(self, quest: PracticeQuest, answer: object) -> AttemptCheck:
        return quest.evaluate(answer)

    def record_attempt(
        self,
        attempt: PendingAttempt,
    ) -> dict[str, Any]:
        result = attempt.result
        if result.status is VerificationStatus.INCONCLUSIVE:
            raise ValueError("An inconclusive check cannot be recorded as a practice result.")
        outcome = attempt.outcome
        default_evidence = {
            Outcome.CORRECT: (
                "The local verifier confirmed the submitted practice answer."
            ),
            Outcome.PARTIAL: (
                "The local verifier confirmed some parts of the submitted dashboard "
                "quest answer."
            ),
            Outcome.INCORRECT: (
                "The local verifier rejected the submitted practice answer."
            ),
        }[outcome]
        evidence = attempt.misconception_evidence or default_evidence
        problem = attempt.quest.full_text
        event = LearningEvent(
            skill_id=attempt.quest.skill_id,
            outcome=outcome,
            misconception=attempt.misconception,
            evidence=evidence,
            confidence=1.0,
            problem=problem,
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
        with LearningStore(self.database_path) as store:
            update = store.record_event(event)
            return {
                "progress": asdict(update),
            }


class SenseiDashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: DashboardService,
        adaptive_factory: AdaptiveQuestFactory | None = None,
        error_recorder: ErrorRecorder | None = None,
        misconception_classifier: MisconceptionClassifier | None = None,
        study_plan_scanner: StudyPlanScanner | None = None,
        lesson_factory: LessonFactory | None = None,
    ) -> None:
        self.service = service
        self.error_recorder = error_recorder or ErrorRecorder()
        self.csrf_token = secrets.token_urlsafe(32)
        self.challenges = ChallengeStore(adaptive_factory)
        self.adaptive_available = adaptive_factory is not None
        self.misconception_classifier = misconception_classifier
        self.study_plan_scanner = study_plan_scanner
        self.lesson_factory = lesson_factory
        self.pending_attempts = PendingAttemptStore()
        self.topic_state_lock = threading.RLock()
        self.assets = {
            path: (asset_path.read_bytes(), content_type)
            for path, (asset_path, content_type) in ASSETS.items()
        }
        super().__init__(server_address, DashboardRequestHandler)

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
        optional = optional_fields or set()
        supplied = set(document) if isinstance(document, dict) else set()
        if (
            not isinstance(document, dict)
            or not expected_fields.issubset(supplied)
            or not supplied.issubset(expected_fields | optional)
        ):
            if optional:
                raise ValueError(
                    f"Request fields must include {sorted(expected_fields)} and may "
                    f"also include {sorted(optional)}."
                )
            raise ValueError(
                f"Request fields must be exactly {sorted(expected_fields)}."
            )
        return document

    @staticmethod
    def _skill_id(value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 80:
            raise ValueError("Study topic ID must be valid text.")
        return value

    @staticmethod
    def _step_index(value: object) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= MAX_LESSON_STEP_INDEX
        ):
            raise ValueError("Lesson step must be a whole number.")
        return value

    @staticmethod
    def _learner_text(value: object, *, maximum: int, empty_message: str) -> str:
        if not isinstance(value, str):
            raise ValueError(empty_message)
        text = value.strip()
        if not text:
            raise ValueError(empty_message)
        if len(text) > maximum:
            raise ValueError(f"Keep it under {maximum} characters.")
        return text

    def _lesson_factory(self) -> LessonFactory:
        factory = self.server.lesson_factory
        if factory is None:
            raise RuntimeError(
                "Guided lessons are unavailable. Restart Sensei with a valid hosted "
                "LLM API connection."
            )
        return factory

    def _lesson_response(
        self, record: Mapping[str, Any], *, generated: bool
    ) -> dict[str, Any]:
        service = self.server.service
        return {
            "lesson": service.public_lesson(record),
            "progress": service.lesson_progress_document(record),
            "generated": generated,
        }

    def _active_lesson(
        self, skill_id: str, step_index: int
    ) -> tuple[dict[str, Any], Lesson, dict[str, Any]]:
        """Load one topic's stored lesson for a step the learner has reached."""

        service = self.server.service
        skill = service.study_topic(skill_id)
        record = service.lesson_for_topic(skill_id)
        if record is None:
            raise ValueError("Start the lesson before working on a step.")
        if step_index >= int(record["step_count"]):
            raise ValueError("That lesson step does not exist.")
        if step_index > int(record["current_step"]):
            raise ValueError("Finish the earlier steps first.")
        lesson = Lesson.from_private_dict(
            record["document"], lesson_id=str(record["id"]), skill_id=skill_id
        )
        return skill, lesson, record

    def _diagnose(
        self,
        quest: AdaptiveQuest,
        check: AttemptCheck,
        hints_used: int,
    ) -> MisconceptionFinding | None:
        """Best-effort naming of the mistake behind a wrong or partial answer."""

        classifier = self.server.misconception_classifier
        if classifier is None:
            return None
        if check.parts:
            wrong = [
                (label, result)
                for label, result in check.parts
                if result.status is not VerificationStatus.VERIFIED_CORRECT
            ]
            expected = "; ".join(f"({label}) {result.expected}" for label, result in wrong)
            submitted = "; ".join(
                f"({label}) {result.submitted}" for label, result in wrong
            )
        else:
            expected = check.result.expected or ""
            submitted = check.result.submitted
        try:
            return classifier.classify(
                subject=quest.subject,
                topic=quest.topic,
                problem=quest.full_text,
                expected=expected,
                submitted=submitted,
                solution=quest.solution,
                help_steps_used=hints_used,
            )
        except (ProviderError, LearningEventError, ValueError) as error:
            self._record_exception(
                error,
                "classify misconception",
                context={"skill_id": quest.skill_id},
            )
            return None

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
            document["runtime"]["lessons"] = (
                "ready" if self.server.lesson_factory is not None else "unavailable"
            )
            document["runtime"]["study_plan_scan"] = (
                "ready" if self.server.study_plan_scanner is not None else "unavailable"
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
        generation_context: dict[str, object] = {}
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
            if path == "/api/study/plan/scan":
                document = self._read_json(
                    {"filename", "media_base64", "media_type", "subject_hint", "set_name_hint"},
                    max_bytes=MAX_UPLOAD_REQUEST_BYTES,
                )
                if not all(isinstance(value, str) for value in document.values()):
                    raise ValueError("Study-guide fields must be text.")
                try:
                    media_bytes = base64.b64decode(
                        str(document["media_base64"]), validate=True
                    )
                except (binascii.Error, ValueError) as error:
                    raise ValueError("The uploaded file data is invalid.") from error
                scanner = self.server.study_plan_scanner
                if scanner is None:
                    raise RuntimeError(
                        "Study-guide analysis is unavailable. Restart Sensei with a "
                        "valid hosted LLM API connection."
                    )
                plan = scanner.scan(
                    media_bytes,
                    filename=str(document["filename"]),
                    media_type=str(document["media_type"]),
                    subject_hint=str(document["subject_hint"]),
                    set_name_hint=str(document["set_name_hint"]),
                )
                self._send_json(200, {"plan": plan.public_dict()})
                return
            if path == "/api/study/plan/create":
                document = self._read_json(
                    {"subject", "set_name", "course_profile", "topics"},
                    max_bytes=MAX_PLAN_REQUEST_BYTES,
                )
                raw_topics = document["topics"]
                if not all(
                    isinstance(document[field], str)
                    for field in ("subject", "set_name", "course_profile")
                ):
                    raise ValueError("Study-plan fields must be text.")
                if (
                    not isinstance(raw_topics, list)
                    or not 1 <= len(raw_topics) <= MAX_PLAN_TOPICS_PER_REQUEST
                    or not all(isinstance(item, dict) for item in raw_topics)
                ):
                    raise ValueError(
                        "A study plan must list 1 to "
                        f"{MAX_PLAN_TOPICS_PER_REQUEST} topics."
                    )
                for item in raw_topics:
                    if not set(item) <= {"name", "section", "description", "materials"}:
                        raise ValueError(
                            "Each topic may only include name, section, description, "
                            "and materials."
                        )
                    for field in ("name", "section", "description"):
                        if item.get(field) is not None and not isinstance(item[field], str):
                            raise ValueError("Study-plan topic fields must be text.")
                    materials = item.get("materials") or []
                    if not isinstance(materials, list) or not all(
                        isinstance(material, dict)
                        and set(material) <= {"kind", "body", "solution", "source_label"}
                        and all(
                            value is None or isinstance(value, str)
                            for value in material.values()
                        )
                        for material in materials
                    ):
                        raise ValueError("Study-plan materials must be text objects.")
                with self.server.topic_state_lock:
                    result = self.server.service.create_study_plan(
                        subject=str(document["subject"]),
                        set_name=str(document["set_name"]),
                        course_profile=str(document["course_profile"]),
                        topics=raw_topics,
                    )
                self._send_json(200, result)
                return
            if path == "/api/study/generate":
                document = self._read_json({"skill_id"})
                skill_id = self._skill_id(document["skill_id"])
                generation_context = {"skill_id": skill_id}
                with self.server.topic_state_lock:
                    brief = self.server.service.generation_brief(skill_id)
                    challenge_token, quest = self.server.challenges.issue_adaptive(
                        brief["skill"],
                        avoid_prompts=brief["avoid_prompts"],
                        materials=brief["materials"],
                        subject_profile=brief["subject_profile"],
                        learner_signal=brief["learner_signal"],
                    )
                self._send_json(
                    200,
                    {
                        "quest": self.server.service.public_adaptive_quest(quest),
                        "challenge_token": challenge_token,
                    },
                )
                return
            if path == "/api/study/learn/start":
                document = self._read_json({"skill_id", "restart"})
                skill_id = self._skill_id(document["skill_id"])
                restart = document["restart"]
                if not isinstance(restart, bool):
                    raise ValueError("The restart flag must be true or false.")
                generation_context = {"skill_id": skill_id}
                with self.server.topic_state_lock:
                    brief = self.server.service.lesson_brief(skill_id)
                    existing = self.server.service.lesson_for_topic(skill_id)
                if existing is not None and not restart:
                    self._send_json(200, self._lesson_response(existing, generated=False))
                    return
                factory = self._lesson_factory()
                # The long lesson call runs outside the topic lock, like scans do.
                lesson = factory.generate(
                    brief["skill"],
                    materials=brief["materials"],
                    subject_profile=brief["subject_profile"],
                    learner_signal=brief["learner_signal"],
                )
                with self.server.topic_state_lock:
                    record = self.server.service.save_lesson(lesson)
                self._send_json(200, self._lesson_response(record, generated=True))
                return
            if path == "/api/study/learn/check":
                document = self._read_json({"skill_id", "step_index", "answer"})
                skill_id = self._skill_id(document["skill_id"])
                step_index = self._step_index(document["step_index"])
                answer = self._learner_text(
                    document["answer"],
                    maximum=MAX_LEARNER_ANSWER_CHARACTERS,
                    empty_message="Enter an answer to the check-in question first.",
                )
                generation_context = {"skill_id": skill_id, "step_index": step_index}
                with self.server.topic_state_lock:
                    skill, lesson, record = self._active_lesson(skill_id, step_index)
                factory = self._lesson_factory()
                grade = factory.grade_check_in(skill, lesson, step_index, answer)
                progress = self.server.service.lesson_progress_document(record)
                completed = False
                if grade.passed and step_index == int(record["current_step"]):
                    with self.server.topic_state_lock:
                        advanced = self.server.service.advance_lesson(
                            skill_id, step_index
                        )
                        progress = advanced
                        completed = (
                            advanced["status"] == "complete"
                            and record["status"] != "complete"
                        )
                self._send_json(
                    200,
                    {
                        "verdict": grade.verdict,
                        "feedback": grade.feedback,
                        "progress": progress,
                        "completed": completed,
                    },
                )
                return
            if path == "/api/study/learn/ask":
                document = self._read_json({"skill_id", "step_index", "question"})
                skill_id = self._skill_id(document["skill_id"])
                step_index = self._step_index(document["step_index"])
                question = self._learner_text(
                    document["question"],
                    maximum=MAX_LEARNER_QUESTION_CHARACTERS,
                    empty_message="Type a question for Sensei first.",
                )
                generation_context = {"skill_id": skill_id, "step_index": step_index}
                with self.server.topic_state_lock:
                    skill, lesson, _record = self._active_lesson(skill_id, step_index)
                factory = self._lesson_factory()
                answer = factory.answer_question(skill, lesson, step_index, question)
                self._send_json(200, {"answer": answer})
                return
            if path == "/api/practice/help":
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
                    },
                )
                return
            if path == "/api/practice/check":
                document = self._read_json({"challenge_token", "answer"})
                challenge_token = document["challenge_token"]
                answer = document["answer"]
                if not isinstance(challenge_token, str) or len(challenge_token) > 200:
                    raise ValueError("Challenge token and answer must be text.")
                if isinstance(answer, dict):
                    if len(answer) > 8 or not all(
                        isinstance(label, str) and isinstance(value, str)
                        for label, value in answer.items()
                    ):
                        raise ValueError("Part answers must be text.")
                elif not isinstance(answer, str):
                    raise ValueError("Challenge token and answer must be text.")
                with self.server.topic_state_lock:
                    quest, hints_used, solution_revealed = (
                        self.server.challenges.attempt_context(challenge_token)
                    )
                    check = self.server.service.evaluate_quest(quest, answer)
                result = check.result
                conclusive = result.status is not VerificationStatus.INCONCLUSIVE
                finding = None
                if (
                    conclusive
                    and check.outcome is not Outcome.CORRECT
                    and not solution_revealed
                ):
                    finding = self._diagnose(quest, check, hints_used)
                attempt_token = (
                    self.server.pending_attempts.issue(
                        quest,
                        result,
                        hints_used=hints_used,
                        solution_revealed=solution_revealed,
                        outcome=check.outcome,
                        parts=check.parts,
                        misconception=finding.misconception if finding else None,
                        misconception_evidence=finding.evidence if finding else None,
                    )
                    if conclusive
                    else None
                )
                spec = quest.spec
                self._send_json(
                    200,
                    {
                        "result": verification_document(result, spec),
                        "outcome": check.outcome.value if conclusive else None,
                        "parts": part_documents(quest, check),
                        "attempt_token": attempt_token,
                        "solution": (
                            quest.solution
                        ),
                        "likely_mistake": finding.misconception if finding else None,
                    },
                )
                return
            if path == "/api/practice/record":
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
            operation, message = LESSON_FAILURE_MESSAGES.get(
                path,
                (
                    "generate and validate adaptive question",
                    "Sensei could not finish a valid new question. Please try again.",
                ),
            )
            error_id = self._record_exception(
                error,
                operation,
                context=generation_context,
            )
            self.log_error(
                "Hosted generation failed validation (%s): %s",
                error_reference(error_id),
                error,
            )
            self._send_json(
                503,
                {
                    "error": message,
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
                "Sensei could not generate a new question. Please try again."
                if path == "/api/study/generate"
                else "Sensei could not build the lesson. Please try again."
                if path == "/api/study/learn/start"
                else "Sensei could not finish that lesson step. Please try again."
                if path.startswith("/api/study/learn/")
                else "Sensei could not analyze that document. Please try again."
                if path == "/api/study/plan/scan"
                else "The study plan could not be saved."
                if path == "/api/study/plan/create"
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
    adaptive_factory: AdaptiveQuestFactory | None = None,
    error_recorder: ErrorRecorder | None = None,
    misconception_classifier: MisconceptionClassifier | None = None,
    study_plan_scanner: StudyPlanScanner | None = None,
    lesson_factory: LessonFactory | None = None,
) -> SenseiDashboardServer:
    if not 0 <= port <= 65_535:
        raise ValueError("Dashboard port must be from 0 to 65535.")
    return SenseiDashboardServer(
        (LOOPBACK_HOST, port),
        service,
        adaptive_factory,
        error_recorder,
        misconception_classifier=misconception_classifier,
        study_plan_scanner=study_plan_scanner,
        lesson_factory=lesson_factory,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Sensei's study-guide learning dashboard."
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
        "--scanner-model",
        help=(
            "Hosted model used only to scan uploaded class material (default: the "
            f"practice model, or {SCANNER_MODEL_ENVIRONMENT})."
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
        "--error-log",
        type=Path,
        default=DEFAULT_ERROR_LOG_PATH,
        help="Local structured error-log path.",
    )
    return parser.parse_args(argv)


@dataclass(frozen=True)
class HostedComponents:
    """Every hosted-model client the dashboard builds from one credential."""

    factory: AdaptiveQuestFactory
    classifier: MisconceptionClassifier
    plan_scanner: StudyPlanScanner
    practice_model: str
    scanner_model: str
    lesson_factory: LessonFactory


def _hosted_components(args: argparse.Namespace) -> HostedComponents:
    settings = api_settings_from_environment(
        model=args.model,
        base_url=args.api_base_url,
    )
    scanner_model = (
        getattr(args, "scanner_model", None)
        or os.environ.get(SCANNER_MODEL_ENVIRONMENT)
        or settings.model
    ).strip() or settings.model
    factory = AdaptiveQuestFactory(
        ResponsesAPIProvider(
            settings.api_key,
            settings.model,
            base_url=settings.base_url,
            max_output_tokens=PRACTICE_MAX_OUTPUT_TOKENS,
            json_mode=True,
        )
    )
    classifier = MisconceptionClassifier(
        ResponsesAPIProvider(
            settings.api_key,
            settings.model,
            base_url=settings.base_url,
            max_output_tokens=CLASSIFIER_MAX_OUTPUT_TOKENS,
            json_mode=True,
        )
    )
    plan_scanner = StudyPlanScanner(
        ResponsesAPIProvider(
            settings.api_key,
            scanner_model,
            base_url=settings.base_url,
            timeout_seconds=300,
            max_output_tokens=PLAN_SCANNER_MAX_OUTPUT_TOKENS,
            json_mode=True,
        )
    )
    lesson_factory = LessonFactory(
        ResponsesAPIProvider(
            settings.api_key,
            settings.model,
            base_url=settings.base_url,
            timeout_seconds=300,
            max_output_tokens=LESSON_MAX_OUTPUT_TOKENS,
            json_mode=True,
        ),
        coach_provider=ResponsesAPIProvider(
            settings.api_key,
            settings.model,
            base_url=settings.base_url,
            max_output_tokens=LESSON_COACH_MAX_OUTPUT_TOKENS,
            json_mode=True,
        ),
    )
    return HostedComponents(
        factory,
        classifier,
        plan_scanner,
        settings.model,
        scanner_model,
        lesson_factory,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    error_recorder = ErrorRecorder(args.error_log)
    with ExitStack() as stack:
        try:
            service = DashboardService(args.database)
            service.state()
            components = _hosted_components(args)
            server = create_server(
                service,
                port=args.port,
                adaptive_factory=components.factory,
                error_recorder=error_recorder,
                misconception_classifier=components.classifier,
                study_plan_scanner=components.plan_scanner,
                lesson_factory=components.lesson_factory,
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
        print(
            f"Practice model: {components.practice_model}; class-material scanner: "
            f"{components.scanner_model}"
        )
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
