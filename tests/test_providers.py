import json
import unittest
from unittest.mock import patch

from sensei.providers import (
    ProviderError,
    ResponsesAPIProvider,
    api_settings_from_environment,
    parse_response,
    parse_sse_data,
)


class ProviderTests(unittest.TestCase):
    def test_parse_response_validates_completed_output(self) -> None:
        result = parse_response(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Try the chain rule."}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        )
        self.assertEqual("Try the chain rule.", result.text)
        self.assertEqual("completed", result.finish_reason)
        self.assertEqual(10, result.prompt_tokens)

    def test_parse_response_rejects_incomplete_answer(self) -> None:
        with self.assertRaises(ProviderError):
            parse_response(
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                }
            )

    def test_parse_sse_data_ignores_done_marker(self) -> None:
        self.assertIsNone(parse_sse_data(b"data: [DONE]\n"))
        event = {"type": "response.output_text.delta", "delta": "hello"}
        parsed = parse_sse_data(f"data: {json.dumps(event)}\n".encode())
        self.assertEqual(event, parsed)

    def test_stream_assembles_tokens_and_reports_usage(self) -> None:
        events = [
            b'data: {"type":"response.output_text.delta","delta":"Chain "}\n',
            b'data: {"type":"response.output_text.delta","delta":"rule"}\n',
            (
                b'data: {"type":"response.completed","response":'
                b'{"status":"completed","usage":{"input_tokens":12,'
                b'"output_tokens":2}}}\n'
            ),
            b"data: [DONE]\n",
        ]
        tokens: list[str] = []
        result = ResponsesAPIProvider._read_stream(events, tokens.append)
        self.assertEqual("Chain rule", result.text)
        self.assertEqual(["Chain ", "rule"], tokens)
        self.assertEqual(12, result.prompt_tokens)

    def test_payload_uses_responses_api_and_disables_remote_storage(self) -> None:
        provider = ResponsesAPIProvider(
            "secret",
            "test-model",
            base_url="https://example.test/v1",
            json_mode=True,
        )
        payload = json.loads(
            provider._payload([{"role": "user", "content": "new problem"}], False)
        )
        self.assertEqual("https://example.test/v1/responses", provider.endpoint)
        self.assertEqual("test-model", payload["model"])
        self.assertFalse(payload["store"])
        self.assertEqual(
            {"format": {"type": "json_object"}},
            payload["text"],
        )

    def test_environment_requires_a_key_and_supports_overrides(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "API key is required"):
                api_settings_from_environment()
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "SENSEI_LLM_MODEL": "test-model",
                "SENSEI_LLM_BASE_URL": "https://example.test/v1/",
            },
            clear=True,
        ):
            settings = api_settings_from_environment()
        self.assertEqual("test-key", settings.api_key)
        self.assertEqual("test-model", settings.model)
        self.assertEqual("https://example.test/v1", settings.base_url)


if __name__ == "__main__":
    unittest.main()
