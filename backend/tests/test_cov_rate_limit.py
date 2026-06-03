"""test-coverage-2: IPRateLimiter / HTTP 429 / WS 1008 / _trusted_forwarded_ip.

This abuse-control surface had zero regression guard. Covers:
- IPRateLimiter allow-then-deny, window eviction, max<=0 disabled
- /api/calendar 429 via TestClient (HTTP limiter dep; /plan requires a full
  plan run so we exercise the same Depends(_http_rate_limit_dep) on the
  cheaper authenticated GET route)
- WS 1008 close on connect flood
- _trusted_forwarded_ip rightmost-hop selection (CURRENT behavior, read from
  source: default _TRUSTED_PROXY_HOPS=1)
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _reload_main_with_env(**env: str):
    for k in (
        "APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN", "CLERK_JWT_ISSUER",
        "CLERK_JWKS_URL", "TEST_DATABASE_URL", "HTTP_RATE_LIMIT_PER_MINUTE",
        "WS_CONNECT_LIMIT_PER_MINUTE", "TRUSTED_PROXY_HOPS", "ALLOWED_ORIGINS",
    ):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("auth", "db", "models", "repository", "main"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    return sys.modules["main"]


class IPRateLimiterUnitTests(unittest.TestCase):
    def setUp(self):
        self.main = _reload_main_with_env(APP_ENV="test")

    def test_allow_up_to_n_then_deny(self):
        limiter = self.main.IPRateLimiter(max_per_window=3, window_seconds=60)
        self.assertTrue(limiter.allow("1.1.1.1"))
        self.assertTrue(limiter.allow("1.1.1.1"))
        self.assertTrue(limiter.allow("1.1.1.1"))
        self.assertFalse(limiter.allow("1.1.1.1"))  # 4th over the cap

    def test_separate_buckets_per_ip(self):
        limiter = self.main.IPRateLimiter(max_per_window=1, window_seconds=60)
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        # Different IP has its own fresh bucket.
        self.assertTrue(limiter.allow("b"))

    def test_window_eviction_restores_capacity(self):
        import time as _time

        limiter = self.main.IPRateLimiter(max_per_window=2, window_seconds=60)
        # Pre-load two events that are already outside the window.
        old = _time.monotonic() - 120
        limiter._events["x"].append(old)
        limiter._events["x"].append(old)
        # Both stale events get evicted on the next allow() -> capacity restored.
        self.assertTrue(limiter.allow("x"))
        self.assertTrue(limiter.allow("x"))
        self.assertFalse(limiter.allow("x"))

    def test_max_zero_disables_limiter(self):
        limiter = self.main.IPRateLimiter(max_per_window=0, window_seconds=60)
        for _ in range(100):
            self.assertTrue(limiter.allow("anyone"))

    def test_negative_max_disables_limiter(self):
        limiter = self.main.IPRateLimiter(max_per_window=-1, window_seconds=60)
        for _ in range(50):
            self.assertTrue(limiter.allow("anyone"))


class TrustedForwardedIpTests(unittest.TestCase):
    def setUp(self):
        # Default hops = 1 (rightmost entry is the real client).
        self.main = _reload_main_with_env(APP_ENV="test")

    def test_single_hop_picks_rightmost(self):
        ip = self.main._trusted_forwarded_ip("203.0.113.9, 70.41.3.18, 150.172.238.178")
        self.assertEqual(ip, "150.172.238.178")

    def test_empty_returns_none(self):
        self.assertIsNone(self.main._trusted_forwarded_ip(""))
        self.assertIsNone(self.main._trusted_forwarded_ip("   "))

    def test_single_entry(self):
        self.assertEqual(self.main._trusted_forwarded_ip("8.8.8.8"), "8.8.8.8")

    def test_two_hops_picks_second_from_right(self):
        m = _reload_main_with_env(APP_ENV="test", TRUSTED_PROXY_HOPS="2")
        ip = m._trusted_forwarded_ip("client, proxyA, proxyB")
        self.assertEqual(ip, "proxyA")

    def test_zero_hops_ignores_xff(self):
        m = _reload_main_with_env(APP_ENV="test", TRUSTED_PROXY_HOPS="0")
        self.assertIsNone(m._trusted_forwarded_ip("1.2.3.4, 5.6.7.8"))

    def test_short_chain_falls_back_to_leftmost(self):
        m = _reload_main_with_env(APP_ENV="test", TRUSTED_PROXY_HOPS="3")
        # Only one entry but 3 declared hops -> index clamped to leftmost.
        self.assertEqual(m._trusted_forwarded_ip("only.one"), "only.one")


class HttpRateLimit429Tests(unittest.TestCase):
    def setUp(self):
        # Cap HTTP to 2/min so the 3rd request is throttled.
        self.main = _reload_main_with_env(APP_ENV="test", HTTP_RATE_LIMIT_PER_MINUTE="2")

    def test_calendar_route_returns_429_after_cap(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client:
            r1 = client.get("/api/calendar")
            r2 = client.get("/api/calendar")
            r3 = client.get("/api/calendar")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
        self.assertEqual(r3.json()["detail"], "Too many requests")


class WsConnectFloodTests(unittest.TestCase):
    def setUp(self):
        # Cap WS connect rate to 1/min so the 2nd connect is closed 1008.
        self.main = _reload_main_with_env(APP_ENV="test", WS_CONNECT_LIMIT_PER_MINUTE="1")

    def test_second_connect_closed_1008(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        with TestClient(self.main.app) as client:
            with client.websocket_connect("/ws"):
                pass  # first connection consumes the single allowed slot
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect("/ws") as ws2:
                    ws2.receive_json()
            self.assertEqual(ctx.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
