import json
import random
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sensei.dashboard import (
    LOOPBACK_HOST,
    DashboardService,
    create_server,
    rank_name,
)
from sensei.generation import GeneratedQuestFactory
from sensei.learning import LearningEvent, Outcome
from sensei.practice import AdaptiveQuestFactory
from sensei.providers import CompletionResult
from sensei.storage import LearningStore


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sensei.db"
        self.service = DashboardService(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_state_is_local_and_does_not_expose_quest_answers(self) -> None:
        state = self.service.state()
        self.assertEqual("Dojo Novice", state["profile"]["rank_name"])
        self.assertEqual("calculus_foundations", state["next_quest"]["skill_id"])
        self.assertEqual(
            "precalc_exponent_properties",
            state["next_quests"]["precalculus"]["skill_id"],
        )
        self.assertNotIn("sample_answer", state["next_quest"])
        self.assertNotIn("verification", state["next_quest"])
        for quest in state["quests"]:
            self.assertNotIn("sample_answer", quest)
            self.assertNotIn("verification", quest)
        self.assertEqual("Local SQLite", state["runtime"]["storage"])
        self.assertEqual(2, state["runtime"]["practice_api_version"])
        self.assertEqual(40, state["catalog"]["quest_count"])
        self.assertEqual(20, state["catalog"]["courses"]["precalculus"])
        self.assertEqual(37, state["catalog"]["generated_skill_count"])
        self.assertEqual(37, len(state["skills"]))

    def test_rank_names_advance_at_documented_thresholds(self) -> None:
        self.assertEqual("Dojo Novice", rank_name(1))
        self.assertEqual("Quest Initiate", rank_name(2))
        self.assertEqual("Dojo Adept", rank_name(4))
        self.assertEqual("Realm Scholar", rank_name(7))
        self.assertEqual("Grand Sensei", rank_name(10))

    def test_recommendation_can_select_a_generated_only_calculus_subject(self) -> None:
        with LearningStore(self.database) as store:
            store.record_event(
                LearningEvent(
                    skill_id="continuity",
                    outcome=Outcome.INCORRECT,
                    misconception="Used the point value instead of the limit.",
                    evidence="The proposed value did not match the limiting value.",
                    confidence=1.0,
                    problem="Choose k for continuity.",
                    hints_used=0,
                    solution_revealed=False,
                    tutor_turns=1,
                )
            )
        state = self.service.state()
        self.assertEqual("continuity", state["next_quests"]["calculus"]["skill_id"])

    def test_loopback_server_serves_health_api_and_dashboard_assets(self) -> None:
        server = create_server(self.service, port=0)
        self.assertEqual(LOOPBACK_HOST, server.server_address[0])
        self.assertIn(b"Sensei // Adaptive Dojo", server.assets["/"][0])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/healthz", timeout=5) as response:
                health = json.load(response)
                self.assertEqual(200, response.status)
                self.assertTrue(health["local"])
                self.assertEqual("DENY", response.headers["X-Frame-Options"])
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
                self.assertEqual(37, len(state["skills"]))
                self.assertTrue(state["csrf_token"])
            with urlopen(f"{base_url}/", timeout=5) as response:
                html = response.read().decode("utf-8")
                self.assertIn("Sensei // Adaptive Dojo", html)
                self.assertIn("What do you want to master?", html)
                self.assertIn("/assets/app.js", html)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_checks_and_records_a_precalculus_quest_once(self) -> None:
        seed = 443
        expected_quest = GeneratedQuestFactory(
            random.Random(seed)
        ).generate("precalc_linear_equations")
        server = create_server(
            self.service,
            port=0,
            quest_factory=GeneratedQuestFactory(random.Random(seed)),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"

        def post(path: str, document: dict[str, str], token: str):
            request = Request(
                f"{base_url}{path}",
                data=json.dumps(document).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": token,
                },
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)

        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
            csrf_token = state["csrf_token"]
            status, generated = post(
                "/api/quest/generate",
                {"skill_id": "precalc_linear_equations"},
                csrf_token,
            )
            self.assertEqual(200, status)
            self.assertEqual(
                "precalc_linear_equations",
                generated["quest"]["skill_id"],
            )
            self.assertNotIn("sample_answer", generated["quest"])
            self.assertNotIn("verification", generated["quest"])
            status, checked = post(
                "/api/quest/check",
                {
                    "challenge_token": generated["challenge_token"],
                    "answer": expected_quest.sample_answer,
                },
                csrf_token,
            )
            self.assertEqual(200, status)
            self.assertEqual("verified_correct", checked["result"]["status"])
            self.assertTrue(checked["attempt_token"])

            status, recorded = post(
                "/api/quest/record",
                {"attempt_token": checked["attempt_token"]},
                csrf_token,
            )
            self.assertEqual(200, status)
            self.assertEqual(25, recorded["progress"]["xp_awarded"])
            self.assertEqual(1, recorded["profile"]["attempts"])
            with self.assertRaises(HTTPError) as replay:
                post(
                    "/api/quest/record",
                    {"attempt_token": checked["attempt_token"]},
                    csrf_token,
                )
            self.assertEqual(400, replay.exception.code)

            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                updated = json.load(response)
            self.assertEqual("precalculus", updated["recent_attempts"][0]["course"])
            self.assertTrue(
                updated["recent_attempts"][0]["quest_id"].startswith(
                    "generated-precalc-linear-equations-"
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_builds_checks_and_records_a_learner_created_topic(self) -> None:
        draft = json.dumps(
            {
                "title": "Mole Ratio Gate",
                "prompt": "Which tool converts between substances in a reaction?",
                "answer_type": "multiple_choice",
                "answer": "C",
                "options": [
                    "Atomic number",
                    "Temperature scale",
                    "Balanced-equation coefficients",
                    "Density alone",
                ],
                "hint": "Read the integers before each formula.",
                "solution": "Balanced coefficients define the reaction's mole ratios.",
                "graph": None,
            }
        )
        fresh_draft = json.dumps(
            {
                "title": "Reaction Ratio Gate",
                "prompt": (
                    "In N2 + 3 H2 -> 2 NH3, which coefficient gives the moles "
                    "of H2 consumed per mole of N2?"
                ),
                "answer_type": "multiple_choice",
                "answer": "C",
                "options": ["1", "2", "3", "6"],
                "hint": "Compare the coefficients before N2 and H2.",
                "solution": "The equation has a 1:3 mole ratio, so C is correct.",
                "graph": None,
            }
        )

        class Provider:
            def __init__(self) -> None:
                self.requests = []
                self.responses = [
                    draft,
                    json.dumps({"approved": True, "reason": "Checked."}),
                    draft,
                    fresh_draft,
                    json.dumps({"approved": True, "reason": "Checked."}),
                ]

            def complete(self, messages, on_token=None):
                self.requests.append(list(messages))
                return CompletionResult(self.responses.pop(0), "stop")

        provider = Provider()
        server = create_server(
            self.service,
            port=0,
            adaptive_factory=AdaptiveQuestFactory(provider),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"

        def post(path: str, document: dict[str, str], token: str):
            request = Request(
                f"{base_url}{path}",
                data=json.dumps(document).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": token,
                },
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            focus = post(
                "/api/study/focus",
                {
                    "subject": "Chemistry",
                    "topic": "Stoichiometry",
                    "context": "Mole ratios",
                    "difficulty": "beginner",
                },
                csrf_token,
            )
            skill_id = focus["study_topic"]["id"]
            generated = post(
                "/api/study/generate",
                {"skill_id": skill_id, "difficulty": "beginner"},
                csrf_token,
            )
            self.assertEqual("Chemistry", generated["quest"]["subject"])
            self.assertEqual("beginner", generated["quest"]["difficulty"])
            self.assertIsNone(generated["quest"]["graph"])
            self.assertNotIn("answer", generated["quest"])
            generated_again = post(
                "/api/study/generate",
                {"skill_id": skill_id, "difficulty": "expert"},
                csrf_token,
            )
            self.assertEqual("expert", generated_again["quest"]["difficulty"])
            self.assertNotEqual(
                generated["quest"]["prompt"],
                generated_again["quest"]["prompt"],
            )
            checked = post(
                "/api/quest/check",
                {
                    "challenge_token": generated_again["challenge_token"],
                    "answer": "C",
                },
                csrf_token,
            )
            self.assertEqual("verified_correct", checked["result"]["status"])
            self.assertIn("mole ratio", checked["solution"])
            recorded = post(
                "/api/quest/record",
                {"attempt_token": checked["attempt_token"]},
                csrf_token,
            )
            self.assertEqual(25, recorded["progress"]["xp_awarded"])
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
            self.assertEqual("Stoichiometry", state["study_topics"][0]["name"])
            self.assertEqual("expert", state["study_topics"][0]["difficulty"])
            self.assertEqual(1, state["study_topics"][0]["attempts_count"])
            self.assertIn(
                "Beginner (level 1 of 4)",
                provider.requests[0][-1]["content"],
            )
            self.assertIn(
                "Expert (level 4 of 4)",
                provider.requests[2][-1]["content"],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_rejects_a_write_without_csrf_token(self) -> None:
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        request = Request(
            f"{base_url}/api/quest/generate",
            data=json.dumps(
                {"skill_id": "precalc_linear_equations"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request, timeout=5)
            self.assertEqual(403, rejected.exception.code)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_invalid_adaptive_generation_returns_a_retryable_status(self) -> None:
        skill = self.service.create_study_topic(
            subject="Mathematics",
            topic="Limits",
            context="Practice direct substitution.",
            difficulty="beginner",
        )

        class InvalidProvider:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, messages, on_token=None):
                self.calls += 1
                return CompletionResult("{}", "stop")

        provider = InvalidProvider()
        server = create_server(
            self.service,
            port=0,
            adaptive_factory=AdaptiveQuestFactory(provider),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            request = Request(
                f"{base_url}/api/study/generate",
                data=json.dumps(
                    {"skill_id": skill["id"], "difficulty": "beginner"}
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": csrf_token,
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request, timeout=5)
            self.assertEqual(503, rejected.exception.code)
            self.assertIn("Please try again", json.load(rejected.exception)["error"])
            self.assertEqual(3, provider.calls)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_generation_avoids_an_immediate_repeat_for_one_subject(self) -> None:
        server = create_server(
            self.service,
            port=0,
            quest_factory=GeneratedQuestFactory(random.Random(99)),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"

        def generate(token: str) -> dict[str, object]:
            request = Request(
                f"{base_url}/api/quest/generate",
                data=json.dumps(
                    {"skill_id": "precalc_exponent_properties"}
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": token,
                },
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            first = generate(csrf_token)
            second = generate(csrf_token)
            self.assertNotEqual(
                first["quest"]["prompt"],
                second["quest"]["prompt"],
            )
            self.assertNotEqual(first["challenge_token"], second["challenge_token"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
