import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_model_benchmarks.py"
SPEC = importlib.util.spec_from_file_location("run_model_benchmarks", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BenchmarkEvaluatorTests(unittest.TestCase):
    def test_contains_any_is_case_insensitive(self) -> None:
        check = {"type": "contains_any", "values": ["chain rule"]}
        passed, _ = MODULE.evaluate_check(check, "Use the Chain Rule here.")
        self.assertTrue(passed)

    def test_contains_all_ignores_math_spacing(self) -> None:
        check = {"type": "contains_all", "values": ["(x+h)^2", "2x"]}
        passed, _ = MODULE.evaluate_check(
            check, r"Expand \( (x + h)^2 \), then the limit gives \(2 x\)."
        )
        self.assertTrue(passed)

    def test_excludes_all_fails_when_answer_is_revealed(self) -> None:
        check = {"type": "excludes_all", "values": ["-3/2"]}
        passed, _ = MODULE.evaluate_check(check, "The answer is -3/2 ft/s.")
        self.assertFalse(passed)

    def test_json_exact_fields_accepts_json_fence(self) -> None:
        check = {
            "type": "json_exact_fields",
            "required_fields": ["skill", "correctness"],
            "expected_values": {"skill": "chain_rule", "correctness": "incorrect"},
        }
        content = "```json\n" + json.dumps(
            {"skill": "chain_rule", "correctness": "incorrect"}
        ) + "\n```"
        passed, _ = MODULE.evaluate_check(check, content)
        self.assertTrue(passed)

    def test_extract_json_lines_ignores_runtime_logs(self) -> None:
        output = 'runtime log\n{"n_prompt": 512}\nmore logs\n{"n_gen": 128}\n'
        records = MODULE.extract_json_lines(output)
        self.assertEqual([512, 128], [records[0]["n_prompt"], records[1]["n_gen"]])


if __name__ == "__main__":
    unittest.main()
