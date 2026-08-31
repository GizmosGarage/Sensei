import base64
import json
import unittest

from sensei.imports import (
    CurriculumScanError,
    PDFCurriculumScanner,
    parse_curriculum_plan,
)
from sensei.providers import CompletionResult


class CurriculumImportTests(unittest.TestCase):
    def test_curriculum_plan_requires_distinct_validated_topics(self) -> None:
        plan = parse_curriculum_plan(
            json.dumps(
                {
                    "subject": "Physics",
                    "folder_name": "Kinematics chapter",
                    "topics": [
                        {
                            "name": "Position and displacement",
                            "description": "Interpret position, distance, and displacement.",
                        },
                        {
                            "name": "Velocity graphs",
                            "description": "Read slope and signed area on motion graphs.",
                        },
                    ],
                }
            )
        )

        self.assertEqual("Physics", plan.subject)
        self.assertEqual(2, len(plan.topics))
        with self.assertRaisesRegex(CurriculumScanError, "duplicate topic"):
            parse_curriculum_plan(
                json.dumps(
                    {
                        "subject": "Physics",
                        "folder_name": "Motion",
                        "topics": [
                            {"name": "Velocity", "description": "Define velocity."},
                            {"name": "velocity", "description": "Use velocity."},
                        ],
                    }
                )
            )

    def test_pdf_scanner_sends_page_text_and_images_to_only_its_provider(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.requests = []

            def complete(self, messages, on_token=None):
                self.requests.append(messages)
                return CompletionResult(
                    json.dumps(
                        {
                            "subject": "Biology",
                            "folder_name": "Cell membranes",
                            "topics": [
                                {
                                    "name": "Membrane transport",
                                    "description": (
                                        "Compare diffusion, osmosis, and active "
                                        "transport."
                                    ),
                                }
                            ],
                        }
                    ),
                    "completed",
                )

        provider = Provider()
        scanner = PDFCurriculumScanner(provider)
        plan = scanner.scan(b"%PDF-1.7\nscanned-page-bytes", filename="chapter.pdf")

        self.assertEqual("Cell membranes", plan.folder_name)
        content = provider.requests[0][1]["content"]
        self.assertEqual("input_file", content[0]["type"])
        self.assertEqual("high", content[0]["detail"])
        self.assertEqual(
            b"%PDF-1.7\nscanned-page-bytes",
            base64.b64decode(content[0]["file_data"].split(",", 1)[1]),
        )
        self.assertIn("complete Atlas curriculum", content[1]["text"])

    def test_pdf_scanner_rejects_non_pdf_content_before_calling_provider(self) -> None:
        class Provider:
            def complete(self, messages, on_token=None):
                raise AssertionError("invalid files must not reach the provider")

        with self.assertRaisesRegex(CurriculumScanError, "not a valid PDF"):
            PDFCurriculumScanner(Provider()).scan(
                b"not a PDF", filename="chapter.pdf"
            )


if __name__ == "__main__":
    unittest.main()
