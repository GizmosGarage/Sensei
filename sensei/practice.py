"""Learner-directed practice generation and locally checked answer contracts."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, Collection, Mapping

from sensei.difficulty import difficulty_instruction, normalize_difficulty
from sensei.providers import ChatProvider
from sensei.verification import (
    CalculusVerifier,
    VerificationKind,
    VerificationResult,
    VerificationStatus,
)


EXACT_VERIFIER_VERSION = "sensei-answer-key-1"
ANSWER_TYPES = {"expression", "multiple_choice"}
MAX_SOLUTION_CHARACTERS = 4_000
PRACTICE_FIELDS = {
    "title",
    "prompt",
    "answer_type",
    "answer",
    "options",
    "hint",
    "solution",
}


class PracticeGenerationError(ValueError):
    """Raised when model output cannot satisfy the safe practice contract."""


def problem_fingerprint(prompt: str) -> str:
    """Normalize superficial formatting so recent problem repeats are detectable."""

    return re.sub(r"[^a-z0-9]+", " ", prompt.casefold()).strip()


def _json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE
    )
    if fenced:
        stripped = fenced.group(1)
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise PracticeGenerationError(f"invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise PracticeGenerationError("practice output must be a JSON object")
    return document


def _text(
    document: Mapping[str, object], field: str, *, maximum: int
) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PracticeGenerationError(f"{field} must be non-empty text")
    value = value.strip()
    if len(value) > maximum:
        raise PracticeGenerationError(f"{field} exceeds {maximum} characters")
    return value


@dataclass(frozen=True)
class AdaptiveQuest:
    """A model-authored quest whose answer can be checked without another model call."""

    id: str
    skill_id: str
    subject: str
    topic: str
    difficulty: str
    title: str
    prompt: str
    answer_type: str
    answer: str
    options: tuple[str, ...]
    hint: str
    solution: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "skill_name": self.topic,
            "course": self.subject,
            "subject": self.subject,
            "difficulty": self.difficulty,
            "title": self.title,
            "prompt": self.prompt,
            "answer_type": self.answer_type,
            "options": list(self.options),
            "hint": self.hint,
            "check_kind": "adaptive",
            "source": "adaptive",
        }

    def check(self, submitted: str) -> VerificationResult:
        submitted = submitted.strip()
        if not submitted:
            raise ValueError("Enter an answer before checking the quest.")
        if self.answer_type == "expression":
            return CalculusVerifier().equivalent(self.answer, submitted)

        expected_index = ord(self.answer) - ord("A")
        normalized = submitted.upper().strip().rstrip(".)")
        if normalized in {"A", "B", "C", "D"}:
            selected = normalized
        else:
            matches = [
                index
                for index, option in enumerate(self.options)
                if option.casefold().strip() == submitted.casefold().strip()
            ]
            selected = chr(ord("A") + matches[0]) if len(matches) == 1 else ""
        correct = selected == self.answer
        expected = f"{self.answer}. {self.options[expected_index]}"
        return VerificationResult(
            kind=VerificationKind.EQUIVALENT,
            status=(
                VerificationStatus.VERIFIED_CORRECT
                if correct
                else VerificationStatus.VERIFIED_INCORRECT
            ),
            submitted=submitted,
            expected=expected,
            detail=(
                "The selected option matches the validated answer key."
                if correct
                else "The selected option does not match the validated answer key."
            ),
            verifier_version=EXACT_VERIFIER_VERSION,
        )


def parse_adaptive_quest(
    text: str,
    *,
    skill: Mapping[str, object],
) -> AdaptiveQuest:
    document = _json_object(text)
    if set(document) != PRACTICE_FIELDS:
        raise PracticeGenerationError(
            f"fields must be exactly {sorted(PRACTICE_FIELDS)}"
        )
    answer_type = _text(document, "answer_type", maximum=40)
    if answer_type not in ANSWER_TYPES:
        raise PracticeGenerationError(
            "answer_type must be expression or multiple_choice"
        )
    answer = _text(document, "answer", maximum=300)
    raw_options = document["options"]
    if not isinstance(raw_options, list) or not all(
        isinstance(option, str) and option.strip() for option in raw_options
    ):
        raise PracticeGenerationError("options must be a list of non-empty strings")
    options = tuple(str(option).strip() for option in raw_options)
    if answer_type == "multiple_choice":
        if len(options) != 4 or answer not in {"A", "B", "C", "D"}:
            raise PracticeGenerationError(
                "multiple-choice quests need four options and an A-D answer"
            )
    elif options:
        raise PracticeGenerationError("expression quests must use an empty option list")

    quest = AdaptiveQuest(
        id=f"adaptive-{skill['id']}-{secrets.token_hex(6)}",
        skill_id=str(skill["id"]),
        subject=str(skill["course"]),
        topic=str(skill["name"]),
        difficulty=normalize_difficulty(str(skill["difficulty"])),
        title=_text(document, "title", maximum=100),
        prompt=_text(document, "prompt", maximum=1_000),
        answer_type=answer_type,
        answer=answer,
        options=options,
        hint=_text(document, "hint", maximum=500),
        solution=_text(
            document,
            "solution",
            maximum=MAX_SOLUTION_CHARACTERS,
        ),
    )
    if answer_type == "expression":
        result = quest.check(answer)
        if result.status is not VerificationStatus.VERIFIED_CORRECT:
            raise PracticeGenerationError("the expression answer could not be parsed")
    return quest


class AdaptiveQuestFactory:
    """Uses a local model to draft and independently review one focused quest."""

    def __init__(
        self,
        provider: ChatProvider,
        *,
        validation_attempts: int = 3,
    ) -> None:
        if validation_attempts < 1:
            raise ValueError("validation_attempts must be positive")
        self.provider = provider
        self.validation_attempts = validation_attempts

    @staticmethod
    def _request(
        skill: Mapping[str, object],
        repair: str,
        *,
        variation_key: str,
        avoid_prompts: Collection[str],
    ) -> list[dict[str, str]]:
        context = str(skill.get("description") or "No additional source material.")
        difficulty = difficulty_instruction(str(skill["difficulty"]))
        recent = "\n".join(
            f"{index}. {prompt}"
            for index, prompt in enumerate(tuple(avoid_prompts)[-8:], start=1)
        )
        if not recent:
            recent = "None yet."
        return [
            {
                "role": "system",
                "content": (
                    "You are Sensei's practice architect. Create exactly one accurate, "
                    "standalone practice problem confined to the learner's requested "
                    "subject and topic. Return only JSON with exactly these fields: "
                    "title, prompt, answer_type, answer, options, hint, solution. "
                    "Use answer_type=expression for a numeric or symbolic result; the "
                    "answer must use plain restricted math syntax such as 3/4, x^2, "
                    "sqrt(2), or 6.02*10^23, and options must be []. Tell the learner "
                    "in the prompt to enter only the requested value when units apply. "
                    "Use answer_type=multiple_choice for conceptual, formula-name, or "
                    "chemistry-notation questions; provide exactly four plain options "
                    "and make answer exactly A, B, C, or D. Include one useful hint and "
                    "a concise worked solution. Keep the title under 80 characters, "
                    "the problem under 700 characters, the hint under 250 characters, "
                    "and the solution under 1,200 characters. Do not use trick "
                    "questions, ambiguous rounding, or facts that require current "
                    "events. Every encounter "
                    "must be materially new: vary the underlying function, graph "
                    "features, given values, requested direction, or reasoning task, "
                    "not merely the title or wording. For a graphical topic, give an "
                    "unambiguous textual description of the graph or a compact value "
                    "table because no image is attached. Match the requested problem "
                    "difficulty exactly; do not silently make it easier or harder."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Subject: {skill['course']}\n"
                    f"Topic: {skill['name']}\n"
                    f"Problem difficulty: {difficulty}\n"
                    f"Learner material or emphasis: {context}\n"
                    f"Internal variation key (never mention this): {variation_key}\n"
                    "Do not repeat or paraphrase any recently issued problem below.\n"
                    f"Recently issued problems:\n{recent}\n"
                    f"{repair}"
                ),
            },
        ]

    def _review(self, skill: Mapping[str, object], quest: AdaptiveQuest) -> str | None:
        draft = {
            "title": quest.title,
            "prompt": quest.prompt,
            "answer_type": quest.answer_type,
            "answer": quest.answer,
            "options": list(quest.options),
            "hint": quest.hint,
            "solution": quest.solution,
        }
        result = self.provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Act as a strict independent teacher reviewing a generated "
                        "practice problem. Recompute the answer. Check that the prompt "
                        "is unambiguous, the keyed answer and solution agree, and the "
                        "problem stays inside the requested subject and topic. Confirm "
                        "that its number of steps, setup, scaffolding, and conceptual "
                        "depth match the requested difficulty. Return only JSON with "
                        "exactly two fields: approved (boolean) and reason (a short "
                        "string)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Requested subject: {skill['course']}\n"
                        f"Requested topic: {skill['name']}\n"
                        "Requested problem difficulty: "
                        f"{difficulty_instruction(str(skill['difficulty']))}\n"
                        f"Draft: {json.dumps(draft, ensure_ascii=False)}"
                    ),
                },
            ]
        )
        review = _json_object(result.text)
        if set(review) != {"approved", "reason"}:
            raise PracticeGenerationError(
                "review fields must be exactly approved and reason"
            )
        approved = review["approved"]
        reason = review["reason"]
        if not isinstance(approved, bool) or not isinstance(reason, str):
            raise PracticeGenerationError("review approval has an invalid shape")
        return None if approved else reason.strip() or "The draft was not approved."

    def generate(
        self,
        skill: Mapping[str, object],
        *,
        avoid_prompts: Collection[str] = (),
    ) -> AdaptiveQuest:
        repair = ""
        last_error = "The local model did not return a usable quest."
        avoided = {
            fingerprint
            for prompt in avoid_prompts
            if (fingerprint := problem_fingerprint(prompt))
        }
        for _ in range(self.validation_attempts):
            try:
                result = self.provider.complete(
                    self._request(
                        skill,
                        repair,
                        variation_key=secrets.token_hex(12),
                        avoid_prompts=avoid_prompts,
                    )
                )
                quest = parse_adaptive_quest(result.text, skill=skill)
                if problem_fingerprint(quest.prompt) in avoided:
                    raise PracticeGenerationError(
                        "the problem repeats a recent encounter; change its underlying "
                        "function, values, graph features, or requested reasoning"
                    )
                review_issue = self._review(skill, quest)
                if review_issue is None:
                    return quest
                last_error = review_issue
            except PracticeGenerationError as error:
                last_error = str(error)
            repair = (
                "The prior draft was rejected. Correct this issue in a completely "
                f"new problem: {last_error}"
            )
        raise PracticeGenerationError(
            f"Sensei could not validate a fresh quest: {last_error}"
        )
