"""API and dashboard availability while Discord is down (edge-banned)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import cloudbreaker


class ApiDuringDiscordDowntime(unittest.TestCase):
    """The FastAPI app must answer 200 on /health and /api/status even while
    cloudbreaker is EDGE_BLOCKED — Render must not restart a working service
    because Discord is banned, and the dashboard must stay live."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.server import create_app
        cls.client = TestClient(create_app())

    def setUp(self):
        cloudbreaker._reset_for_tests()
        # Isolate the persisted-state file so tests never touch bot/.rest_state.json
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_state_file = cloudbreaker._STATE_FILE
        cloudbreaker._STATE_FILE = os.path.join(self._tmpdir.name, ".rest_state.json")

    def tearDown(self):
        cloudbreaker._STATE_FILE = self._old_state_file
        cloudbreaker._reset_for_tests()
        self._tmpdir.cleanup()

    def test_health_200_while_edge_blocked(self):
        cloudbreaker.report_ban(3076, cf_ray="downtime-ray")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn(body["status"], ("ok", "degraded"))

    def test_status_reports_cooldown_while_banned(self):
        cloudbreaker.report_ban(3076, cf_ray="downtime-ray")
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["web"]["status"], "online")
        rest = data["rest"]
        self.assertEqual(rest["state"], "EDGE_BLOCKED")
        self.assertGreaterEqual(rest["cooldown_remaining_s"], 3075)
        self.assertIsNotNone(rest["next_attempt_utc"])
        # Never leaks secrets.
        raw = resp.text.lower()
        self.assertNotIn("authorization", raw)
        self.assertNotIn("bot token", raw)

    def test_dashboard_served_while_banned(self):
        cloudbreaker.report_ban(3076)
        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Discord Gateway", resp.text)
        self.assertIn("cooldown_remaining_s", resp.text)
        self.assertIn("EDGE_BLOCKED", resp.text)  # new state name in page JS

    def test_status_ok_when_healthy(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["rest"]["state"], "CONNECTED")
        self.assertFalse(data["rest"]["banned"])

    def test_lavalink_status_reported(self):
        """Lavalink status must be present and honest (never 'connected'
        unless a real node is connected in the pool)."""
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        lv = resp.json().get("lavalink", {})
        self.assertIn(lv.get("status"), ("connected", "disconnected", "unavailable", "unknown"))
        if lv.get("status") == "connected":
            self.assertGreater(lv.get("connected") or 0, 0)


if __name__ == "__main__":
    unittest.main()
