"""Sanitize learner-visible model text."""

import re


def student_facing_text(text: str) -> str:
    """Remove tagged reasoning if a provider returns it despite the prompt policy."""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if re.search(r"<think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"<think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("The model returned no safe student-facing text.")
    return cleaned
