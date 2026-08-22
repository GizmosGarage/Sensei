import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from sensei.dashboard import (
    LOOPBACK_HOST,
    DashboardService,
    create_server,
    rank_name,
)


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
        self.assertNotIn("sample_answer", state["next_quest"])
        self.assertNotIn("verification", state["next_quest"])
        self.assertEqual("Local SQLite", state["runtime"]["storage"])
        self.assertEqual(20, state["catalog"]["quest_count"])

    def test_rank_names_advance_at_documented_thresholds(self) -> None:
        self.assertEqual("Dojo Novice", rank_name(1))
        self.assertEqual("Limit Initiate", rank_name(2))
        self.assertEqual("Derivative Adept", rank_name(4))
        self.assertEqual("Integral Scholar", rank_name(7))
        self.assertEqual("Calculus Master", rank_name(10))

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
                self.assertEqual(17, len(state["skills"]))
            with urlopen(f"{base_url}/", timeout=5) as response:
                html = response.read().decode("utf-8")
                self.assertIn("Sensei // Calculus Dojo", html)
                self.assertIn("/assets/app.js", html)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
