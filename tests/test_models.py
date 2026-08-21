import json
import tempfile
import unittest
from pathlib import Path

from sensei.models import ModelCatalog, model_path


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_loads_a_pinned_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "models.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": [
                            {
                                "id": "example",
                                "vendor": "Test",
                                "filename": "example.gguf",
                                "revision": "abc",
                                "quantization": "Q4",
                                "license": "Apache-2.0",
                                "size_bytes": 10,
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            candidate = ModelCatalog.load(manifest).get("example")
            self.assertEqual("example.gguf", candidate.filename)

    def test_model_path_rejects_directory_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "models.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": [
                            {
                                "id": "unsafe",
                                "vendor": "Test",
                                "filename": "../outside.gguf",
                                "revision": "abc",
                                "quantization": "Q4",
                                "license": "Apache-2.0",
                                "size_bytes": 10,
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            candidate = ModelCatalog.load(manifest).get("unsafe")
            with self.assertRaises(ValueError):
                model_path(candidate, Path(directory) / "models")


if __name__ == "__main__":
    unittest.main()
