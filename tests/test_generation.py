import json
import random
import unittest
from pathlib import Path

from sensei.generation import GENERATED_SKILL_IDS, GeneratedQuestFactory
from sensei.verification import VerificationStatus


ROOT = Path(__file__).resolve().parents[1]


class GeneratedQuestFactoryTests(unittest.TestCase):
    def test_every_catalog_skill_has_a_confined_validated_generator(self) -> None:
        catalog = json.loads(
            (ROOT / "config" / "skills.json").read_text(encoding="utf-8")
        )
        catalog_ids = {skill["id"] for skill in catalog["skills"]}
        self.assertEqual(catalog_ids, set(GENERATED_SKILL_IDS))

        factory = GeneratedQuestFactory(random.Random(20260822))
        for skill_id in GENERATED_SKILL_IDS:
            with self.subTest(skill=skill_id):
                quest = factory.generate(skill_id)
                self.assertEqual(skill_id, quest.skill_id)
                result = quest.check(quest.sample_answer, factory.verifier)
                self.assertEqual(
                    VerificationStatus.VERIFIED_CORRECT,
                    result.status,
                )

    def test_each_subject_produces_multiple_prompt_variants(self) -> None:
        factory = GeneratedQuestFactory(random.Random(71))
        for skill_id in GENERATED_SKILL_IDS:
            with self.subTest(skill=skill_id):
                prompts = {
                    factory.generate(skill_id).prompt
                    for _ in range(12)
                }
                self.assertGreaterEqual(len(prompts), 2)

    def test_unknown_skill_is_rejected(self) -> None:
        factory = GeneratedQuestFactory(random.Random(1))
        with self.assertRaisesRegex(ValueError, "unavailable"):
            factory.generate("not_a_real_subject")


if __name__ == "__main__":
    unittest.main()
