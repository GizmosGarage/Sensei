"""Turn a transient homework, exam, or textbook page into reviewable class material."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sensei.practice import normalize_display_notation
from sensei.storage import (
    MATERIAL_KINDS,
    MAX_MATERIAL_CHARACTERS,
    MAX_SOURCE_LABEL_CHARACTERS,
)


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 200 * 1024
PROPOSAL_FIELDS = {"kind", "body", "solution", "source_label"}
IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
SUPPORTED_MEDIA_TYPES = ("application/pdf", *IMAGE_MEDIA_TYPES, "text/plain")
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


class MaterialScanError(ValueError):
    """Raised when a page or the scanner response cannot become class material."""


@dataclass(frozen=True)
class MaterialProposal:
    kind: str
    body: str
    solution: str | None
    source_label: str

    def public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "body": self.body,
            "solution": self.solution,
            "source_label": self.source_label,
        }


def clean_material_text(value: object, field: str, *, required: bool) -> str:
    """Normalize scanner text: line endings, trailing space, notation escapes."""

    if value is None:
        value = ""
    if not isinstance(value, str):
        raise MaterialScanError(f"Scanner field {field!r} must be text.")
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned = "\n".join(line.rstrip() for line in lines).strip()
    if required and not cleaned:
        raise MaterialScanError(f"Scanner field {field!r} cannot be empty.")
    if len(cleaned) > MAX_MATERIAL_CHARACTERS:
        raise MaterialScanError(
            f"Scanner field {field!r} must be {MAX_MATERIAL_CHARACTERS} characters or fewer."
        )
    return normalize_display_notation(cleaned) if cleaned else cleaned


def proposal_from_mapping(raw: object) -> MaterialProposal:
    """Validate one scanned material object."""

    if not isinstance(raw, Mapping) or set(raw) != PROPOSAL_FIELDS:
        raise MaterialScanError(
            f"Every scanned material must have exactly {sorted(PROPOSAL_FIELDS)}."
        )
    kind = raw["kind"]
    if kind not in MATERIAL_KINDS:
        raise MaterialScanError(
            "Scanned material kind must be example_problem, worked_example, or notes."
        )
    body = clean_material_text(raw["body"], "body", required=True)
    solution = clean_material_text(raw["solution"], "solution", required=False) or None
    source_label = " ".join(str(raw["source_label"] or "").split())
    if len(source_label) > MAX_SOURCE_LABEL_CHARACTERS:
        raise MaterialScanError(
            f"Scanner source labels must be {MAX_SOURCE_LABEL_CHARACTERS} "
            "characters or fewer."
        )
    return MaterialProposal(str(kind), body, solution, source_label)


def json_document(text: str, *, error: type[ValueError]) -> dict[str, object]:
    """Decode one JSON object from model output, tolerating a code fence."""

    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        document = json.loads(candidate)
    except json.JSONDecodeError as problem:
        raise error(f"Scanner output is not valid JSON: {problem}") from problem
    if not isinstance(document, dict):
        raise error("Scanner output must be one JSON object.")
    return document


def validate_media(media_bytes: bytes, *, filename: str, media_type: str) -> str:
    """Check the upload's type, magic bytes, and size; return a safe filename."""

    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise MaterialScanError(
            "Unsupported file type. Upload a PDF, a PNG, JPEG, or WebP image, or "
            "paste plain text."
        )
    if not media_bytes:
        raise MaterialScanError("The uploaded file is empty.")
    if media_type == "application/pdf":
        if not media_bytes.startswith(_MAGIC_PREFIXES[media_type]):
            raise MaterialScanError("The selected file is not a valid PDF.")
        if len(media_bytes) > MAX_PDF_BYTES:
            raise MaterialScanError("PDF files must be 20 MB or smaller.")
    elif media_type in IMAGE_MEDIA_TYPES:
        valid_prefix = media_bytes.startswith(_MAGIC_PREFIXES[media_type])
        if media_type == "image/webp":
            valid_prefix = valid_prefix and media_bytes[8:12] == b"WEBP"
        if not valid_prefix:
            raise MaterialScanError("The selected file is not a valid image.")
        if len(media_bytes) > MAX_IMAGE_BYTES:
            raise MaterialScanError("Images must be 8 MB or smaller.")
    else:
        if len(media_bytes) > MAX_TEXT_BYTES:
            raise MaterialScanError("Pasted text must be 200 KB or smaller.")
        try:
            decoded = media_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MaterialScanError("Pasted text must be UTF-8 text.") from error
        if not decoded.strip():
            raise MaterialScanError("Pasted text is empty.")
    safe_filename = Path(filename).name.strip()
    if not safe_filename or len(safe_filename) > 160:
        raise MaterialScanError("The file name is invalid or too long.")
    return safe_filename


def media_content_block(
    media_bytes: bytes, *, filename: str, media_type: str
) -> dict[str, object]:
    """Build the Responses API content block that carries the study material."""

    if media_type == "application/pdf":
        encoded = base64.b64encode(media_bytes).decode("ascii")
        return {
            "type": "input_file",
            "filename": filename,
            "file_data": f"data:application/pdf;base64,{encoded}",
        }
    if media_type in IMAGE_MEDIA_TYPES:
        encoded = base64.b64encode(media_bytes).decode("ascii")
        return {
            "type": "input_image",
            "image_url": f"data:{media_type};base64,{encoded}",
            "detail": "high",
        }
    return {
        "type": "input_text",
        "text": "Study material (pasted text):\n" + media_bytes.decode("utf-8"),
    }
