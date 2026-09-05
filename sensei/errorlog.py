"""Durable, local structured error records for Sensei."""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ERROR_LOG_PATH = REPOSITORY_ROOT / "data" / "logs" / "study-errors.jsonl"
DEFAULT_MAX_LOG_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10
MAX_CONTEXT_VALUE_CHARACTERS = 2_000


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _error_id(timestamp: str) -> str:
    compact = timestamp.replace("-", "").replace(":", "")
    compact = compact.replace("+0000", "Z").replace("+00:00", "Z")
    return f"SEN-{compact}-{uuid.uuid4().hex[:8].upper()}"


def _safe_context(context: Mapping[str, object] | None) -> dict[str, object]:
    """Keep diagnostic metadata JSON-safe, bounded, and deliberately shallow."""

    if not context:
        return {}
    safe: dict[str, object] = {}
    for key, value in context.items():
        if value is None or isinstance(value, (bool, int, float)):
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)[:MAX_CONTEXT_VALUE_CHARACTERS]
    return safe


class ErrorRecorder:
    """Append error events as independently readable JSON records.

    Recording is best-effort by design: a logging failure is reported to stderr but
    never replaces the application error that the learner actually encountered.
    """

    def __init__(
        self,
        path: Path = DEFAULT_ERROR_LOG_PATH,
        *,
        max_bytes: int = DEFAULT_MAX_LOG_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("Error-log max_bytes must be positive.")
        if backup_count < 0:
            raise ValueError("Error-log backup_count cannot be negative.")
        self.path = path.expanduser().resolve()
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()

    def record_exception(
        self,
        error: BaseException,
        *,
        component: str,
        operation: str,
        context: Mapping[str, object] | None = None,
        severity: str = "ERROR",
    ) -> str:
        """Record an exception and return the learner-visible correlation ID."""

        timestamp = _utc_timestamp()
        error_id = _error_id(timestamp)
        exception = {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "message": str(error),
            "traceback": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
        }
        self._append(
            self._document(
                timestamp=timestamp,
                error_id=error_id,
                severity=severity,
                component=component,
                operation=operation,
                message=str(error),
                exception=exception,
                context=context,
            )
        )
        return error_id

    def record_problem(
        self,
        message: str,
        *,
        component: str,
        operation: str,
        context: Mapping[str, object] | None = None,
        severity: str = "ERROR",
    ) -> str:
        """Record a failure that did not originate as a Python exception."""

        timestamp = _utc_timestamp()
        error_id = _error_id(timestamp)
        self._append(
            self._document(
                timestamp=timestamp,
                error_id=error_id,
                severity=severity,
                component=component,
                operation=operation,
                message=message,
                exception=None,
                context=context,
            )
        )
        return error_id

    @staticmethod
    def _document(
        *,
        timestamp: str,
        error_id: str,
        severity: str,
        component: str,
        operation: str,
        message: str,
        exception: dict[str, str] | None,
        context: Mapping[str, object] | None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "timestamp": timestamp,
            "error_id": error_id,
            "severity": severity.upper(),
            "application": "sensei",
            "component": component,
            "operation": operation,
            "message": message,
            "exception": exception,
            "context": _safe_context(context),
            "process_id": os.getpid(),
            "thread_name": threading.current_thread().name,
        }

    def _append(self, document: dict[str, object]) -> None:
        encoded = (
            json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(encoded))
                with self.path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
        except Exception as logging_error:  # logging must never hide the real failure
            print(
                f"Sensei could not write its error log at {self.path}: "
                f"{logging_error}",
                file=sys.stderr,
            )

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        if self.backup_count == 0:
            self.path.unlink()
            return
        oldest = Path(f"{self.path}.{self.backup_count}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backup_count - 1, 0, -1):
            source = Path(f"{self.path}.{index}")
            if source.exists():
                source.replace(Path(f"{self.path}.{index + 1}"))
        self.path.replace(Path(f"{self.path}.1"))


def error_reference(error_id: str) -> str:
    """Return a consistent learner-facing correlation suffix."""

    return f"Error ID: {error_id}"
