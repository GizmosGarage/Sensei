"""Model-provider boundary and hosted Responses API implementation."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from dotenv import load_dotenv


DEFAULT_API_BASE_URL = "https://api.openai.com/v1"
DEFAULT_API_MODEL = "gpt-5.4-mini"
API_KEY_ENVIRONMENTS = ("SENSEI_LLM_API_KEY", "OPENAI_API_KEY")
MODEL_ENVIRONMENT = "SENSEI_LLM_MODEL"
BASE_URL_ENVIRONMENT = "SENSEI_LLM_BASE_URL"
LOCAL_ENV_FILENAME = ".env"

# Responses messages may contain either plain text or multimodal content blocks.
Message = dict[str, object]
TokenCallback = Callable[[str], None]


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a valid completion."""


@dataclass(frozen=True)
class CompletionResult:
    text: str
    finish_reason: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class APISettings:
    """Hosted LLM connection settings resolved without persisting the secret."""

    api_key: str
    model: str
    base_url: str


class ChatProvider(Protocol):
    """Small interface that keeps the tutor independent from its provider."""

    def complete(
        self,
        messages: Sequence[Message],
        on_token: TokenCallback | None = None,
    ) -> CompletionResult: ...


def api_settings_from_environment(
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> APISettings:
    """Resolve credentials and overrides after loading a project-local .env file."""

    load_dotenv(Path.cwd() / LOCAL_ENV_FILENAME, override=False)

    api_key = next(
        (
            value.strip()
            for name in API_KEY_ENVIRONMENTS
            if (value := os.environ.get(name, "")).strip()
        ),
        "",
    )
    if not api_key:
        names = " or ".join(API_KEY_ENVIRONMENTS)
        raise ValueError(
            f"A hosted LLM API key is required. Set {names} before starting Sensei."
        )

    resolved_model = (model or os.environ.get(MODEL_ENVIRONMENT) or DEFAULT_API_MODEL)
    resolved_model = resolved_model.strip()
    if not resolved_model:
        raise ValueError("The hosted LLM model name cannot be empty.")

    resolved_base_url = (
        base_url
        or os.environ.get(BASE_URL_ENVIRONMENT)
        or DEFAULT_API_BASE_URL
    ).strip()
    if not resolved_base_url.startswith(("https://", "http://")):
        raise ValueError("The hosted LLM base URL must begin with http:// or https://.")
    return APISettings(api_key, resolved_model, resolved_base_url.rstrip("/"))


def parse_sse_data(line: bytes) -> dict[str, object] | None:
    """Parse one server-sent-event data line; ignore comments and blank lines."""

    decoded = line.decode("utf-8").strip()
    if not decoded.startswith("data:"):
        return None
    payload = decoded[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProviderError(f"Streaming event is invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ProviderError("Streaming event payload is not a JSON object.")
    return parsed


def _usage(document: dict[str, object]) -> tuple[int | None, int | None]:
    usage = document.get("usage")
    if not isinstance(usage, dict):
        return None, None
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    return (
        prompt_tokens if isinstance(prompt_tokens, int) else None,
        completion_tokens if isinstance(completion_tokens, int) else None,
    )


def _response_text(document: dict[str, object]) -> str:
    direct_text = document.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    parts: list[str] = []
    output = document.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "output_text":
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    text = "".join(parts)
    if not text.strip():
        raise ProviderError("The Responses API returned no student-facing text.")
    return text


def parse_response(document: dict[str, object]) -> CompletionResult:
    """Validate and normalize the subset of the Responses schema Sensei uses."""

    status = document.get("status")
    if status != "completed":
        error = document.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        incomplete = document.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        detail = message or reason or status or "unknown status"
        raise ProviderError(f"The Responses API did not complete normally ({detail}).")
    prompt_tokens, completion_tokens = _usage(document)
    return CompletionResult(
        _response_text(document),
        "completed",
        prompt_tokens,
        completion_tokens,
    )


class ResponsesAPIProvider:
    """Calls a hosted, OpenAI-compatible Responses API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: int = 120,
        max_retries: int = 2,
        max_output_tokens: int = 1_536,
        json_mode: bool = False,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A hosted LLM API key is required.")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self.endpoint = f"{base_url.rstrip('/')}/responses"
        self.api_key = api_key.strip()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self.json_mode = json_mode

    def _payload(self, messages: Sequence[Message], stream: bool) -> bytes:
        payload: dict[str, object] = {
            "model": self.model,
            "input": list(messages),
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "stream": stream,
        }
        if self.json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        return json.dumps(payload).encode("utf-8")

    def _request(
        self,
        messages: Sequence[Message],
        stream: bool,
    ) -> urllib.request.Request:
        return urllib.request.Request(
            self.endpoint,
            data=self._payload(messages, stream),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def complete(
        self,
        messages: Sequence[Message],
        on_token: TokenCallback | None = None,
    ) -> CompletionResult:
        if not messages:
            raise ValueError("At least one chat message is required.")

        for attempt in range(self.max_retries + 1):
            request = self._request(messages, stream=on_token is not None)
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    if on_token is not None:
                        return self._read_stream(response, on_token)
                    document = json.loads(response.read().decode("utf-8"))
                    if not isinstance(document, dict):
                        raise ProviderError("The Responses API returned a non-object.")
                    return parse_response(document)
            except urllib.error.HTTPError as error:
                retryable = error.code in {408, 409, 429} or error.code >= 500
                detail = error.read().decode("utf-8", errors="replace")[:500]
                provider_error = ProviderError(
                    f"The hosted LLM API returned HTTP {error.code}: {detail}"
                )
                if not retryable or attempt == self.max_retries:
                    raise provider_error from error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                provider_error = ProviderError(f"Hosted LLM request failed: {error}")
                if attempt == self.max_retries:
                    raise provider_error from error
            except ProviderError:
                raise
            time.sleep(0.5 * (2**attempt))

        raise AssertionError("The retry loop must return or raise.")

    @staticmethod
    def _read_stream(
        response: object,
        on_token: TokenCallback,
    ) -> CompletionResult:
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        completed = False

        try:
            for raw_line in response:  # type: ignore[union-attr]
                event = parse_sse_data(raw_line)
                if event is None:
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str) and delta:
                        parts.append(delta)
                        on_token(delta)
                elif event_type == "response.completed":
                    final_response = event.get("response")
                    if isinstance(final_response, dict):
                        prompt_tokens, completion_tokens = _usage(final_response)
                        completed = final_response.get("status") == "completed"
                    else:
                        completed = True
                elif event_type in {
                    "response.failed",
                    "response.incomplete",
                    "error",
                }:
                    error = event.get("error")
                    message = error.get("message") if isinstance(error, dict) else None
                    raise ProviderError(
                        f"The streaming Responses API request failed: "
                        f"{message or event_type}."
                    )
        except ProviderError:
            raise
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderError(
                "The streaming connection ended before a complete response."
            ) from error

        text = "".join(parts)
        if not text.strip():
            raise ProviderError("The streaming response contained no student-facing text.")
        if not completed:
            raise ProviderError("The streaming response did not complete normally.")
        return CompletionResult(
            text=text,
            finish_reason="completed",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
