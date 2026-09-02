import json
import unittest

from sensei.materials import (
    MaterialScanError,
    MaterialScanner,
    parse_material_proposals,
)
from sensei.providers import CompletionResult, ProviderError


class StubProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, object]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        return CompletionResult(self.responses.pop(0), "completed")


def proposals_json(count: int = 1) -> str:
    return json.dumps(
        {
            "materials": [
                {
                    "kind": "example_problem",
                    "body": (
                        "A 13 ft ladder slides down a wall.\\r\\n"
                        "(a) Find \\\\(\\\\frac{dy}{dt}\\\\).\\r\\n(b) Find the angle rate."
                    ),
                    "solution": None,
                    "source_label": "  HW 4   #7 ",
                }
            ]
            + [
                {
                    "kind": "worked_example",
                    "body": f"Problem {index}",
                    "solution": f"Solution {index}",
                    "source_label": "",
                }
                for index in range(count - 1)
            ]
        }
    )


PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)
PDF = b"%PDF-1.7\n%test\n"


class MaterialProposalTests(unittest.TestCase):
    def test_proposals_are_validated_and_normalized(self) -> None:
        proposals = parse_material_proposals(proposals_json(2))
        self.assertEqual(2, len(proposals))
        first = proposals[0]
        self.assertEqual("example_problem", first.kind)
        self.assertTrue(first.body.startswith("A 13 ft ladder"))
        self.assertIn(r"(a) Find \(\frac{dy}{dt}\).", first.body)
        self.assertNotIn("\r", first.body)
        self.assertIsNone(first.solution)
        self.assertEqual("HW 4 #7", first.source_label)
        self.assertEqual("Solution 0", proposals[1].solution)
        self.assertEqual(
            {"kind", "body", "solution", "source_label"},
            set(first.public_dict()),
        )

    def test_invalid_scanner_documents_are_rejected(self) -> None:
        with self.assertRaisesRegex(MaterialScanError, "not valid JSON"):
            parse_material_proposals("{oops")
        with self.assertRaisesRegex(MaterialScanError, "one JSON object with materials"):
            parse_material_proposals(json.dumps({"topics": []}))
        with self.assertRaisesRegex(MaterialScanError, "found no class material"):
            parse_material_proposals(json.dumps({"materials": []}))
        with self.assertRaisesRegex(MaterialScanError, "at most 40"):
            parse_material_proposals(proposals_json(41))
        with self.assertRaisesRegex(MaterialScanError, "exactly"):
            parse_material_proposals(
                json.dumps({"materials": [{"kind": "notes", "body": "x"}]})
            )
        with self.assertRaisesRegex(MaterialScanError, "kind must be"):
            parse_material_proposals(
                json.dumps(
                    {
                        "materials": [
                            {"kind": "video", "body": "x", "solution": None, "source_label": ""}
                        ]
                    }
                )
            )
        with self.assertRaisesRegex(MaterialScanError, "cannot be empty"):
            parse_material_proposals(
                json.dumps(
                    {
                        "materials": [
                            {"kind": "notes", "body": "  ", "solution": None, "source_label": ""}
                        ]
                    }
                )
            )
        with self.assertRaisesRegex(MaterialScanError, "4000 characters"):
            parse_material_proposals(
                json.dumps(
                    {
                        "materials": [
                            {
                                "kind": "notes",
                                "body": "x" * 4_001,
                                "solution": None,
                                "source_label": "",
                            }
                        ]
                    }
                )
            )


class MaterialScannerTests(unittest.TestCase):
    def test_pdf_is_sent_as_input_file_and_images_as_input_image(self) -> None:
        provider = StubProvider([proposals_json(), proposals_json()])
        scanner = MaterialScanner(provider)

        proposals = scanner.scan(
            PDF,
            filename="C:\\Users\\me\\hw4.pdf",
            media_type="application/pdf",
            subject="Calculus I",
            topic="Related rates",
            practice_instructions="Match Dr. Lee's homework.",
        )
        self.assertEqual(1, len(proposals))
        system, user = provider.requests[0]
        self.assertIn("untrusted", str(system["content"]))
        self.assertIn("(a), (b), (c)", str(system["content"]))
        media, text = user["content"]
        self.assertEqual("input_file", media["type"])
        self.assertEqual("hw4.pdf", media["filename"])
        self.assertTrue(str(media["file_data"]).startswith("data:application/pdf;base64,"))
        self.assertIn("Topic: Related rates", str(text["text"]))
        self.assertIn("Match Dr. Lee's homework.", str(text["text"]))

        scanner.scan(
            PNG,
            filename="page.png",
            media_type="image/png",
            subject="Calculus I",
            topic="Related rates",
        )
        media = provider.requests[1][1]["content"][0]
        self.assertEqual("input_image", media["type"])
        self.assertTrue(str(media["image_url"]).startswith("data:image/png;base64,"))
        self.assertEqual("high", media["detail"])
        self.assertIn("Practice instructions: none provided", provider.requests[1][1]["content"][1]["text"])

    def test_pasted_text_is_sent_as_input_text(self) -> None:
        provider = StubProvider([proposals_json()])
        MaterialScanner(provider).scan(
            "1.3 Evaluating limits\nFactor and divide.".encode("utf-8"),
            filename="notes.txt",
            media_type="text/plain",
            subject="Calculus I",
            topic="Limits",
        )
        block = provider.requests[0][1]["content"][0]
        self.assertEqual("input_text", block["type"])
        self.assertIn("Factor and divide.", str(block["text"]))

    def test_scanner_rejects_bad_media_and_provider_failures(self) -> None:
        scanner = MaterialScanner(StubProvider([]))
        common = dict(subject="Calculus I", topic="Limits")
        with self.assertRaisesRegex(MaterialScanError, "Unsupported file type"):
            scanner.scan(b"hello", filename="a.doc", media_type="application/msword", **common)
        with self.assertRaisesRegex(MaterialScanError, "Pasted text is empty"):
            scanner.scan(b"   ", filename="a.txt", media_type="text/plain", **common)
        with self.assertRaisesRegex(MaterialScanError, "UTF-8"):
            scanner.scan(b"\xff\xfe", filename="a.txt", media_type="text/plain", **common)
        with self.assertRaisesRegex(MaterialScanError, "not a valid PDF"):
            scanner.scan(b"hello", filename="a.pdf", media_type="application/pdf", **common)
        with self.assertRaisesRegex(MaterialScanError, "not a valid image"):
            scanner.scan(PDF, filename="a.png", media_type="image/png", **common)
        with self.assertRaisesRegex(MaterialScanError, "not a valid image"):
            scanner.scan(b"RIFF1234NOPE", filename="a.webp", media_type="image/webp", **common)
        with self.assertRaisesRegex(MaterialScanError, "empty"):
            scanner.scan(b"", filename="a.pdf", media_type="application/pdf", **common)
        with self.assertRaisesRegex(MaterialScanError, "20 MB"):
            scanner.scan(
                PDF + bytes(20 * 1024 * 1024),
                filename="big.pdf",
                media_type="application/pdf",
                **common,
            )
        with self.assertRaisesRegex(MaterialScanError, "8 MB"):
            scanner.scan(
                PNG + bytes(8 * 1024 * 1024),
                filename="big.png",
                media_type="image/png",
                **common,
            )
        with self.assertRaisesRegex(MaterialScanError, "file name"):
            scanner.scan(PDF, filename="x" * 200 + ".pdf", media_type="application/pdf", **common)

        class FailingProvider:
            def complete(self, messages, on_token=None):
                raise ProviderError("rate limited")

        with self.assertRaisesRegex(MaterialScanError, "could not finish"):
            MaterialScanner(FailingProvider()).scan(
                PDF, filename="a.pdf", media_type="application/pdf", **common
            )


if __name__ == "__main__":
    unittest.main()
