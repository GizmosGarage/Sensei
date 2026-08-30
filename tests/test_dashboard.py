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
    ChallengeStore,
    DashboardService,
    PendingAttemptStore,
    create_server,
    rank_name,
)
from sensei.errorlog import ErrorRecorder
from sensei.generation import GeneratedQuestFactory
from sensei.learning import LearningEvent, Outcome
from sensei.practice import AdaptiveQuestFactory
from sensei.providers import CompletionResult
from sensei.storage import LearningStore
from sensei.verification import CalculusVerifier


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sensei.db"
        self.error_log = Path(self.temporary.name) / "errors.jsonl"
        self.error_recorder = ErrorRecorder(self.error_log)
        self.service = DashboardService(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_state_is_local_and_does_not_expose_quest_answers(self) -> None:
        state = self.service.state()
        self.assertEqual("Dojo Novice", state["profile"]["rank_name"])
        for quest in state["quests"]:
            self.assertNotIn("sample_answer", quest)
            self.assertNotIn("verification", quest)
        self.assertEqual("Local SQLite", state["runtime"]["storage"])
        self.assertEqual(5, state["runtime"]["practice_api_version"])
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

    def test_deleted_topic_is_purged_from_in_process_quest_memory(self) -> None:
        skill_id = "precalc_linear_equations"
        challenges = ChallengeStore(GeneratedQuestFactory(random.Random(443)))
        attempts = PendingAttemptStore()
        challenge_token, quest = challenges.issue(skill_id)
        result = quest.check(quest.sample_answer, CalculusVerifier())
        attempt_token = attempts.issue(quest, result)

        challenges.discard_skill(skill_id)
        attempts.discard_skill(skill_id)

        with self.assertRaisesRegex(ValueError, "missing or expired"):
            challenges.get(challenge_token)
        with self.assertRaisesRegex(ValueError, "missing, expired"):
            attempts.consume(attempt_token)
        self.assertNotIn(skill_id, challenges._last_prompts)

    def test_loopback_server_serves_health_api_and_dashboard_assets(self) -> None:
        server = create_server(
            self.service,
            port=0,
            error_recorder=self.error_recorder,
        )
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
                self.assertIn("Forge a questline", html)
                self.assertIn("Start practice chat", html)
                self.assertIn("Ask Sensei for help", html)
                self.assertNotIn("Ask Sensei for a hint", html)
                self.assertIn("Your study brief", html)
                self.assertIn("Practice instructions", html)
                self.assertIn("Next problem", html)
                self.assertIn('data-view="profile"', html)
                self.assertIn('data-view="past-quest"', html)
                self.assertIn('id="subject-filters"', html)
                self.assertIn("file its topics into named folders", html)
                self.assertIn('class="delete-topic-button"', html)
                self.assertIn('id="folder-dialog"', html)
                self.assertNotIn("Name the quest.", html)
                self.assertIn("/assets/app.js", html)
            with urlopen(f"{base_url}/assets/app.js", timeout=5) as response:
                javascript = response.read().decode("utf-8")
                self.assertIn("It cannot be recovered once deleted.", javascript)
                self.assertIn(
                    'function openArena(quest) {\n  byId("chat-history").replaceChildren();',
                    javascript,
                )
                self.assertNotIn("function archiveActiveTurn()", javascript)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_deletes_one_topic_and_all_of_its_learning_data(self) -> None:
        with LearningStore(self.database) as store:
            topic = store.create_study_topic(
                subject="Chemistry",
                topic="Stoichiometry",
                context="Mole ratios",
            )
            store.record_event(
                LearningEvent(
                    skill_id=topic["id"],
                    outcome=Outcome.INCORRECT,
                    misconception="Skipped the mole ratio.",
                    evidence="The response used a 1:1 ratio.",
                    confidence=1.0,
                    problem="Convert reactant moles to product moles.",
                    hints_used=0,
                    solution_revealed=False,
                    tutor_turns=1,
                )
            )

        server = create_server(
            self.service,
            port=0,
            error_recorder=self.error_recorder,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            request = Request(
                f"{base_url}/api/study/delete",
                data=json.dumps({"skill_id": topic["id"]}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": csrf_token,
                },
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                deletion = json.load(response)["deleted_topic"]
            self.assertEqual(topic["id"], deletion["skill_id"])
            self.assertEqual(1, deletion["deleted_attempts"])

            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
            self.assertEqual([], state["study_topics"])
            self.assertEqual([], state["recent_attempts"])
            self.assertEqual(0, state["profile"]["attempts"])
            self.assertEqual(0, state["profile"]["total_xp"])
            with LearningStore(self.database) as store:
                self.assertEqual(
                    0,
                    store.connection.execute(
                        "SELECT COUNT(*) FROM skills WHERE id = ?", (topic["id"],)
                    ).fetchone()[0],
                )
                self.assertEqual(
                    [], list(store.connection.execute("PRAGMA foreign_key_check"))
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_creates_edits_and_removes_subject_folders(self) -> None:
        with LearningStore(self.database) as store:
            first = store.create_study_topic(
                subject="Chemistry", topic="Stoichiometry", context="Mole ratios"
            )
            second = store.create_study_topic(
                subject="Chemistry", topic="Lewis structures", context="Valence electrons"
            )

        server = create_server(
            self.service,
            port=0,
            error_recorder=self.error_recorder,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]

            def post(path: str, document: dict[str, object]) -> dict[str, object]:
                request = Request(
                    f"{base_url}{path}",
                    data=json.dumps(document).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": base_url,
                        "X-Sensei-CSRF": csrf_token,
                    },
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    return json.load(response)

            created = post(
                "/api/folders/create",
                {
                    "subject": "Chemistry",
                    "name": "Exam review",
                    "skill_ids": [first["id"]],
                },
            )["topic_folder"]
            self.assertEqual([first["id"]], created["topic_ids"])

            updated = post(
                "/api/folders/update",
                {
                    "folder_id": created["id"],
                    "name": "Final review",
                    "skill_ids": [first["id"], second["id"]],
                },
            )["topic_folder"]
            self.assertEqual("Final review", updated["name"])
            self.assertEqual(2, updated["topic_count"])

            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
            self.assertEqual("Final review", state["topic_folders"][0]["name"])
            self.assertEqual(
                {created["id"]},
                {topic["folder_id"] for topic in state["study_topics"]},
            )

            removed = post(
                "/api/folders/delete", {"folder_id": created["id"]}
            )["deleted_folder"]
            self.assertEqual(2, removed["topic_count"])
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                state = json.load(response)
            self.assertEqual([], state["topic_folders"])
            self.assertEqual(2, len(state["study_topics"]))
            self.assertEqual(
                {None}, {topic["folder_id"] for topic in state["study_topics"]}
            )
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
            error_recorder=self.error_recorder,
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

    def test_progressive_help_reveals_one_step_and_zeroes_final_answer_rewards(
        self,
    ) -> None:
        seed = 919
        expected_quest = GeneratedQuestFactory(
            random.Random(seed)
        ).generate("precalc_linear_equations")
        server = create_server(
            self.service,
            port=0,
            quest_factory=GeneratedQuestFactory(random.Random(seed)),
            error_recorder=self.error_recorder,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"

        def post(path: str, document: dict[str, str], token: str) -> dict[str, object]:
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
            generated = post(
                "/api/quest/generate",
                {"skill_id": "precalc_linear_equations"},
                csrf_token,
            )
            challenge_token = generated["challenge_token"]

            first = post(
                "/api/quest/help",
                {"challenge_token": challenge_token},
                csrf_token,
            )
            self.assertEqual(1, first["step_number"])
            self.assertEqual(2, first["total_steps"])
            self.assertFalse(first["final_answer"])
            self.assertNotIn(expected_quest.sample_answer, first["step"])
            self.assertEqual(20, first["reward"]["xp_if_correct"])
            self.assertEqual(
                85.0,
                first["reward"]["mastery_evidence_if_correct"],
            )

            final = post(
                "/api/quest/help",
                {"challenge_token": challenge_token},
                csrf_token,
            )
            self.assertTrue(final["final_answer"])
            self.assertIn(expected_quest.sample_answer, final["step"])
            self.assertEqual(0, final["reward"]["xp_if_correct"])
            self.assertEqual(0.0, final["reward"]["mastery_evidence_if_correct"])

            checked = post(
                "/api/quest/check",
                {
                    "challenge_token": challenge_token,
                    "answer": expected_quest.sample_answer,
                },
                csrf_token,
            )
            recorded = post(
                "/api/quest/record",
                {"attempt_token": checked["attempt_token"]},
                csrf_token,
            )
            self.assertEqual(0, recorded["progress"]["xp_awarded"])
            self.assertEqual(0.0, recorded["progress"]["mastery_evidence"])
            self.assertEqual(0.0, recorded["progress"]["mastery_score"])
            with LearningStore(self.database) as store:
                attempt = store.connection.execute(
                    "SELECT hints_used, solution_revealed FROM attempts"
                ).fetchone()
            self.assertEqual(2, attempt["hints_used"])
            self.assertEqual(1, attempt["solution_revealed"])
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
            error_recorder=self.error_recorder,
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
                },
                csrf_token,
            )
            skill_id = focus["study_topic"]["id"]
            generated = post(
                "/api/study/generate",
                {"skill_id": skill_id},
                csrf_token,
            )
            self.assertEqual("Chemistry", generated["quest"]["subject"])
            self.assertIsNone(generated["quest"]["graph"])
            self.assertNotIn("answer", generated["quest"])
            generated_again = post(
                "/api/study/generate",
                {"skill_id": skill_id},
                csrf_token,
            )
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
            self.assertEqual(1, state["study_topics"][0]["attempts_count"])
            self.assertIn(
                "Topic or skill: Stoichiometry",
                provider.requests[0][-1]["content"],
            )
            self.assertIn(
                "Practice instructions: Mole ratios",
                provider.requests[0][-1]["content"],
            )
            self.assertIn(
                "Topic or skill: Stoichiometry",
                provider.requests[2][-1]["content"],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_rejects_a_write_without_csrf_token(self) -> None:
        server = create_server(
            self.service,
            port=0,
            error_recorder=self.error_recorder,
        )
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

    def test_dashboard_records_browser_and_request_failures_with_error_ids(self) -> None:
        server = create_server(
            self.service,
            port=0,
            error_recorder=self.error_recorder,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"

        def request(path: str, document: dict[str, str], token: str) -> Request:
            return Request(
                f"{base_url}{path}",
                data=json.dumps(document).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url,
                    "X-Sensei-CSRF": token,
                },
                method="POST",
            )

        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            with urlopen(
                request(
                    "/api/errors",
                    {
                        "message": "Render failed",
                        "stack": "at render (app.js:1)",
                        "source": "window.error app.js:1:1",
                    },
                    csrf_token,
                ),
                timeout=5,
            ) as response:
                browser_error_id = json.load(response)["error_id"]
                self.assertEqual(202, response.status)

            with self.assertRaises(HTTPError) as rejected:
                urlopen(
                    request(
                        "/api/quest/record",
                        {"attempt_token": "missing"},
                        csrf_token,
                    ),
                    timeout=5,
                )
            request_error = json.load(rejected.exception)
            self.assertEqual(400, rejected.exception.code)
            self.assertTrue(request_error["error_id"].startswith("SEN-"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        records = [
            json.loads(line)
            for line in self.error_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(2, len(records))
        self.assertEqual(browser_error_id, records[0]["error_id"])
        self.assertEqual("dashboard.browser", records[0]["component"])
        self.assertEqual("dashboard.request", records[1]["component"])
        self.assertEqual("validate dashboard request", records[1]["operation"])

    def test_invalid_adaptive_generation_returns_a_retryable_status(self) -> None:
        skill = self.service.create_study_topic(
            subject="Mathematics",
            topic="Limits",
            context="Practice direct substitution.",
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
            error_recorder=self.error_recorder,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://{LOOPBACK_HOST}:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/dashboard", timeout=5) as response:
                csrf_token = json.load(response)["csrf_token"]
            request = Request(
                f"{base_url}/api/study/generate",
                data=json.dumps({"skill_id": skill["id"]}).encode("utf-8"),
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
            self.assertEqual(4, provider.calls)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_generation_avoids_an_immediate_repeat_for_one_subject(self) -> None:
        server = create_server(
            self.service,
            port=0,
            quest_factory=GeneratedQuestFactory(random.Random(99)),
            error_recorder=self.error_recorder,
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
