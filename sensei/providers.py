"""Model-provider boundary and local llama.cpp implementation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence


Message = dict[str, str]
TokenCallback = Callable[[str], None]


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a valid completion."""


@dataclass(frozen=True)
class CompletionResult:
    text: str
    finish_reason: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatProvider(Protocol):
    """Small interface that keeps the tutor independent from its runtime."""

    def complete(
        self,
        messages: Sequence[Message],
        on_token: TokenCallback | None = None,
    ) -> CompletionResult: ...


def parse_completion(document: dict[str, object]) -> CompletionResult:
    """Validate the subset of the chat-completion schema Sensei consumes."""

    try:
        choices = document["choices"]
        if not isinstance(choices, list) or not choices:
            raise TypeError("choices must be a non-empty list")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError("the first choice must be an object")
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError("choice.message must be an object")
        text = message["content"]
        finish_reason = choice["finish_reason"]
        if not isinstance(text, str) or not text.strip():
            raise TypeError("choice.message.content must be a non-empty string")
        if not isinstance(finish_reason, str):
            raise TypeError("choice.finish_reason must be a string")
        usage = document.get("usage")
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = (
            usage.get("completion_tokens") if isinstance(usage, dict) else None
        )
        if prompt_tokens is not None and not isinstance(prompt_tokens, int):
            prompt_tokens = None
        if completion_tokens is not None and not isinstance(completion_tokens, int):
            completion_tokens = None
    except (KeyError, TypeError) as error:
        raise ProviderError(f"Invalid chat-completion response: {error}") from error

    if finish_reason != "stop":
        raise ProviderError(
            f"The model response did not finish normally ({finish_reason!r})."
        )
    return CompletionResult(text, finish_reason, prompt_tokens, completion_tokens)


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


class LlamaCppProvider:
    """Calls llama.cpp's localhost OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: int = 600,
        max_retries: int = 2,
        temperature: float = 0.2,
        max_tokens: int = 768,
        seed: int = 42,
        json_mode: bool = False,
    ) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed
        self.json_mode = json_mode
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")

    def _payload(self, messages: Sequence[Message], stream: bool) -> bytes:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature,
            "top_p": 0.9,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return json.dumps(payload).encode("utf-8")

    def complete(
        self,
        messages: Sequence[Message],
        on_token: TokenCallback | None = None,
    ) -> CompletionResult:
        if not messages:
            raise ValueError("At least one chat message is required.")
        request = urllib.request.Request(
            self.endpoint,
            data=self._payload(messages, stream=on_token is not None),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    if on_token is None:
                        document = json.loads(response.read().decode("utf-8"))
                        if not isinstance(document, dict):
                            raise ProviderError("Completion response is not an object.")
                        return parse_completion(document)
                    return self._read_stream(response, on_token)
            except urllib.error.HTTPError as error:
                retryable = error.code >= 500
                detail = error.read().decode("utf-8", errors="replace")[:500]
                provider_error = ProviderError(
                    f"llama.cpp returned HTTP {error.code}: {detail}"
                )
                if not retryable or attempt == self.max_retries:
                    raise provider_error from error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                provider_error = ProviderError(f"Local model request failed: {error}")
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
        finish_reason: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        emitted_text = False

        try:
            for raw_line in response:  # type: ignore[union-attr]
                event = parse_sse_data(raw_line)
                if event is None:
                    continue
                choices = event.get("choices")
                if isinstance(choices, list) and choices:
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise ProviderError("Streaming choice is not an object.")
                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        token = delta.get("content")
                        if isinstance(token, str) and token:
                            parts.append(token)
                            emitted_text = True
                            on_token(token)
                    reason = choice.get("finish_reason")
                    if isinstance(reason, str):
                        finish_reason = reason
                usage = event.get("usage")
                if isinstance(usage, dict):
                    if isinstance(usage.get("prompt_tokens"), int):
                        prompt_tokens = usage["prompt_tokens"]
                    if isinstance(usage.get("completion_tokens"), int):
                        completion_tokens = usage["completion_tokens"]
        except ProviderError:
            raise
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderError(
                "The streaming connection ended before a complete response."
            ) from error

        text = "".join(parts)
        if not emitted_text or not text.strip():
            raise ProviderError("The streaming response contained no student-facing text.")
        if finish_reason != "stop":
            raise ProviderError(
                f"The streaming response did not finish normally ({finish_reason!r})."
            )
        return CompletionResult(
            text=text,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
