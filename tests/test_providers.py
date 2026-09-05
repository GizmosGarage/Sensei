import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sensei.providers import (
    ProviderError,
    ResponsesAPIProvider,
    api_settings_from_environment,
    parse_response,
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



    def test_payload_uses_responses_api_and_disables_remote_storage(self) -> None:
        provider = ResponsesAPIProvider(
            "secret",
            "test-model",
            base_url="https://example.test/v1",
            json_mode=True,
        )
        payload = json.loads(
            provider._payload([{"role": "user", "content": "new problem"}])
        )
        self.assertEqual("https://example.test/v1/responses", provider.endpoint)
        self.assertEqual("test-model", payload["model"])
        self.assertFalse(payload["store"])
        self.assertEqual(
            {"format": {"type": "json_object"}},
            payload["text"],
        )

    def test_environment_requires_a_key_and_supports_overrides(self) -> None:
        with patch("sensei.providers.load_dotenv"), patch.dict(
            "os.environ", {}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "API key is required"):
                api_settings_from_environment()
        with patch("sensei.providers.load_dotenv"), patch.dict(
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

    def test_environment_loads_dotenv_without_overriding_process_values(self) -> None:
        with TemporaryDirectory() as directory:
            dotenv_path = Path(directory) / ".env"
            dotenv_path.write_text(
                "OPENAI_API_KEY=file-key\n"
                "SENSEI_LLM_MODEL=file-model\n"
                "SENSEI_LLM_BASE_URL=https://file.example/v1\n",
                encoding="utf-8",
            )
            with patch("sensei.providers.Path.cwd", return_value=Path(directory)):
                with patch.dict(
                    "os.environ",
                    {"SENSEI_LLM_MODEL": "process-model"},
                    clear=True,
                ):
                    settings = api_settings_from_environment()

        self.assertEqual("file-key", settings.api_key)
        self.assertEqual("process-model", settings.model)
        self.assertEqual("https://file.example/v1", settings.base_url)


if __name__ == "__main__":
    unittest.main()
