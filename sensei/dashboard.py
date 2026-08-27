"""Loopback-only browser dashboard for Sensei's local learning memory."""

from __future__ import annotations

import argparse
import json
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

from sensei.generation import GENERATED_SKILL_IDS, GeneratedQuestFactory
from sensei.learning import LearningEvent, Outcome
from sensei.models import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODELS_DIRECTORY,
    FAST_MODEL_ID,
    ModelCatalog,
    model_path,
)
from sensei.practice import (
    AdaptiveQuest,
    AdaptiveQuestFactory,
    PracticeGenerationError,
    adaptive_quest_fingerprint,
)
from sensei.providers import LlamaCppProvider
from sensei.quests import DEFAULT_QUESTS_PATH, QuestDeck, QuestTemplate
from sensei.runtime import DEFAULT_RUNTIME_DIRECTORY, LocalLlamaRuntime, RuntimeSettings
from sensei.storage import DEFAULT_DATABASE_PATH, DEFAULT_SKILLS_PATH, LearningStore, utc_now
from sensei.verification import (
    CalculusVerifier,
    MathInputError,
    VerificationResult,
    VerificationStatus,
)


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
MAX_REQUEST_BYTES = 4_096
ATTEMPT_TOKEN_LIFETIME_SECONDS = 15 * 60
CHALLENGE_TOKEN_LIFETIME_SECONDS = 60 * 60
ADAPTIVE_PROMPT_HISTORY = 8
ADAPTIVE_DISTINCT_ATTEMPTS = 3
WEB_DIRECTORY = Path(__file__).resolve().parent / "web"
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


def generated_recommendation(
    store: LearningStore,
    skills: list[dict[str, Any]],
    course: str,
) -> dict[str, Any]:
    eligible = {
        str(skill["id"])
        for skill in skills
        if skill["course"] == course and skill["id"] in GENERATED_SKILL_IDS
    }
    review = store.review_recommendation(skill_ids=eligible)
    if review is None:
        starting_skill = (
            "precalc_exponent_properties"
            if course == "precalculus"
            else "calculus_foundations"
        )
        skill = next(item for item in skills if item["id"] == starting_skill)
        due = True
        reason = "Begin your path with a fresh foundation quest."
        mastery_score = 0.0
        mastery_label = "not started"
        next_review_at = None
    else:
        skill = next(item for item in skills if item["id"] == review["id"])
        due = bool(review["due"])
        reason = (
            "Scheduled review is due now."
            if due
            else "This is the next subject in your generated review queue."
        )
        mastery_score = float(review["mastery_score"])
        mastery_label = str(review["mastery_label"])
        next_review_at = str(review["next_review_at"])
    return {
        "id": f"generated-recommendation-{skill['id']}",
        "skill_id": skill["id"],
        "skill_name": skill["name"],
        "course": course,
        "title": f"Fresh {skill['name']} quest",
        "prompt": "Generate a new verifier-backed challenge for this subject.",
        "check_kind": "generated",
        "due": due,
        "reason": reason,
        "mastery_score": mastery_score,
        "mastery_label": mastery_label,
        "next_review_at": next_review_at,
    }


def verification_document(result: VerificationResult) -> dict[str, str | None]:
    return {
        "kind": result.kind.value,
        "status": result.status.value,
        "submitted": result.submitted,
        "expected": result.expected,
        "detail": result.detail,
        "verifier_version": result.verifier_version,
    }


@dataclass(frozen=True)
class PendingAttempt:
    quest: PracticeQuest
    result: VerificationResult
    issued_at: float


class PendingAttemptStore:
    """Keeps checked browser attempts one-time and process-local until recorded."""

    def __init__(self) -> None:
        self._attempts: dict[str, PendingAttempt] = {}
        self._lock = threading.Lock()

    def issue(self, quest: PracticeQuest, result: VerificationResult) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._attempts[token] = PendingAttempt(quest, result, now)
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


@dataclass(frozen=True)
class PendingChallenge:
    quest: PracticeQuest
    issued_at: float


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
    ) -> tuple[str, AdaptiveQuest]:
        if self.adaptive_factory is None:
            raise RuntimeError(
                "Adaptive generation is unavailable. Restart the dashboard with its "
                "local model enabled."
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
            quest = self.adaptive_factory.generate(
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
            recommendations = {
                course: generated_recommendation(store, skills, course)
                for course in ("precalculus", "calculus")
            }
            review = store.review_recommendation()
            return {
                "generated_at": utc_now().astimezone(timezone.utc).isoformat(),
                "profile": profile,
                "next_quest": recommendations["calculus"],
                "next_quests": recommendations,
                "quests": deck.public_quests(),
                "review": review,
                "skills": skills,
                "study_topics": study_topics,
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
                    "model_access": "Local dashboard process",
                    "practice_api_version": 2,
                },
            }

    def create_study_topic(
        self,
        *,
        subject: str,
        topic: str,
        context: str,
        difficulty: str,
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.create_study_topic(
                subject=subject,
                topic=topic,
                context=context,
                difficulty=difficulty,
            )

    def study_topic(self, skill_id: str) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.study_topic(skill_id)

    def study_topic_for_generation(
        self,
        skill_id: str,
        difficulty: str,
    ) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            return store.set_study_topic_difficulty(skill_id, difficulty)

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
            hints_used=0,
            solution_revealed=False,
            tutor_turns=1,
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
    ) -> None:
        self.service = service
        self.csrf_token = secrets.token_urlsafe(32)
        self.challenges = ChallengeStore(quest_factory, adaptive_factory)
        self.adaptive_available = adaptive_factory is not None
        self.pending_attempts = PendingAttemptStore()
        self.assets = {
            path: (asset_path.read_bytes(), content_type)
            for path, (asset_path, content_type) in ASSETS.items()
        }
        super().__init__(server_address, DashboardRequestHandler)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: SenseiDashboardServer

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

    def _read_json(self, expected_fields: set[str]) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            raise ValueError("Requests must use application/json.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ValueError("A valid Content-Length is required.") from error
        if not 1 <= length <= MAX_REQUEST_BYTES:
            raise ValueError(
                f"Request body must be from 1 to {MAX_REQUEST_BYTES} bytes."
            )
        try:
            document = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid UTF-8 JSON.") from error
        if not isinstance(document, dict) or set(document) != expected_fields:
            raise ValueError(
                f"Request fields must be exactly {sorted(expected_fields)}."
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
                self.log_error("Dashboard snapshot failed: %s", error)
                self._send_json(500, {"error": "Dashboard data is unavailable."})
                return
            document["csrf_token"] = self.server.csrf_token
            document["runtime"]["adaptive_generation"] = (
                "ready" if self.server.adaptive_available else "unavailable"
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
            self._send_json(403, {"error": "Local write authorization failed."})
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/study/focus":
                document = self._read_json(
                    {"subject", "topic", "context", "difficulty"}
                )
                if not all(isinstance(value, str) for value in document.values()):
                    raise ValueError("Study-focus fields must be text.")
                skill = self.server.service.create_study_topic(
                    subject=str(document["subject"]),
                    topic=str(document["topic"]),
                    context=str(document["context"]),
                    difficulty=str(document["difficulty"]),
                )
                self._send_json(200, {"study_topic": skill})
                return
            if path == "/api/study/generate":
                document = self._read_json({"skill_id", "difficulty"})
                skill_id = document["skill_id"]
                difficulty = document["difficulty"]
                if (
                    not isinstance(skill_id, str)
                    or len(skill_id) > 80
                    or not isinstance(difficulty, str)
                    or len(difficulty) > 20
                ):
                    raise ValueError(
                        "Study topic ID and problem difficulty must be valid text."
                    )
                skill = self.server.service.study_topic_for_generation(
                    skill_id,
                    difficulty,
                )
                challenge_token, quest = self.server.challenges.issue_adaptive(
                    skill,
                    avoid_prompts=self.server.service.recent_topic_prompts(skill_id),
                )
                self._send_json(
                    200,
                    {
                        "quest": self.server.service.public_adaptive_quest(quest),
                        "challenge_token": challenge_token,
                    },
                )
                return
            if path == "/api/quest/generate":
                document = self._read_json({"skill_id"})
                skill_id = document["skill_id"]
                if not isinstance(skill_id, str) or len(skill_id) > 80:
                    raise ValueError("Skill ID must be valid text.")
                challenge_token, quest = self.server.challenges.issue(skill_id)
                self._send_json(
                    200,
                    {
                        "quest": self.server.service.public_generated_quest(quest),
                        "challenge_token": challenge_token,
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
                quest = self.server.challenges.get(challenge_token)
                result = self.server.service.check_quest(quest, answer)
                attempt_token = (
                    None
                    if result.status is VerificationStatus.INCONCLUSIVE
                    else self.server.pending_attempts.issue(quest, result)
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
                attempt = self.server.pending_attempts.consume(token)
                self._send_json(
                    200,
                    self.server.service.record_attempt(attempt),
                )
                return
        except PracticeGenerationError as error:
            self.log_error("Adaptive generation failed validation: %s", error)
            self._send_json(
                503,
                {
                    "error": (
                        "Sensei could not finish a valid new encounter. "
                        "Please try again."
                    )
                },
            )
            return
        except (MathInputError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
            return
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self.log_error("Dashboard write failed: %s", error)
            message = (
                "Sensei could not generate a new encounter. Please try again."
                if path in {"/api/study/generate", "/api/quest/generate"}
                else "The local attempt could not be recorded."
            )
            self._send_json(500, {"error": message})
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
) -> SenseiDashboardServer:
    if not 0 <= port <= 65_535:
        raise ValueError("Dashboard port must be from 0 to 65535.")
    return SenseiDashboardServer(
        (LOOPBACK_HOST, port),
        service,
        quest_factory,
        adaptive_factory,
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
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument("--model-id", help="Pinned local model ID.")
    model_group.add_argument(
        "--fast",
        action="store_true",
        help=f"Use the lighter adaptive model ({FAST_MODEL_ID}).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Override the pinned model manifest path.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIRECTORY,
        help="Directory containing local GGUF weights.",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIRECTORY,
        help="Directory containing llama-server.exe.",
    )
    parser.add_argument(
        "--server-url",
        help="Use an already-running llama.cpp server.",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Run only the legacy deterministic practice generators.",
    )
    return parser.parse_args(argv)


def _adaptive_factory(
    args: argparse.Namespace,
    stack: ExitStack,
) -> AdaptiveQuestFactory | None:
    if args.no_model:
        return None
    catalog = (
        ModelCatalog.load(args.manifest.resolve())
        if args.manifest
        else ModelCatalog.load()
    )
    selected_id = FAST_MODEL_ID if args.fast else args.model_id or DEFAULT_MODEL_ID
    candidate = catalog.get(selected_id)
    selected_path = model_path(candidate, args.models_dir)
    if args.server_url:
        base_url = args.server_url
    else:
        if not selected_path.is_file():
            raise FileNotFoundError(
                f"Model is missing: {selected_path}. Run scripts/download_models.py "
                f"--model {selected_id}."
            )
        print(
            f"Starting local practice architect {selected_id}; loading may take a moment...",
            file=sys.stderr,
        )
        runtime = LocalLlamaRuntime(
            RuntimeSettings(
                executable=args.runtime_dir.resolve() / "llama-server.exe",
                model_path=selected_path,
                model_alias=selected_id,
            )
        )
        base_url = stack.enter_context(runtime).base_url
    return AdaptiveQuestFactory(
        LlamaCppProvider(base_url, selected_id, seed=-1, max_tokens=1_024)
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with ExitStack() as stack:
        try:
            service = DashboardService(args.database)
            service.state()
            adaptive_factory = _adaptive_factory(args, stack)
            server = create_server(
                service,
                port=args.port,
                adaptive_factory=adaptive_factory,
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            print(f"Dashboard could not start: {error}", file=sys.stderr)
            return 1

        host, port = server.server_address
        url = f"http://{host}:{port}/"
        print(f"Sensei dashboard: {url}")
        print("Learning data and model inference stay on this machine.")
        if not args.no_open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping dashboard.")
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
