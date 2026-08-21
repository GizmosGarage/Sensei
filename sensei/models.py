"""Pinned local-model catalog access."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "config" / "model_candidates.json"
DEFAULT_MODELS_DIRECTORY = REPOSITORY_ROOT / "models"
DEFAULT_MODEL_ID = "qwen-3.5-9b-q4-k-m"
FAST_MODEL_ID = "qwen-3.5-4b-q4-k-m"


@dataclass(frozen=True)
class ModelCandidate:
    """A model artifact pinned by the public manifest."""

    model_id: str
    vendor: str
    filename: str
    revision: str
    quantization: str
    license: str
    size_bytes: int
    sha256: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ModelCandidate":
        return cls(
            model_id=record["id"],
            vendor=record["vendor"],
            filename=record["filename"],
            revision=record["revision"],
            quantization=record["quantization"],
            license=record["license"],
            size_bytes=int(record["size_bytes"]),
            sha256=record["sha256"],
        )


class ModelCatalog:
    """Loads and validates model choices from the pinned manifest."""

    def __init__(self, candidates: dict[str, ModelCandidate]) -> None:
        self._candidates = candidates

    @classmethod
    def load(cls, manifest_path: Path = DEFAULT_MANIFEST) -> "ModelCatalog":
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError("Unsupported model manifest schema version.")
        candidates = {
            record["id"]: ModelCandidate.from_record(record)
            for record in document["models"]
        }
        if not candidates:
            raise ValueError("The model manifest contains no candidates.")
        return cls(candidates)

    def get(self, model_id: str) -> ModelCandidate:
        try:
            return self._candidates[model_id]
        except KeyError as error:
            available = ", ".join(sorted(self._candidates))
            raise ValueError(
                f"Unknown model ID {model_id!r}. Available IDs: {available}"
            ) from error

    def ids(self) -> tuple[str, ...]:
        return tuple(self._candidates)


def model_path(candidate: ModelCandidate, models_directory: Path) -> Path:
    """Return a candidate path while preventing filenames from escaping the directory."""

    directory = models_directory.resolve()
    path = (directory / candidate.filename).resolve()
    if path.parent != directory:
        raise ValueError(f"Unsafe model filename in manifest: {candidate.filename!r}")
    return path
