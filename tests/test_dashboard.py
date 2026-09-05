import base64 as _base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from sensei.dashboard import LOOPBACK_HOST, DashboardService, create_server
from sensei.errorlog import ErrorRecorder
from sensei.practice import AdaptiveQuestFactory
from sensei.lessons import LessonFactory
from sensei.providers import CompletionResult
from sensei.curriculum import StudyPlan, PlannedTopic
from sensei.materials import MaterialProposal


MULTI_PART_DRAFT = {
    "title": "Sliding ladder",
    "prompt": (
        r"A 10 ft ladder leans against a wall. Its base slides away from the "
        r"wall at \(2\) ft/s."
    ),
    "answer_type": "multi_part",
    "answer": "",
    "options": [],
    "parts": [
        {
            "label": "a",
            "prompt": r"Find \(\frac{dy}{dt}\) when \(x = 6\). Enter only the value in ft/s.",
            "answer_type": "expression",
            "answer": "-3/2",
        },
        {
            "label": "b",
            "prompt": "For which base distances is the top moving faster than 1 ft/s downward? Use interval notation.",
            "answer_type": "interval",
            "answer": "(4, 10)",
        },
        {
            "label": "c",
            "prompt": "Which quantity stays constant? Choose the best answer.",
            "answer_type": "multiple_choice",
            "answer": "C",
            "options": ["x", "y", "The ladder length", r"\(\frac{dy}{dt}\)"],
        },
    ],
    "help_steps": [
        "Relate the base distance and height with the Pythagorean theorem.",
        r"Differentiate both sides with respect to \(t\).",
        "Substitute the known values and solve for the unknown rate.",
    ],
    "solution": (
        r"From \(x^2 + y^2 = 100\), \(2x\,x' + 2y\,y' = 0\), so at \(x = 6\), "
        r"\(y = 8\) and \(y' = -\frac{3}{2}\) ft/s."
    ),
    "graph": None,
}

LESSON_DRAFT = {
    "title": "How to solve related-rates problems",
    "overview": r"Every related-rates problem gives one rate and asks for \(\frac{dy}{dt}\).",
    "steps": [
        {
            "title": "Name the changing quantities",
            "explanation": r"Assign a variable to every quantity that changes with \(t\).",
            "worked_example": r"Let \(x\) be the base distance and \(y\) the height.",
            "check_in": "Which quantities change as the ladder slides?",
            "check_in_answer": "The base distance and the height; partial credit for one.",
            "key_takeaway": "Variables belong to changing quantities.",
        },
        {
            "title": "Differentiate the relationship",
            "explanation": r"Apply \(\frac{d}{dt}\) to both sides with the chain rule.",
            "worked_example": "",
            "check_in": r"Differentiate \(x^{2} + y^{2} = 100\).",
            "check_in_answer": r"\(2xx' + 2yy' = 0\); partial credit for a missing 2.",
            "key_takeaway": "Every variable picks up its own rate.",
        },
    ],
    "closing_summary": "Name, relate, differentiate, substitute, answer with units.",
}

class _ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, object]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        return CompletionResult(self.responses.pop(0), "completed")


class _LiveDashboardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sensei.db"
        self.error_log = Path(self.temporary.name) / "errors.jsonl"
        self.error_recorder = ErrorRecorder(self.error_log)
        self.service = DashboardService(self.database)
        self.server = None
        self.thread = None

    def tearDown(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.temporary.cleanup()

    def _start(self, **components) -> str:
        self.server = create_server(
            self.service, port=0, error_recorder=self.error_recorder, **components
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://{LOOPBACK_HOST}:{self.server.server_address[1]}"
        with urlopen(f"{self.base_url}/api/dashboard", timeout=5) as response:
            self.csrf_token = json.load(response)["csrf_token"]
        return self.base_url

    def _create_concept(self, name="Related rates", context=""):
        result = self._post("/api/study/plan/create", {
            "subject": "Calculus I", "set_name": "Exam review", "course_profile": "",
            "topics": [{"name": name, "description": context, "materials": []}],
        })
        return result["topics"][0]["id"]

    def _post(self, path: str, document: dict) -> dict:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(document).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "X-Sensei-CSRF": self.csrf_token,
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def _post_error(self, path: str, document: dict) -> tuple[int, dict]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(document).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "X-Sensei-CSRF": self.csrf_token,
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as rejected:
            urlopen(request, timeout=5)
        return rejected.exception.code, json.load(rejected.exception)

    def _get(self, path: str) -> dict:
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.load(response)


class GuidedLessonDashboardTests(_LiveDashboardCase):
    def test_guided_lesson_round_trip_preserves_mastery(self) -> None:
        approved = json.dumps({"approved": True, "reason": "Recomputed."})
        provider = _ScriptedProvider(
            [
                json.dumps(LESSON_DRAFT),
                approved,
                json.dumps({"verdict": "incorrect", "feedback": "Think about what moves."}),
                json.dumps({"verdict": "correct", "feedback": "Both quantities named."}),
                json.dumps({"answer": r"Because \(x\) depends on \(t\)."}),
                json.dumps({"verdict": "partial", "feedback": "Missing a factor of 2."}),
                json.dumps({**LESSON_DRAFT, "title": "Related rates, second pass"}),
                approved,
            ]
        )
        self._start(lesson_factory=LessonFactory(provider))
        skill_id = self._create_concept("Related rates", "Ladders and cones.")
        state = self._get("/api/dashboard")
        self.assertEqual("ready", state["runtime"]["lessons"])
        self.assertEqual(8, state["runtime"]["practice_api_version"])
        topic = next(item for item in state["study_topics"] if item["id"] == skill_id)
        self.assertEqual(("none", 0, 0), (
            topic["lesson_status"], topic["lesson_step"], topic["lesson_step_count"]
        ))

        started = self._post("/api/study/learn/start", {"skill_id": skill_id, "restart": False})
        self.assertTrue(started["generated"])
        self.assertNotIn("check_in_answer", json.dumps(started))
        self.assertEqual(
            {"status": "in_progress", "current_step": 0, "step_count": 2, "completed_at": None},
            started["progress"],
        )
        self.assertEqual([0, 1], [step["index"] for step in started["lesson"]["steps"]])
        self.assertEqual("Name the changing quantities", started["lesson"]["steps"][0]["title"])
        lesson_id = started["lesson"]["id"]
        self.assertIn("Subject: Calculus I", provider.requests[0][-1]["content"])
        self.assertIn("Practice instructions: Ladders and cones.", provider.requests[0][-1]["content"])
        self.assertIn("lesson architect", provider.requests[0][0]["content"])

        wrong = self._post(
            "/api/study/learn/check", {"skill_id": skill_id, "step_index": 0, "answer": "no idea"}
        )
        self.assertEqual("incorrect", wrong["verdict"])
        self.assertEqual(0, wrong["progress"]["current_step"])
        self.assertFalse(wrong["completed"])
        grader_request = provider.requests[2][-1]["content"]
        self.assertIn("Expected answer and rubric: The base distance and the height", grader_request)
        self.assertIn("Learner answer: no idea", grader_request)

        code, body = self._post_error(
            "/api/study/learn/check", {"skill_id": skill_id, "step_index": 1, "answer": "x"}
        )
        self.assertEqual(400, code)
        self.assertIn("earlier steps", body["error"])

        right = self._post(
            "/api/study/learn/check",
            {"skill_id": skill_id, "step_index": 0, "answer": "base and height"},
        )
        self.assertEqual("correct", right["verdict"])
        self.assertEqual(1, right["progress"]["current_step"])
        self.assertFalse(right["completed"])

        asked = self._post(
            "/api/study/learn/ask", {"skill_id": skill_id, "step_index": 0, "question": "Why?"}
        )
        self.assertEqual(r"Because \(x\) depends on \(t\).", asked["answer"])
        self.assertIn("Learner question: Why?", provider.requests[4][-1]["content"])
        self.assertNotIn("partial credit", provider.requests[4][-1]["content"])
        code, body = self._post_error(
            "/api/study/learn/ask", {"skill_id": skill_id, "step_index": 2, "question": "Why?"}
        )
        self.assertEqual(400, code)
        self.assertIn("does not exist", body["error"])

        final = self._post(
            "/api/study/learn/check",
            {"skill_id": skill_id, "step_index": 1, "answer": "2x x' + 2y y'"},
        )
        self.assertEqual("partial", final["verdict"])
        self.assertTrue(final["completed"])
        self.assertEqual("complete", final["progress"]["status"])
        self.assertEqual(2, final["progress"]["current_step"])

        state = self._get("/api/dashboard")
        topic = next(item for item in state["study_topics"] if item["id"] == skill_id)
        self.assertEqual(("complete", 2, 2), (
            topic["lesson_status"], topic["lesson_step"], topic["lesson_step_count"]
        ))
        self.assertEqual(0, topic["attempts_count"])
        self.assertNotIn("check_in_answer", json.dumps(state))

        same = self._post("/api/study/learn/start", {"skill_id": skill_id, "restart": False})
        self.assertFalse(same["generated"])
        self.assertEqual(lesson_id, same["lesson"]["id"])
        self.assertEqual("complete", same["progress"]["status"])
        self.assertEqual(6, len(provider.requests))

        again = self._post("/api/study/learn/start", {"skill_id": skill_id, "restart": True})
        self.assertTrue(again["generated"])
        self.assertEqual(lesson_id, again["lesson"]["id"])
        self.assertEqual("Related rates, second pass", again["lesson"]["title"])
        self.assertEqual("in_progress", again["progress"]["status"])
        self.assertEqual(0, again["progress"]["current_step"])

    def test_lesson_routes_validate_input_and_need_a_factory(self) -> None:
        self._start()
        skill_id = self._create_concept("Limits", "")
        self.assertEqual("unavailable", self._get("/api/dashboard")["runtime"]["lessons"])
        code, body = self._post_error(
            "/api/study/learn/start", {"skill_id": skill_id, "restart": False}
        )
        self.assertEqual(500, code)
        self.assertIn("could not build the lesson", body["error"])
        code, _ = self._post_error(
            "/api/study/learn/start", {"skill_id": skill_id, "restart": "yes"}
        )
        self.assertEqual(400, code)
        code, body = self._post_error(
            "/api/study/learn/start", {"skill_id": "missing-topic", "restart": False}
        )
        self.assertEqual(400, code)
        code, _ = self._post_error(
            "/api/study/learn/check", {"skill_id": skill_id, "step_index": "1", "answer": "x"}
        )
        self.assertEqual(400, code)
        code, _ = self._post_error(
            "/api/study/learn/check", {"skill_id": skill_id, "step_index": True, "answer": "x"}
        )
        self.assertEqual(400, code)
        code, body = self._post_error(
            "/api/study/learn/ask", {"skill_id": skill_id, "step_index": 0, "question": "  "}
        )
        self.assertEqual(400, code)
        self.assertIn("Type a question", body["error"])
        code, _ = self._post_error(
            "/api/study/learn/check", {"skill_id": skill_id, "answer": "x"}
        )
        self.assertEqual(400, code)


class _StubPlanScanner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def scan(self, media_bytes, *, filename, media_type, subject_hint="", set_name_hint=""):
        self.calls.append(
            {
                "size": len(media_bytes),
                "filename": filename,
                "media_type": media_type,
                "subject_hint": subject_hint,
                "set_name_hint": set_name_hint,
            }
        )
        return StudyPlan(
            subject=subject_hint or "MAC2311 Calculus I",
            set_name=set_name_hint or "Test 1",
            course_profile="Calculator in radian mode.",
            topics=(
                PlannedTopic(
                    "Limits from a table",
                    "1.2",
                    "Estimate a limit from a table of values.",
                    (
                        MaterialProposal(
                            "example_problem",
                            "[Graph of f with a hole at (2, 1/2).] Find the limit at 2.",
                            "L = 1/2",
                            "Exercise 12",
                        ),
                    ),
                ),
                PlannedTopic("Squeeze theorem", "1.4", "Bound h(x) between two functions.", ()),
                PlannedTopic(
                    "Vertical asymptotes versus holes", "1.5", "Classify discontinuities.", ()
                ),
            ),
        )


class StudyPlanDashboardTests(_LiveDashboardCase):
    def test_study_guide_scan_and_plan_creation_round_trip(self) -> None:
        provider = _ScriptedProvider(
            [json.dumps(MULTI_PART_DRAFT), json.dumps({"approved": True, "reason": "Recomputed."})]
        )
        scanner = _StubPlanScanner()
        self._start(
            adaptive_factory=AdaptiveQuestFactory(provider), study_plan_scanner=scanner
        )
        state = self._get("/api/dashboard")
        self.assertEqual("ready", state["runtime"]["study_plan_scan"])

        scanned = self._post(
            "/api/study/plan/scan",
            {
                "filename": "MAC2311_test_1_study_guide.pdf",
                "media_base64": _base64.b64encode(b"%PDF-1.7 guide").decode("ascii"),
                "media_type": "application/pdf",
                "subject_hint": "",
                "set_name_hint": "Test 1",
            },
        )
        plan = scanned["plan"]
        self.assertEqual(3, len(plan["topics"]))
        self.assertEqual(1, plan["material_count"])
        self.assertEqual("Test 1", scanner.calls[0]["set_name_hint"])
        self.assertEqual("application/pdf", scanner.calls[0]["media_type"])

        created = self._post(
            "/api/study/plan/create",
            {
                "subject": plan["subject"],
                "set_name": plan["set_name"],
                "course_profile": plan["course_profile"],
                "topics": plan["topics"][:2],
            },
        )
        self.assertEqual("Test 1", created["folder"]["name"])
        self.assertEqual(2, len(created["topics"]))
        self.assertEqual(2, created["created_topics"])
        self.assertEqual(1, created["added_materials"])
        self.assertTrue(created["profile_saved"])
        self.assertEqual("Section 1.2", created["topics"][0]["unit"])

        state = self._get("/api/dashboard")
        self.assertEqual(2, len(state["study_topics"]))
        self.assertEqual(1, len(state["study_guides"]))
        self.assertEqual(2, len(state["study_guides"][0]["concepts"]))

        generated = self._post("/api/study/generate", {"skill_id": created["topics"][0]["id"]})
        self.assertEqual(1, generated["quest"]["material_count"])
        prompt = provider.requests[0][-1]["content"]
        self.assertIn("[1] (Exercise 12)", prompt)
        self.assertIn("Course profile: Calculator in radian mode.", prompt)
        self.assertIn("Topic or skill: Limits from a table", prompt)

        code, error = self._post_error(
            "/api/study/plan/create",
            {"subject": "X", "set_name": "T", "course_profile": "", "topics": []},
        )
        self.assertEqual(400, code)
        self.assertIn("1 to 40", error["error"])

    def test_plan_scan_requires_a_scanner_and_a_valid_upload(self) -> None:
        self._start()
        state = self._get("/api/dashboard")
        self.assertEqual("unavailable", state["runtime"]["study_plan_scan"])
        upload = {
            "filename": "guide.pdf",
            "media_base64": _base64.b64encode(b"%PDF-1.7 guide").decode("ascii"),
            "media_type": "application/pdf",
            "subject_hint": "",
            "set_name_hint": "",
        }
        code, error = self._post_error("/api/study/plan/scan", upload)
        self.assertEqual(500, code)
        self.assertIn("could not analyze", error["error"])
        code, error = self._post_error(
            "/api/study/plan/scan", {**upload, "media_base64": "not base64!"}
        )
        self.assertEqual(400, code)
        self.assertIn("invalid", error["error"])


class PracticeDashboardTests(_LiveDashboardCase):
    def test_fresh_state_and_retired_routes(self):
        self._start()
        state = self._get("/api/dashboard")
        self.assertEqual([], state["study_guides"])
        self.assertEqual([], state["study_topics"])
        self.assertEqual([], state["recent_attempts"])
        for key in ("profile", "catalog", "quests", "skills", "topic_folders"):
            self.assertNotIn(key, state)
        for path in ("/api/study/focus", "/api/folders/create", "/api/study/materials/add", "/api/quest/generate"):
            self.assertEqual(404, self._post_error(path, {})[0])
        request = Request(self.base_url + "/api/study/plan/create", data=b"{}",
                          headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as denied:
            urlopen(request)
        self.assertEqual(403, denied.exception.code)

    def test_guide_practice_help_check_and_record_round_trip(self):
        provider = _ScriptedProvider([json.dumps(MULTI_PART_DRAFT),
                                      json.dumps({"approved": True, "reason": "Checked"})])
        self._start(adaptive_factory=AdaptiveQuestFactory(provider))
        skill_id = self._create_concept()
        generated = self._post("/api/study/generate", {"skill_id": skill_id})
        token = generated["challenge_token"]
        self.assertNotIn('"answer": "-3/2"', json.dumps(generated))
        reveal = self._post("/api/practice/help", {"challenge_token": token})
        self.assertEqual(1, reveal["hints_used"])
        self.assertNotIn("reward", reveal)
        checked = self._post("/api/practice/check", {
            "challenge_token": token, "answer": {"a": "-3/2", "b": "(4, 10)", "c": "C"}})
        self.assertEqual("correct", checked["outcome"])
        saved = self._post("/api/practice/record", {"attempt_token": checked["attempt_token"]})
        self.assertGreater(saved["progress"]["mastery_evidence"], 0)
        self.assertNotIn("xp_awarded", saved["progress"])
        self.assertEqual(400, self._post_error("/api/practice/record", {
            "attempt_token": checked["attempt_token"]})[0])
        state = self._get("/api/dashboard")
        self.assertEqual(1, len(state["recent_attempts"]))
        self.assertEqual("learn", state["study_guides"][0]["next"]["action"])
