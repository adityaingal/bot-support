"""Automated tests for utils.cloudbreaker (mocked HTTP, no live Discord)."""

import os
import sys
import json
import time
import asyncio
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import cloudbreaker as cb


class FakeResponse:
    def __init__(self, headers=None):
        self.headers = headers or {}


class FakeHTTPException(Exception):
    def __init__(self, status=429, text="", headers=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.text = text
        self.response = FakeResponse(headers)


class CloudbreakerTests(unittest.TestCase):
    def setUp(self):
        cb._reset_for_tests()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_state_file = cb._STATE_FILE
        cb._STATE_FILE = os.path.join(self._tmpdir.name, ".rest_state.json")

    def tearDown(self):
        cb._STATE_FILE = self._old_state_file
        cb._reset_for_tests()
        self._tmpdir.cleanup()

    # --- Retry-After: 60 seconds (route-level limit, no suppression) ---

    def test_retry_after_60_route_limit(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "60",
                                          "X-RateLimit-Remaining": "0"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_RATE_LIMITED)
        self.assertEqual(cb.seconds_left(), 0.0)

    def test_retry_after_535_route_limit(self):
        """The exact production case: 535s on login, no suppression."""
        exc = FakeHTTPException(429, "", {"Retry-After": "535",
                                          "CF-RAY": "a53a47218b2bd25b-SIN",
                                          "X-RateLimit-Remaining": "0"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_RATE_LIMITED)
        self.assertEqual(cb.parse_retry_after(exc), 535.0)

    # --- Retry-After: 3076 seconds (edge ban, full cooldown honoured) ---

    def test_retry_after_3076_edge_ban_full_cooldown(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "3076", "CF-RAY": "abc-SIN"})
        cb._maybe_report_edge_ban(exc)
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_EDGE_BLOCKED)
        self.assertGreaterEqual(cb.seconds_left(), 3075)
        # The wait must be the FULL server cooldown — never a 60s/300s poll.
        wait = cb.suggested_wait()
        self.assertGreaterEqual(wait, 3000)
        self.assertLessEqual(wait, 3076)
        snap = cb.snapshot()
        self.assertEqual(snap["cf_ray"], "abc-SIN")
        self.assertEqual(snap["classification"], "edge_429")
        self.assertIsNotNone(snap["next_attempt_utc"])
        self.assertGreaterEqual(snap["cooldown_remaining_s"], 3075)

    # --- Missing / malformed Retry-After ---

    def test_missing_retry_after(self):
        exc = FakeHTTPException(429, "", {"CF-RAY": "x"})
        cb._maybe_report_edge_ban(exc)  # must not raise
        self.assertFalse(cb.is_banned())

    def test_malformed_retry_after_header_json_body_fallback(self):
        # Header garbage, JSON body carries the real value.
        exc = FakeHTTPException(429, '{"retry_after": 1234.5, "global": false}',
                                {"Retry-After": "not-a-number"})
        self.assertEqual(cb.parse_retry_after(exc), 1234.5)
        cb._maybe_report_edge_ban(exc)
        self.assertTrue(cb.is_banned())
        self.assertGreaterEqual(cb.seconds_left(), 1234)

    def test_malformed_retry_after_http_date_and_html(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "Fri, 21 Oct 2099 00:00:00 GMT"})
        cb._maybe_report_edge_ban(exc)  # must not raise
        exc2 = FakeHTTPException(429, "<!DOCTYPE html><html>error 1015</html>",
                                 {"Retry-After": "3600"})
        cb._maybe_report_edge_ban(exc2)
        self.assertTrue(cb.is_banned())

    def test_parse_retry_after_takes_longest(self):
        exc = FakeHTTPException(429, '{"retry_after": 3076}', {"Retry-After": "60"})
        self.assertEqual(cb.parse_retry_after(exc), 3076.0)
        exc2 = FakeHTTPException(429, '{"retry_after": 30}', {"Retry-After": "3076"})
        self.assertEqual(cb.parse_retry_after(exc2), 3076.0)

    # --- Repeated 429s update the cooldown (extend-only) ---

    def test_repeated_429_extends_only_forward(self):
        cb.report_ban(100)
        first = cb._blocked_until_mono
        cb.report_ban(50)
        self.assertGreaterEqual(cb._blocked_until_mono, first)
        cb.report_ban(3076)
        self.assertGreater(cb._blocked_until_mono, first)
        self.assertGreaterEqual(cb.seconds_left(), 3075)

    def test_html_1015(self):
        exc = FakeHTTPException(429, "<!DOCTYPE html><html>error 1015</html>",
                                {"Retry-After": "3600"})
        cb._maybe_report_edge_ban(exc)
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb._classification, "cloudflare_1015")

    def test_long_429_with_rl_headers_not_suppressed(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "700",
                                          "X-RateLimit-Scope": "shared"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())

    def test_non_429_ignored(self):
        exc = FakeHTTPException(500, "boom")
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())

    def test_auth_failure_401_ignored_by_breaker(self):
        """401 = invalid token: a fatal verdict handled by the login loop,
        never a rate-limit event."""
        exc = FakeHTTPException(401, '{"message": "401: Unauthorized", "code": 0}')
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_CONNECTED)

    # --- Successful recovery after cooldown ---

    def test_recovery_after_cooldown_expiry(self):
        cb.report_ban(5)
        self.assertTrue(cb.is_banned())
        # Simulate cooldown expiry (monotonic deadline in the past).
        cb._blocked_until_mono = time.monotonic() - 1
        self.assertFalse(cb.is_banned())
        cb.report_ok()
        # No event loop in this test -> warmup falls back straight to CONNECTED.
        self.assertEqual(cb.state(), cb.STATE_CONNECTED)
        self.assertFalse(cb.is_banned())

    def test_recovery_warmup_passes_through_recovering(self):
        """With a running loop: report_ok enters RECOVERING, then CONNECTED."""
        old_hold = cb.WARMUP_HOLD
        cb.WARMUP_HOLD = 0.05

        async def run():
            cb.report_ban(5)
            cb._blocked_until_mono = time.monotonic() - 1
            cb.report_ok()
            self.assertEqual(cb.state(), cb.STATE_RECOVERING)
            await asyncio.sleep(0.2)
            self.assertEqual(cb.state(), cb.STATE_CONNECTED)

        try:
            asyncio.run(run())
        finally:
            cb.WARMUP_HOLD = old_hold

    def test_report_ok_clears_immediately(self):
        cb.report_ban(1500, cf_ray="xyz")
        self.assertTrue(cb.is_banned())
        cb.report_ok()
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_CONNECTED)  # no loop in tests

    # --- Lifecycle states ---

    def test_lifecycle_states(self):
        cb.report_starting()
        self.assertEqual(cb.state(), cb.STATE_STARTING)
        cb.report_connecting()
        self.assertEqual(cb.state(), cb.STATE_CONNECTING)
        cb.report_connected()
        self.assertEqual(cb.state(), cb.STATE_CONNECTED)
        cb.report_ban(600)
        cb.report_connected()  # must NOT override an active ban
        self.assertEqual(cb.state(), cb.STATE_EDGE_BLOCKED)
        cb._blocked_until_mono = time.monotonic() - 1
        cb.report_ok()
        cb.report_degraded("db")
        self.assertEqual(cb.state(), cb.STATE_DEGRADED)
        cb.report_failed("bad token")
        self.assertEqual(cb.state(), cb.STATE_FAILED)
        cb.report_degraded("db")  # FAILED is terminal for degradation
        self.assertEqual(cb.state(), cb.STATE_FAILED)

    # --- Suggested wait: full cooldown, never a poll interval ---

    def test_suggested_wait_is_full_cooldown(self):
        cb.report_ban(3600)
        w = cb.suggested_wait()
        self.assertGreaterEqual(w, 3500)
        self.assertLessEqual(w, 3600)
        cb._reset_for_tests()
        cb.report_ban(60)  # near expiry
        w2 = cb.suggested_wait()
        self.assertLessEqual(w2, 60)
        self.assertGreaterEqual(w2, 55)

    # --- Persistence round-trip restores an active ban ---

    def test_persistence_roundtrip(self):
        cb.report_ban(900, cf_ray="persist-ray", classification="edge_429")
        self.assertTrue(os.path.exists(cb._STATE_FILE))
        with open(cb._STATE_FILE) as f:
            data = json.load(f)
        self.assertEqual(data["last_cf_ray"], "persist-ray")
        cb._reset_for_tests()
        self.assertFalse(cb.is_banned())
        cb._load_persisted()
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb._last_cf_ray, "persist-ray")

    def test_stale_persisted_discarded(self):
        stale = {"state": "EDGE_BLOCKED", "detected_at": time.time() - 99999,
                 "retry_after": 100, "last_cf_ray": None, "classification": "edge_429",
                 "last_http_status": 429}
        with open(cb._STATE_FILE, "w") as f:
            json.dump(stale, f)
        cb._load_persisted()
        self.assertFalse(cb.is_banned())

    def test_persistence_has_no_secrets(self):
        cb.report_ban(600)
        with open(cb._STATE_FILE) as f:
            content = f.read().lower()
        self.assertNotIn("token", content)
        self.assertNotIn("authorization", content)

    # --- Duplicate login prevention ---

    def test_login_guard(self):
        self.assertTrue(cb.begin_login())
        self.assertFalse(cb.begin_login())  # second attempt blocked
        cb.end_login()
        self.assertTrue(cb.begin_login())
        cb.end_login()

    def test_snapshot_reports_login_slot(self):
        cb.begin_login()
        self.assertTrue(cb.snapshot()["login_in_flight"])
        cb.end_login()
        self.assertFalse(cb.snapshot()["login_in_flight"])

    # --- Probe lock single-flight ---

    def test_probe_lock_single_flight(self):
        async def run():
            lock = cb._get_probe_lock()
            self.assertFalse(lock.locked())
            await lock.acquire()
            self.assertTrue(lock.locked())
            lock.release()
        asyncio.run(run())

    def test_ban_error_type(self):
        self.assertTrue(issubclass(cb.CloudflareBanError, RuntimeError))

    # --- 429 body-kind classification (Cloudflare HTML vs Discord JSON) ---

    def test_body_kind_detection(self):
        self.assertEqual(cb._body_kind_of(FakeHTTPException(429, "<html>cf</html>")), "html")
        self.assertEqual(cb._body_kind_of(FakeHTTPException(429, '{"retry_after": 1}')), "json")
        self.assertEqual(cb._body_kind_of(FakeHTTPException(429, "")), "empty")
        self.assertEqual(cb._body_kind_of(FakeHTTPException(429, "plain text")), "other")

    def test_global_json_limit_recorded_not_suppressed(self):
        exc = FakeHTTPException(429, '{"retry_after": 0.5, "global": true, "message": "You are being rate limited."}',
                                {})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_RATE_LIMITED)
        self.assertEqual(cb.snapshot()["classification"], "global_limit")
        self.assertEqual(cb.snapshot()["body_kind"], "json")

    def test_cf_unclassified_recorded_not_suppressed(self):
        """CF-RAY + short Retry-After + no X-RateLimit headers: ambiguous —
        record for diagnostics, never suppress REST."""
        exc = FakeHTTPException(429, "", {"Retry-After": "10", "CF-RAY": "xyz-SIN"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.snapshot()["classification"], "cf_unclassified")
        self.assertEqual(cb.snapshot()["body_kind"], "empty")

    def test_login_slot_released_on_connect(self):
        cb.begin_login()
        self.assertTrue(cb.snapshot()["login_in_flight"])
        cb.report_connected()
        self.assertFalse(cb.snapshot()["login_in_flight"])

    def test_report_connected_does_not_override_ban(self):
        cb.report_ban(600)
        cb.report_connected()
        self.assertTrue(cb.is_banned())

    def test_start_probe_idempotent(self):
        async def run():
            cb.start_probe("test-token")
            first = cb._probe_task
            cb.start_probe("test-token")  # second call must not duplicate
            self.assertIs(cb._probe_task, first)
            if first is not None and not first.done():
                first.cancel()
                try:
                    await first
                except (asyncio.CancelledError, Exception):
                    pass
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
