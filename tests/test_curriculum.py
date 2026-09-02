import json
import unittest

from sensei.curriculum import (
    StudyPlanError,
    StudyPlanScanner,
    parse_study_plan,
)
from sensei.providers import CompletionResult, ProviderError


PDF = b"%PDF-1.7\n%study guide\n"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)


def topic(index: int, materials: int = 1) -> dict:
    return {
        "name": f"Topic {index}",
        "section": f"1.{index}",
        "description": f"Know how to do topic {index}.",
        "materials": [
            {
                "kind": "example_problem",
                "body": f"Problem {index}.{item}: evaluate \\\\(\\\\lim_{{x \\\\to {item}}} f(x)\\\\).",
                "solution": f"L = {item}",
                "source_label": f"Exercise {index}{item}",
            }
            for item in range(materials)
        ],
    }


def plan_json(topics: object = 3, materials: int = 1, **overrides: object) -> str:
    topic_list = (
        list(topics)
        if isinstance(topics, list)
        else [topic(index, materials) for index in range(1, int(topics) + 1)]
    )
    document = {
        "subject": "MAC2311 Calculus I",
        "set_name": "Test 1",
        "course_profile": "Calculator in radian mode. Support limits with a table or graph.",
        "topics": topic_list,
    }
    document.update(overrides)
    return json.dumps(document)


class ScriptedProvider:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, object]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return CompletionResult(response, "completed")


class StudyPlanParsingTests(unittest.TestCase):
    def test_valid_plan_is_normalized(self) -> None:
        plan = parse_study_plan(plan_json(topics=4, materials=2))
        self.assertEqual("MAC2311 Calculus I", plan.subject)
        self.assertEqual("Test 1", plan.set_name)
        self.assertIn("radian mode", plan.course_profile)
        self.assertEqual(4, len(plan.topics))
        self.assertEqual("1.2", plan.topics[1].section)
        self.assertEqual(2, len(plan.topics[0].materials))
        self.assertIn(r"\(\lim_{x \to 0} f(x)\)", plan.topics[0].materials[0].body)
        self.assertEqual("L = 1", plan.topics[0].materials[1].solution)
        public = plan.public_dict()
        self.assertEqual(8, public["material_count"])
        self.assertEqual("Exercise 10", public["topics"][0]["materials"][0]["source_label"])

    def test_plan_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(StudyPlanError, "not valid JSON"):
            parse_study_plan("{nope")
        with self.assertRaisesRegex(StudyPlanError, "exactly"):
            parse_study_plan(json.dumps({"subject": "x"}))
        with self.assertRaisesRegex(StudyPlanError, "from 3 to 24 topics"):
            parse_study_plan(plan_json(topics=2))
        with self.assertRaisesRegex(StudyPlanError, "from 3 to 24 topics"):
            parse_study_plan(plan_json(topics=25))
        with self.assertRaisesRegex(StudyPlanError, "duplicate topic"):
            parse_study_plan(
                plan_json(topics=3).replace('"name": "Topic 2"', '"name": "topic 1"')
            )
        with self.assertRaisesRegex(StudyPlanError, "at most 6"):
            parse_study_plan(plan_json(topics=3, materials=7))
        with self.assertRaisesRegex(StudyPlanError, "at most 80"):
            parse_study_plan(plan_json(topics=14, materials=6))
        with self.assertRaisesRegex(StudyPlanError, "'subject' cannot be empty"):
            parse_study_plan(plan_json(subject="  "))
        with self.assertRaisesRegex(StudyPlanError, "1500 characters"):
            parse_study_plan(plan_json(course_profile="p" * 1_501))
        bad_topic = topic(9)
        bad_topic["materials"][0]["kind"] = "video"
        with self.assertRaisesRegex(StudyPlanError, "Topic 'Topic 9'"):
            parse_study_plan(plan_json(topics=[topic(1), topic(2), bad_topic]))
        empty = parse_study_plan(plan_json(course_profile=None, topics=[
            {**topic(1), "materials": None}, topic(2), topic(3)
        ]))
        self.assertEqual("", empty.course_profile)
        self.assertEqual((), empty.topics[0].materials)


class StudyPlanScannerTests(unittest.TestCase):
    def test_pdf_image_and_text_inputs_reach_the_analyst(self) -> None:
        provider = ScriptedProvider([plan_json(), plan_json(), plan_json()])
        scanner = StudyPlanScanner(provider)
        plan = scanner.scan(
            PDF, filename="C:\\guides\\test1.pdf", media_type="application/pdf"
        )
        self.assertEqual(3, len(plan.topics))
        system, user = provider.requests[0]
        self.assertIn("study-guide analyst", str(system["content"]))
        self.assertIn("drillable", str(system["content"]))
        self.assertNotIn("Compact mode", str(system["content"]))
        media, text = user["content"]
        self.assertEqual("input_file", media["type"])
        self.assertEqual("test1.pdf", media["filename"])
        self.assertIn("Infer the subject from the document.", str(text["text"]))

        scanner.scan(PNG, filename="page.png", media_type="image/png")
        self.assertEqual("input_image", provider.requests[1][1]["content"][0]["type"])

        scanner.scan(
            "1.1 Limits\nBe able to ...".encode("utf-8"),
            filename="guide.txt",
            media_type="text/plain",
            subject_hint="MAC2311 Calculus I",
            set_name_hint="Test 1",
        )
        text_block, prompt = provider.requests[2][1]["content"]
        self.assertEqual("input_text", text_block["type"])
        self.assertIn("1.1 Limits", str(text_block["text"]))
        self.assertIn('Use this exact subject label: "MAC2311 Calculus I".', str(prompt["text"]))
        self.assertIn('Use this exact study-set name: "Test 1".', str(prompt["text"]))

    def test_hints_must_be_preserved(self) -> None:
        provider = ScriptedProvider([plan_json(subject="Physics")])
        with self.assertRaisesRegex(StudyPlanError, "preserve the requested subject"):
            StudyPlanScanner(provider).scan(
                PDF,
                filename="a.pdf",
                media_type="application/pdf",
                subject_hint="MAC2311 Calculus I",
            )

    def test_invalid_or_truncated_output_retries_once_in_compact_mode(self) -> None:
        provider = ScriptedProvider(['{"subject": "MAC2311", "topics": [', plan_json()])
        plan = StudyPlanScanner(provider).scan(
            PDF, filename="a.pdf", media_type="application/pdf"
        )
        self.assertEqual("Test 1", plan.set_name)
        self.assertEqual(2, len(provider.requests))
        self.assertIn("Compact mode", str(provider.requests[1][0]["content"]))

        truncated = ScriptedProvider(
            [
                ProviderError(
                    "The Responses API did not complete normally (max_output_tokens)."
                ),
                plan_json(),
            ]
        )
        plan = StudyPlanScanner(truncated).scan(
            PDF, filename="a.pdf", media_type="application/pdf"
        )
        self.assertEqual(3, len(plan.topics))
        self.assertEqual(2, len(truncated.requests))

        twice_bad = ScriptedProvider(["nope", "still nope"])
        with self.assertRaisesRegex(StudyPlanError, "not valid JSON"):
            StudyPlanScanner(twice_bad).scan(
                PDF, filename="a.pdf", media_type="application/pdf"
            )

    def test_provider_and_media_failures_become_plan_errors(self) -> None:
        failing = ScriptedProvider([ProviderError("HTTP 429 rate limited")])
        with self.assertRaisesRegex(StudyPlanError, "could not finish"):
            StudyPlanScanner(failing).scan(
                PDF, filename="a.pdf", media_type="application/pdf"
            )
        self.assertEqual(1, len(failing.requests))
        with self.assertRaisesRegex(StudyPlanError, "Unsupported file type"):
            StudyPlanScanner(ScriptedProvider([])).scan(
                b"x", filename="a.doc", media_type="application/msword"
            )
        with self.assertRaisesRegex(StudyPlanError, "not a valid PDF"):
            StudyPlanScanner(ScriptedProvider([])).scan(
                b"hello", filename="a.pdf", media_type="application/pdf"
            )
        with self.assertRaisesRegex(StudyPlanError, "80 characters"):
            StudyPlanScanner(ScriptedProvider([])).scan(
                PDF, filename="a.pdf", media_type="application/pdf", subject_hint="s" * 81
            )


if __name__ == "__main__":
    unittest.main()
