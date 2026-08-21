import tempfile
import unittest
from pathlib import Path

from sensei.runtime import LocalLlamaRuntime, RuntimeSettings


class RuntimeTests(unittest.TestCase):
    def test_command_is_loopback_only_and_disables_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = LocalLlamaRuntime(
                RuntimeSettings(
                    executable=root / "llama-server.exe",
                    model_path=root / "model.gguf",
                    model_alias="test-model",
                    log_path=root / "server.log",
                )
            )
            command = runtime.command(12345)
        self.assertIn("127.0.0.1", command)
        self.assertEqual("off", command[command.index("--reasoning") + 1])
        self.assertEqual("12345", command[command.index("--port") + 1])
        self.assertIn("--no-webui", command)


if __name__ == "__main__":
    unittest.main()
