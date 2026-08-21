import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkConfigurationTests(unittest.TestCase):
    def test_model_manifest_has_unique_ids_and_valid_hashes(self) -> None:
        manifest = json.loads(
            (ROOT / "config" / "model_candidates.json").read_text(encoding="utf-8")
        )
        model_ids = [model["id"] for model in manifest["models"]]
        self.assertEqual(len(model_ids), len(set(model_ids)))
        for model in manifest["models"]:
            self.assertEqual(64, len(model["sha256"]))
            int(model["sha256"], 16)
            self.assertGreater(model["size_bytes"], 0)

    def test_benchmark_case_ids_are_unique_and_total_23_points(self) -> None:
        document = json.loads(
            (ROOT / "config" / "benchmark_cases.json").read_text(encoding="utf-8")
        )
        case_ids = [case["id"] for case in document["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        total = sum(
            check["points"]
            for case in document["cases"]
            for check in case["checks"]
        )
        self.assertEqual(23, total)

    def test_committed_baseline_matches_the_five_candidate_manifest(self) -> None:
        manifest = json.loads(
            (ROOT / "config" / "model_candidates.json").read_text(encoding="utf-8")
        )
        baseline = json.loads(
            (
                ROOT
                / "benchmarks"
                / "results"
                / "baseline-2026-08-21.json"
            ).read_text(encoding="utf-8")
        )

        expected_ids = {model["id"] for model in manifest["models"]}
        result_ids = {model["id"] for model in baseline["models"]}
        self.assertEqual(expected_ids, result_ids)
        for model in baseline["models"]:
            self.assertEqual(23, model["summary"]["quality_points_possible"])
            self.assertFalse(Path(model["filename"]).is_absolute())
            for performance_run in model["performance"]:
                self.assertFalse(
                    Path(performance_run["model_filename"]).is_absolute()
                )


if __name__ == "__main__":
    unittest.main()
