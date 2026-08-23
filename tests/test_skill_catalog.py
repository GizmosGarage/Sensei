import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillCatalogTests(unittest.TestCase):
    def test_skill_ids_are_unique_and_prerequisites_exist(self) -> None:
        document = json.loads(
            (ROOT / "config" / "skills.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, document["schema_version"])
        skills = document["skills"]
        self.assertEqual(37, len(skills))
        skill_ids = [skill["id"] for skill in skills]
        self.assertEqual(len(skill_ids), len(set(skill_ids)))
        known = set(skill_ids)
        self.assertIn("calculus_foundations", known)
        for skill in skills:
            self.assertIn(skill["course"], {"precalculus", "calculus"})
            self.assertLessEqual(set(skill["prerequisites"]), known)

    def test_precalculus_catalog_matches_the_twenty_subject_path(self) -> None:
        document = json.loads(
            (ROOT / "config" / "skills.json").read_text(encoding="utf-8")
        )
        subjects = [
            skill["name"]
            for skill in document["skills"]
            if skill["course"] == "precalculus"
        ]
        self.assertEqual(
            [
                "Properties of exponents",
                "Factoring",
                "Fractions / compound fractions",
                "Rational expressions",
                "Solving polynomial equations",
                "Linear equations",
                "Linear/nonlinear inequalities",
                "Function notation and evaluating functions",
                "Domain and range",
                "Function composition",
                "Inverse functions",
                "Parent functions and graph transformations",
                "Average rate of change",
                "Logarithm properties",
                "Exponential equations",
                "Logarithmic equations",
                "Unit circle",
                "Trig graphs",
                "Trigonometric equations",
                "Trigonometric identities",
            ],
            subjects,
        )


if __name__ == "__main__":
    unittest.main()
