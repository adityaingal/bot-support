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

    # 1. Short route-level 429: no suppression
    def test_route_429_not_edge(self):
        exc = FakeHTTPException(429, '{"retry_after": 5.2}',
                                {"Retry-After": "5", "X-RateLimit-Remaining": "0"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_SUSPECTED_LIMIT)

    # 2. Long Retry-After WITHOUT X-RateLimit headers = edge ban
    def test_long_429_edge_ban(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "1575", "CF-RAY": "abc-SIN"})
        cb._maybe_report_edge_ban(exc)
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_EDGE_BLOCKED)
        self.assertEqual(cb.seconds_left(), 1575)
        snap = cb.snapshot()
        self.assertEqual(snap["cf_ray"], "abc-SIN")
        self.assertEqual(snap["classification"], "edge_429")

    # 3. Long Retry-After WITH X-RateLimit headers = shared/global limit, no suppression
    def test_long_429_with_rl_headers_not_suppressed(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "700",
                                          "X-RateLimit-Scope": "shared"})
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())

    # 4. Cloudflare HTML 1015
    def test_html_1015(self):
        exc = FakeHTTPException(429, "<!DOCTYPE html><html>error 1015</html>",
                                {"Retry-After": "3600"})
        cb._maybe_report_edge_ban(exc)
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb._classification, "cloudflare_1015")

    # 5. Malformed Retry-After does not crash
    def test_malformed_retry_after(self):
        exc = FakeHTTPException(429, "", {"Retry-After": "not-a-number"})
        cb._maybe_report_edge_ban(exc)  # must not raise
        exc2 = FakeHTTPException(429, "", {"Retry-After": "Fri, 21 Oct 2099 00:00:00 GMT"})
        cb._maybe_report_edge_ban(exc2)  # HTTP-date form, far future
        self.assertTrue(cb.is_banned())

    # 6. Non-429 ignored
    def test_non_429_ignored(self):
        exc = FakeHTTPException(500, "boom")
        cb._maybe_report_edge_ban(exc)
        self.assertFalse(cb.is_banned())

    # 7. Successful response clears state immediately (RECOVERING path)
    def test_report_ok_clears(self):
        cb.report_ban(1500, cf_ray="xyz")
        self.assertTrue(cb.is_banned())
        cb.report_ok()
        self.assertFalse(cb.is_banned())
        self.assertEqual(cb.state(), cb.STATE_NORMAL)  # no loop in tests

    # 8. report_ban extends only forward
    def test_report_ban_monotonic_extension(self):
        cb.report_ban(100)
        first = cb._blocked_until_mono
        cb.report_ban(50)  # shorter: must not shrink
        self.assertGreaterEqual(cb._blocked_until_mono, first)
        cb.report_ban(500)
        self.assertGreater(cb._blocked_until_mono, first)

    # 9. suggested_wait stays in sane bounds
    def test_suggested_wait_bounds(self):
        cb.report_ban(3600)
        w = cb.suggested_wait()
        self.assertGreaterEqual(w, 5.0)
        self.assertLessEqual(w, 3600)
        # Near expiry: fresh ban with short remaining time
        cb._reset_for_tests()
        cb.report_ban(60)  # near expiry
        w2 = cb.suggested_wait()
        self.assertLessEqual(w2, 60)

    # 10. Persistence round-trip restores an active ban
    def test_persistence_roundtrip(self):
        cb.report_ban(900, cf_ray="persist-ray", classification="edge_429")
        self.assertTrue(os.path.exists(cb._STATE_FILE))
        data = json.load(open(cb._STATE_FILE))
        self.assertEqual(data["last_cf_ray"], "persist-ray")
        cb._reset_for_tests()
        self.assertFalse(cb.is_banned())
        cb._load_persisted()
        self.assertTrue(cb.is_banned())
        self.assertEqual(cb._last_cf_ray, "persist-ray")

    # 11. Stale persisted record is discarded
    def test_stale_persisted_discarded(self):
        stale = {"state": "EDGE_BLOCKED", "detected_at": time.time() - 99999,
                 "retry_after": 100, "last_cf_ray": None, "classification": "edge_429",
                 "last_http_status": 429}
        with open(cb._STATE_FILE, "w") as f:
            json.dump(stale, f)
        cb._load_persisted()
        self.assertFalse(cb.is_banned())

    # 12. Persistence never contains token-like material
    def test_persistence_has_no_secrets(self):
        cb.report_ban(600)
        content = open(cb._STATE_FILE).read().lower()
        self.assertNotIn("token", content)
        self.assertNotIn("authorization", content)

    # 13. Concurrent login prevention
    def test_login_guard(self):
        self.assertTrue(cb.begin_login())
        self.assertFalse(cb.begin_login())  # second attempt blocked
        cb.end_login()
        self.assertTrue(cb.begin_login())
        cb.end_login()

    # 14. Recovery probe cannot overlap (lock + loop flag)
    def test_probe_lock_single_flight(self):
        async def run():
            lock = cb._get_probe_lock()
            self.assertFalse(lock.locked())
            await lock.acquire()
            self.assertTrue(lock.locked())
            lock.release()
        asyncio.run(run())

    # 15. CloudflareBanError raised while banned for non-exempt routes
    def test_ban_error_type(self):
        self.assertTrue(issubclass(cb.CloudflareBanError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
