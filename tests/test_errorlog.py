import json
import tempfile
import unittest
from pathlib import Path

from sensei.errorlog import ErrorRecorder


class ErrorRecorderTests(unittest.TestCase):
    def test_exception_record_contains_correlation_context_and_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensei-errors.jsonl"
            recorder = ErrorRecorder(path)

            try:
                try:
                    raise KeyError("missing field")
                except KeyError as cause:
                    raise ValueError("invalid encounter") from cause
            except ValueError as error:
                error_id = recorder.record_exception(
                    error,
                    component="test.component",
                    operation="validate encounter",
                    context={"route": "/api/test", "attempt": 2},
                )

            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, record["schema_version"])
            self.assertEqual(error_id, record["error_id"])
            self.assertTrue(error_id.startswith("SEN-"))
            self.assertEqual("ERROR", record["severity"])
            self.assertEqual("test.component", record["component"])
            self.assertEqual("validate encounter", record["operation"])
            self.assertEqual("invalid encounter", record["message"])
            self.assertEqual("builtins.ValueError", record["exception"]["type"])
            self.assertIn("KeyError: 'missing field'", record["exception"]["traceback"])
            self.assertIn("ValueError: invalid encounter", record["exception"]["traceback"])
            self.assertEqual("/api/test", record["context"]["route"])
            self.assertEqual(2, record["context"]["attempt"])
            self.assertTrue(record["timestamp"].endswith("+00:00"))

    def test_non_exception_problem_is_recorded_without_a_fake_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensei-errors.jsonl"
            recorder = ErrorRecorder(path)

            recorder.record_problem(
                "Browser promise was rejected.",
                component="dashboard.browser",
                operation="window.unhandledrejection",
                context={"stack": "at checkAnswer (app.js:500)"},
            )

            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(record["exception"])
            self.assertEqual("dashboard.browser", record["component"])
            self.assertEqual(
                "at checkAnswer (app.js:500)",
                record["context"]["stack"],
            )

    def test_log_rotation_preserves_recent_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sensei-errors.jsonl"
            recorder = ErrorRecorder(path, max_bytes=500, backup_count=2)

            for index in range(4):
                recorder.record_problem(
                    f"Problem {index} with enough detail to rotate the log file.",
                    component="test",
                    operation="rotation",
                )

            self.assertTrue(path.is_file())
            self.assertTrue(Path(f"{path}.1").is_file())
            self.assertLessEqual(
                len(list(path.parent.glob("sensei-errors.jsonl*"))),
                3,
            )


if __name__ == "__main__":
    unittest.main()
