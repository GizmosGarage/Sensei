import tomllib
import unittest
from pathlib import Path

import sensei


ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_package_and_project_versions_match(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(project["project"]["version"], sensei.__version__)


if __name__ == "__main__":
    unittest.main()
