"""Learner-directed practice generation and locally checked answer contracts."""

from __future__ import annotations

import json
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, Collection, Mapping

from sensei.difficulty import difficulty_instruction, normalize_difficulty
from sensei.providers import ChatProvider, ProviderError
from sensei.verification import (
    CalculusVerifier,
    VerificationKind,
    VerificationResult,
    VerificationStatus,
)


EXACT_VERIFIER_VERSION = "sensei-answer-key-1"
ANSWER_TYPES = {"expression", "multiple_choice"}
MAX_SOLUTION_CHARACTERS = 1_600
BASE_PRACTICE_FIELDS = {
    "title",
    "prompt",
    "answer_type",
    "answer",
    "options",
    "hint",
    "solution",
}
PRACTICE_FIELDS = BASE_PRACTICE_FIELDS | {"graph"}
GRAPH_FIELDS = {
    "x_min",
    "x_max",
    "y_min",
    "y_max",
    "curves",
    "points",
    "description",
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


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PracticeGenerationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise PracticeGenerationError(f"{field} must be a finite number")
    return number


def _graph_topic(skill: Mapping[str, object]) -> bool:
    """Return whether the requested topic requires a learner-readable graph."""

    topic = str(skill.get("name") or "").casefold()
    return "graph" in topic


def _graph_limit_topic(skill: Mapping[str, object]) -> bool:
    topic = str(skill.get("name") or "").casefold()
    return "graph" in topic and "limit" in topic


def _concise_graph_limit_prompt(prompt: str, answer_type: str) -> str:
    target = re.search(
        r"\bx\s*(?:approaches|->|→)\s*"
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+|pi(?:\s*/\s*\d+)?))",
        prompt,
        re.I,
    )
    if target is None:
        target = re.search(
            r"\blimit\b[^.?!]{0,80}?\bat\s+x\s*=\s*"
            r"([+-]?(?:\d+(?:\.\d+)?|\.\d+|pi(?:\s*/\s*\d+)?))",
            prompt,
            re.I,
        )
    if target is None:
        raise PracticeGenerationError(
            "a graphical-limit prompt must state the target x-value"
        )
    point = re.sub(r"\s+", "", target.group(1))
    lowered = prompt.casefold()
    mentions_left = "from the left" in lowered or "left-hand" in lowered
    mentions_right = (
        "from the right" in lowered
        or "right-hand" in lowered
        or "right side" in lowered
    )
    if "two-sided" in lowered or (mentions_left and mentions_right):
        direction = ""
    elif mentions_left:
        direction = " from the left"
    elif mentions_right:
        direction = " from the right"
    else:
        direction = ""
    instruction = (
        "Choose the best answer."
        if answer_type == "multiple_choice"
        else "Enter only the value of the limit."
    )
    return (
        "Use the displayed graph to determine the limit of f(x) as x approaches "
        f"{point}{direction}. {instruction}"
    )


@dataclass(frozen=True)
class GraphSpec:
    """Validated, presentation-only coordinate graph data."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    curves: tuple[tuple[tuple[float, float], ...], ...]
    points: tuple[tuple[float, float, str], ...]
    description: str

    def public_dict(self) -> dict[str, object]:
        return {
            "x_min": self.x_min,
            "x_max": self.x_max,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "curves": [
                [[x, y] for x, y in curve]
                for curve in self.curves
            ],
            "points": [
                {"x": x, "y": y, "type": point_type}
                for x, y, point_type in self.points
            ],
            "description": self.description,
        }


def _parse_graph(document: Mapping[str, object]) -> GraphSpec | None:
    raw_graph = document.get("graph")
    if raw_graph is None:
        return None
    if not isinstance(raw_graph, dict) or set(raw_graph) != GRAPH_FIELDS:
        raise PracticeGenerationError(
            f"graph fields must be exactly {sorted(GRAPH_FIELDS)}"
        )

    x_min = _number(raw_graph["x_min"], "graph.x_min")
    x_max = _number(raw_graph["x_max"], "graph.x_max")
    y_min = _number(raw_graph["y_min"], "graph.y_min")
    y_max = _number(raw_graph["y_max"], "graph.y_max")
    if not x_min < x_max or not y_min < y_max:
        raise PracticeGenerationError("graph axis minimums must be below their maximums")

    raw_curves = raw_graph["curves"]
    if not isinstance(raw_curves, list) or not 1 <= len(raw_curves) <= 6:
        raise PracticeGenerationError("graph.curves must contain from 1 to 6 curves")
    curves: list[tuple[tuple[float, float], ...]] = []
    for curve_index, raw_curve in enumerate(raw_curves):
        if not isinstance(raw_curve, list) or not 2 <= len(raw_curve) <= 24:
            raise PracticeGenerationError(
                "each graph curve must contain from 2 to 24 coordinate pairs"
            )
        curve: list[tuple[float, float]] = []
        for point_index, raw_point in enumerate(raw_curve):
            if not isinstance(raw_point, list) or len(raw_point) != 2:
                raise PracticeGenerationError(
                    "each graph curve coordinate must be a two-number list"
                )
            x = _number(
                raw_point[0],
                f"graph.curves[{curve_index}][{point_index}][0]",
            )
            y = _number(
                raw_point[1],
                f"graph.curves[{curve_index}][{point_index}][1]",
            )
            curve.append((x, y))
        curves.append(tuple(curve))

    raw_points = raw_graph["points"]
    if not isinstance(raw_points, list) or len(raw_points) > 12:
        raise PracticeGenerationError("graph.points must contain at most 12 markers")
    points: list[tuple[float, float, str]] = []
    for index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, dict) or set(raw_point) != {"x", "y", "type"}:
            raise PracticeGenerationError(
                "each graph marker needs exactly x, y, and type"
            )
        x = _number(raw_point["x"], f"graph.points[{index}].x")
        y = _number(raw_point["y"], f"graph.points[{index}].y")
        point_type = raw_point["type"]
        if not isinstance(point_type, str) or point_type not in {"open", "closed"}:
            raise PracticeGenerationError("graph marker type must be open or closed")
        points.append((x, y, str(point_type)))

    plotted = [coordinate for curve in curves for coordinate in curve]
    plotted.extend((x, y) for x, y, _ in points)
    x_min = min(x_min, *(x for x, _ in plotted))
    x_max = max(x_max, *(x for x, _ in plotted))
    y_min = min(y_min, *(y for _, y in plotted))
    y_max = max(y_max, *(y for _, y in plotted))
    if not 1e-6 <= x_max - x_min <= 1_000:
        raise PracticeGenerationError("graph x-axis span must be from 0.000001 to 1,000")
    if not 1e-6 <= y_max - y_min <= 1_000:
        raise PracticeGenerationError("graph y-axis span must be from 0.000001 to 1,000")

    description = raw_graph["description"]
    if not isinstance(description, str) or not description.strip():
        raise PracticeGenerationError("graph.description must be non-empty text")
    description = description.strip()
    if len(description) > 500:
        raise PracticeGenerationError("graph.description exceeds 500 characters")
    return GraphSpec(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        curves=tuple(curves),
        points=tuple(points),
        description=description,
    )


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
    graph: GraphSpec | None = None

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
            "graph": self.graph.public_dict() if self.graph else None,
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


def adaptive_quest_fingerprint(quest: AdaptiveQuest) -> str:
    """Identify the learner-visible task, including graph data when present."""

    if quest.graph is None:
        return problem_fingerprint(quest.prompt)
    return json.dumps(
        {
            "prompt": problem_fingerprint(quest.prompt),
            "graph": quest.graph.public_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def parse_adaptive_quest(
    text: str,
    *,
    skill: Mapping[str, object],
) -> AdaptiveQuest:
    document = _json_object(text)
    if frozenset(document) not in {
        frozenset(BASE_PRACTICE_FIELDS),
        frozenset(PRACTICE_FIELDS),
    }:
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

    graph = _parse_graph(document)
    if _graph_topic(skill) and graph is None:
        raise PracticeGenerationError(
            "graphical topics require structured graph data, not a text-only description"
        )
    prompt = _text(document, "prompt", maximum=1_000)
    if graph is not None and _graph_limit_topic(skill):
        prompt = _concise_graph_limit_prompt(prompt, answer_type)
    if graph is not None and re.search(r"\bgraph\s+description\s*:", prompt, re.I):
        raise PracticeGenerationError(
            "the prompt must not repeat the rendered graph as a Graph Description"
        )
    if (
        graph is not None
        and not _graph_limit_topic(skill)
        and re.search(r"\bf\s*\(\s*x\s*\)\s*=", prompt, re.I)
    ):
        raise PracticeGenerationError(
            "a graph-reading prompt must not reveal the plotted function formula"
        )
    coordinate_pairs = re.findall(
        r"\(\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*,\s*"
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*\)",
        prompt,
    )
    if graph is not None and not _graph_limit_topic(skill) and coordinate_pairs:
        raise PracticeGenerationError(
            "a graph-reading prompt must not repeat plotted coordinates"
        )

    quest = AdaptiveQuest(
        id=f"adaptive-{skill['id']}-{secrets.token_hex(6)}",
        skill_id=str(skill["id"]),
        subject=str(skill["course"]),
        topic=str(skill["name"]),
        difficulty=normalize_difficulty(str(skill["difficulty"])),
        title=_text(document, "title", maximum=100),
        prompt=prompt,
        answer_type=answer_type,
        answer=answer,
        options=options,
        hint=_text(document, "hint", maximum=500),
        solution=_text(
            document,
            "solution",
            maximum=MAX_SOLUTION_CHARACTERS,
        ),
        graph=graph,
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
                    "title, prompt, answer_type, answer, options, hint, solution, "
                    "graph. "
                    "Use answer_type=expression for a numeric or symbolic result; the "
                    "answer must use plain restricted math syntax such as 3/4, x^2, "
                    "sqrt(2), or 6.02*10^23, and options must be []. Tell the learner "
                    "in the prompt to enter only the requested value when units apply. "
                    "Use answer_type=multiple_choice for conceptual, formula-name, or "
                    "chemistry-notation questions; provide exactly four plain options "
                    "and make answer exactly A, B, C, or D. Include one useful hint and "
                    "a concise worked solution. Do not restate the prompt or repeat "
                    "the same facts across the prompt, hint, and solution. Keep the "
                    "title under 80 characters, "
                    "the problem under 700 characters, the hint under 250 characters, "
                    "and the solution under 700 characters. Do not use trick "
                    "questions, ambiguous rounding, or facts that require current "
                    "events. Every encounter "
                    "must be materially new: vary the underlying function, graph "
                    "features, given values, requested direction, or reasoning task, "
                    "not merely the title or wording. Set graph to null unless the "
                    "learner must read a coordinate graph. For every graphical topic, "
                    "graph is required and must be "
                    "{x_min,x_max,y_min,y_max,curves,points,description}. curves is "
                    "a list of 1-6 polylines, each a list of 2-24 [x,y] pairs. points "
                    "is a list of {x,y,type} markers where type is open or closed. "
                    "description is concise accessibility text. Keep all coordinates "
                    "inside the axes. Ask the learner to use the displayed graph. The "
                    "visible prompt may name the target x-value but must not repeat "
                    "the plotted points, reveal the function formula, include a value "
                    "table, or add a 'Graph Description'. A valid straight-line graph "
                    "example is graph={\"x_min\":-5,\"x_max\":5,\"y_min\":-5,"
                    "\"y_max\":5,\"curves\":[[[-5,-3],[0,2],[5,4]]],"
                    "\"points\":[{\"x\":0,\"y\":2,\"type\":\"open\"}],"
                    "\"description\":\"A curve with an open point at (0, 2).\"}. "
                    "Match the requested problem "
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
            "graph": quest.graph.public_dict() if quest.graph else None,
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
                        "depth match the requested difficulty. For numeric answers, "
                        "answer_type=expression is required and is not an error. For "
                        "graphical limits, treat the structured graph as the displayed "
                        "source of truth; an open marker at the target x-value is a "
                        "normal way to test a limit and does not conflict with the "
                        "approaching curve. Return only JSON with "
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
        avoid_fingerprints: Collection[str] = (),
    ) -> AdaptiveQuest:
        repair = ""
        last_error = "The local model did not return a usable quest."
        avoided = {
            fingerprint
            for prompt in avoid_prompts
            if (fingerprint := problem_fingerprint(prompt))
        }
        avoided_quests = set(avoid_fingerprints)
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
                repeats_graph = (
                    quest.graph is not None
                    and adaptive_quest_fingerprint(quest) in avoided_quests
                )
                repeats_text = (
                    quest.graph is None
                    and problem_fingerprint(quest.prompt) in avoided
                )
                if repeats_graph or repeats_text:
                    raise PracticeGenerationError(
                        "the problem repeats a recent encounter; change its underlying "
                        "function, values, graph features, or requested reasoning"
                    )
                review_issue = self._review(skill, quest)
                if review_issue is None:
                    return quest
                last_error = review_issue
            except (PracticeGenerationError, ProviderError) as error:
                last_error = str(error)
            repair = (
                "The prior draft was rejected. Correct this issue in a completely "
                f"new problem: {last_error}"
            )
        raise PracticeGenerationError(
            f"Sensei could not validate a fresh quest: {last_error}"
        )
