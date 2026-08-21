import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillCatalogTests(unittest.TestCase):
    def test_skill_ids_are_unique_and_prerequisites_exist(self) -> None:
        document = json.loads(
            (ROOT / "config" / "skills.json").read_text(encoding="utf-8")
        )
        self.assertEqual(1, document["schema_version"])
        skills = document["skills"]
        skill_ids = [skill["id"] for skill in skills]
        self.assertEqual(len(skill_ids), len(set(skill_ids)))
        known = set(skill_ids)
        self.assertIn("calculus_foundations", known)
        for skill in skills:
            self.assertLessEqual(set(skill["prerequisites"]), known)


if __name__ == "__main__":
    unittest.main()
