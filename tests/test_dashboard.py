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
        self.assertEqual(40, state["catalog"]["quest_count"])
        self.assertEqual(20, state["catalog"]["courses"]["precalculus"])
        self.assertEqual(37, state["catalog"]["generated_skill_count"])
        self.assertEqual(37, len(state["skills"]))

    def test_rank_names_advance_at_documented_thresholds(self) -> None:
        self.assertEqual("Dojo Novice", rank_name(1))
        self.assertEqual("Foundation Initiate", rank_name(2))
        self.assertEqual("Algebra Adept", rank_name(4))
        self.assertEqual("Function Scholar", rank_name(7))
        self.assertEqual("Math Master", rank_name(10))

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
                self.assertIn("Sensei // Math Dojo", html)
                self.assertIn("Precalculus subjects", html)
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
