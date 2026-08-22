"""Problem-scoped tutoring session and context policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Sequence

from sensei.providers import ChatProvider, CompletionResult, Message, TokenCallback

if TYPE_CHECKING:
    from sensei.quests import QuestTemplate
    from sensei.verification import VerificationResult


SYSTEM_PROMPT = """You are Sensei, a patient college calculus tutor.
Teach the student how to reason instead of merely producing answers.
Use concise steps and clear mathematical notation suitable for a terminal.
Diagnose the student's specific mistake when they show work.
Ask one useful question at a time when coaching.
Honor the requested help mode exactly.
Never expose hidden reasoning, response planning, self-critique, or internal analysis.
Do not claim that the student's answer is correct unless you have checked it.
If a request is not about calculus or its prerequisites, briefly redirect to the study goal.
"""


class TutorMode(str, Enum):
    COACH = "coach"
    HINT = "hint"
    SOLVE = "solve"


MODE_INSTRUCTIONS = {
    TutorMode.COACH: (
        "Coach mode: give exactly one small next step, then stop and ask one focused "
        "question. If the student has not shown work, ask them to identify the first "
        "relevant rule or structure without doing calculations for them. Never present "
        "later steps in advance. Do not reveal the final answer unless the student has "
        "made a genuine attempt and explicitly asks for it."
    ),
    TutorMode.HINT: (
        "Hint mode: give exactly one conceptual or procedural hint. Do not calculate "
        "or reveal the final answer. End with one focused question."
    ),
    TutorMode.SOLVE: (
        "Solve mode: provide a complete, correct, step-by-step solution. Explain why "
        "each important step is valid and include a quick final check when practical."
    ),
}

NEW_PROBLEM_REQUESTS = {
    TutorMode.COACH: (
        "I have not shown any work yet. Give exactly one conceptual first step, do "
        "not calculate later steps, and end with one question for me to answer."
    ),
    TutorMode.HINT: (
        "Give exactly one hint for this problem, reveal no final answer, and end with "
        "one question for me to answer."
    ),
    TutorMode.SOLVE: "Give the complete explained solution to this problem.",
}


@dataclass(frozen=True)
class TutorReply:
    text: str
    mode: TutorMode
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class LearningSnapshot:
    """The bounded evidence needed to finalize one problem into learning memory."""

    problem: str
    messages: tuple[Message, ...]
    tutor_turns: int
    hints_used: int
    solution_revealed: bool
    verification: VerificationResult | None = None
    quest_id: str | None = None
    quest_skill_id: str | None = None


def student_facing_text(text: str) -> str:
    """Remove tagged reasoning if a runtime violates the no-reasoning setting."""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if re.search(r"<think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"<think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("The model returned no safe student-facing text.")
    return cleaned


class TutorSession:
    """Maintains bounded context for one active calculus problem."""

    def __init__(
        self,
        provider: ChatProvider,
        model_name: str,
        *,
        history_character_budget: int = 12_000,
    ) -> None:
        if history_character_budget < 1:
            raise ValueError("The history character budget must be positive.")
        self.provider = provider
        self.model_name = model_name
        self.history_character_budget = history_character_budget
        self.problem_statement: str | None = None
        self.learner_context: str | None = None
        self.last_verification: VerificationResult | None = None
        self.active_quest: QuestTemplate | None = None
        self._history: list[Message] = []
        self._mode_counts = {mode: 0 for mode in TutorMode}
        self.turn_count = 0

    def reset(self, problem: str | None = None) -> None:
        self.problem_statement = problem.strip() if problem and problem.strip() else None
        self._history.clear()
        self._mode_counts = {mode: 0 for mode in TutorMode}
        self.last_verification = None
        self.active_quest = None
        self.turn_count = 0

    def _recent_history(self) -> list[Message]:
        selected_turns: list[list[Message]] = []
        used = 0
        turns = [
            self._history[index : index + 2]
            for index in range(0, len(self._history), 2)
        ]
        for turn in reversed(turns):
            cost = sum(len(message["content"]) for message in turn)
            if used + cost > self.history_character_budget:
                break
            selected_turns.append(turn)
            used += cost
        selected_turns.reverse()
        return [message for turn in selected_turns for message in turn]

    def _messages(self, student_message: str, mode: TutorMode) -> list[Message]:
        if self.problem_statement is None:
            raise RuntimeError("A problem must be active before building a request.")
        system_content = (
            f"{SYSTEM_PROMPT.strip()}\n\n"
            f"{MODE_INSTRUCTIONS[mode]}\n\n"
            f"Current problem or study question:\n{self.problem_statement}"
        )
        if self.learner_context:
            system_content += (
                "\n\nRelevant persistent learner context:\n"
                f"{self.learner_context}\n"
                "Use this only when relevant. Adapt instruction without mentioning "
                "scores or stored records unless the student asks."
            )
        if self.last_verification:
            system_content += (
                "\n\nLatest deterministic check (authoritative):\n"
                f"{self.last_verification.learning_summary()}\n"
                "Use this result to target the next explanation."
            )
        return [
            {"role": "system", "content": system_content},
            *self._recent_history(),
            {"role": "user", "content": student_message},
        ]

    def respond(
        self,
        student_message: str,
        mode: TutorMode = TutorMode.COACH,
        *,
        starts_new_problem: bool = False,
        on_token: TokenCallback | None = None,
    ) -> TutorReply:
        student_message = student_message.strip()
        if not student_message:
            raise ValueError("Enter a calculus problem, attempt, or question.")
        if starts_new_problem or self.problem_statement is None:
            self.reset(student_message)
            request_text = NEW_PROBLEM_REQUESTS[mode]
        else:
            request_text = student_message

        result: CompletionResult = self.provider.complete(
            self._messages(request_text, mode), on_token=on_token
        )
        safe_text = student_facing_text(result.text)
        self._history.extend(
            [
                {"role": "user", "content": request_text},
                {"role": "assistant", "content": safe_text},
            ]
        )
        self._mode_counts[mode] += 1
        self.turn_count += 1
        return TutorReply(
            text=safe_text,
            mode=mode,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    def context_messages(self) -> Sequence[Message]:
        """Expose a read-only copy for status reporting and tests."""

        return tuple(dict(message) for message in self._recent_history())

    def learning_snapshot(self) -> LearningSnapshot:
        if self.problem_statement is None or self.turn_count == 0:
            raise RuntimeError("Complete at least one tutor turn before recording it.")
        return LearningSnapshot(
            problem=self.problem_statement,
            messages=tuple(dict(message) for message in self._recent_history()),
            tutor_turns=self.turn_count,
            hints_used=self._mode_counts[TutorMode.HINT],
            solution_revealed=self._mode_counts[TutorMode.SOLVE] > 0,
            verification=self.last_verification,
            quest_id=self.active_quest.id if self.active_quest else None,
            quest_skill_id=(
                self.active_quest.skill_id if self.active_quest else None
            ),
        )

    def set_learner_context(self, context: str | None) -> None:
        self.learner_context = context.strip() if context and context.strip() else None

    def set_verification(self, verification: VerificationResult) -> None:
        if self.problem_statement is None:
            raise RuntimeError("Start a problem before attaching a verification result.")
        self.last_verification = verification

    def set_quest(self, quest: QuestTemplate) -> None:
        if self.problem_statement != quest.prompt:
            raise RuntimeError("The quest must match the active problem.")
        self.active_quest = quest

    @property
    def context_characters(self) -> int:
        return sum(len(message["content"]) for message in self._recent_history())
