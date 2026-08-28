import json
import unittest

from sensei.providers import (
    LlamaCppProvider,
    ProviderError,
    parse_completion,
    parse_sse_data,
)


class ProviderTests(unittest.TestCase):
    def test_parse_completion_validates_normal_finish(self) -> None:
        result = parse_completion(
            {
                "choices": [
                    {
                        "message": {"content": "Try the chain rule."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )
        self.assertEqual("Try the chain rule.", result.text)
        self.assertEqual(10, result.prompt_tokens)

    def test_parse_completion_rejects_truncated_answer(self) -> None:
        with self.assertRaises(ProviderError):
            parse_completion(
                {
                    "choices": [
                        {
                            "message": {"content": "unfinished"},
                            "finish_reason": "length",
                        }
                    ]
                }
            )

    def test_parse_sse_data_ignores_done_marker(self) -> None:
        self.assertIsNone(parse_sse_data(b"data: [DONE]\n"))
        event = {"choices": [{"delta": {"content": "hello"}}]}
        parsed = parse_sse_data(f"data: {json.dumps(event)}\n".encode())
        self.assertEqual(event, parsed)

    def test_stream_assembles_tokens_and_reports_usage(self) -> None:
        events = [
            b'data: {"choices":[{"delta":{"content":"Chain "},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{"content":"rule"},"finish_reason":null}]}\n',
            (
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                b'"usage":{"prompt_tokens":12,"completion_tokens":2}}\n'
            ),
            b"data: [DONE]\n",
        ]
        tokens: list[str] = []
        result = LlamaCppProvider._read_stream(events, tokens.append)
        self.assertEqual("Chain rule", result.text)
        self.assertEqual(["Chain ", "rule"], tokens)
        self.assertEqual(12, result.prompt_tokens)

    def test_seed_can_be_randomized_for_fresh_generation(self) -> None:
        provider = LlamaCppProvider("http://127.0.0.1:9999", "test", seed=-1)
        payload = json.loads(
            provider._payload([{"role": "user", "content": "new problem"}], False)
        )
        self.assertEqual(-1, payload["seed"])

    def test_json_mode_constrains_structured_local_completions(self) -> None:
        provider = LlamaCppProvider(
            "http://127.0.0.1:9999",
            "test",
            json_mode=True,
        )
        payload = json.loads(
            provider._payload([{"role": "user", "content": "new problem"}], False)
        )

        self.assertEqual(
            {"type": "json_object"},
            payload["response_format"],
        )


if __name__ == "__main__":
    unittest.main()
