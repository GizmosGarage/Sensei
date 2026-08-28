"""Shared problem-difficulty vocabulary and generation guidance."""

from __future__ import annotations


DIFFICULTY_LEVELS = (
    "beginner",
    "intermediate",
    "advanced",
    "expert",
)

DIFFICULTY_LABELS = {
    "beginner": "Beginner",
    "intermediate": "Intermediate",
    "advanced": "Advanced",
    "expert": "Expert",
}

DIFFICULTY_GUIDANCE = {
    "beginner": (
        "Use the topic's most essential concept in one direct step, with familiar "
        "values, explicit instructions, and no combined subskills."
    ),
    "intermediate": (
        "Use a standard application requiring two or three connected steps and a "
        "clear choice of the relevant rule or method."
    ),
    "advanced": (
        "Require multi-step reasoning with at least three linked solution stages, a "
        "less obvious setup or method choice, and limited scaffolding while staying "
        "inside the requested topic."
    ),
    "expert": (
        "Create the most demanding reasonable problem for this topic: combine its "
        "ideas, include a subtle edge case or constraint, and provide minimal "
        "scaffolding without leaving the requested scope."
    ),
}

DIFFICULTY_DESIGN_CONTRACTS = {
    "beginner": (
        "Require one substantive inference or operation. State the needed method or "
        "relationship directly, and do not make formatting or unit notation part of "
        "the challenge."
    ),
    "intermediate": (
        "Require two or three linked substantive inferences or operations, where an "
        "early result is needed later. Do not count answer formatting, routine "
        "arithmetic cleanup, or a gratuitous unit conversion as an extra step. Design "
        "backward from a solution with two or three explicit substantive steps. A "
        "required unit or representation conversion that feeds a different topic "
        "calculation is substantive rather than gratuitous."
    ),
    "advanced": (
        "Require at least three linked solution stages and do not state the complete "
        "method in the prompt. Recognizing a needed method, applying its key "
        "transformation, and using the simplified result may count as distinct stages; "
        "do not collapse them merely because the method is standard. A single formula "
        "substitution or long routine arithmetic does not qualify. Design backward "
        "from a solution with at least three explicit stages."
    ),
    "expert": (
        "Require at least four linked substantive inferences or operations, combine "
        "two ideas that genuinely belong to the topic, and make a subtle constraint "
        "or edge case affect the solution. Keep the final task unambiguous and "
        "solvable from the supplied information. Design backward from a concise "
        "solution with at least four explicit substantive steps."
    ),
}

LEGACY_DIFFICULTIES = {
    "foundation": "beginner",
    "adaptive": "intermediate",
    "challenge": "advanced",
}


def normalize_difficulty(value: str) -> str:
    """Return one canonical four-level difficulty, accepting old saved labels."""

    normalized = LEGACY_DIFFICULTIES.get(value.strip().casefold(), value.strip().casefold())
    if normalized not in DIFFICULTY_LEVELS:
        labels = ", ".join(DIFFICULTY_LABELS[level] for level in DIFFICULTY_LEVELS)
        raise ValueError(f"Problem difficulty must be one of: {labels}.")
    return normalized


def difficulty_instruction(value: str) -> str:
    """Describe the requested level precisely enough for a local model to follow."""

    difficulty = normalize_difficulty(value)
    position = DIFFICULTY_LEVELS.index(difficulty) + 1
    return (
        f"{DIFFICULTY_LABELS[difficulty]} (level {position} of 4): "
        f"{DIFFICULTY_GUIDANCE[difficulty]}"
    )


def difficulty_design_contract(value: str) -> str:
    """Return an observable construction target for generation and review."""

    difficulty = normalize_difficulty(value)
    return DIFFICULTY_DESIGN_CONTRACTS[difficulty]
