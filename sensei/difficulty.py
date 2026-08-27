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
        "Require multi-step reasoning, less obvious setup, and a deliberate choice "
        "between plausible methods while staying inside the requested topic."
    ),
    "expert": (
        "Create the most demanding reasonable problem for this topic: combine its "
        "ideas, include a subtle edge case or constraint, and provide minimal "
        "scaffolding without leaving the requested scope."
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
