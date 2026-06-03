"""test-coverage-5: POST /plan route + ServerBusyError/503 semaphore concurrency.

The HTTP /plan route had no test: the 400-on-invalid path, the happy
200-snapshot path (through the auth + rate-limit Depends stack), and the
503-on-ServerBusyError mapping were all uncovered, as was the semaphore
acquire-timeout logic in _run_plan_with_limit (the only ServerBusyError raise).

We reload main under APP_ENV=test (local auth -> demo-user) so TestClient can
exercise the real dependency stack, and:
  - invalid currency -> 400
  - happy path -> 200 with the expected snapshot shape (plan run is stubbed
    so no LLM/network/DAG executes)
  - _run_plan_with_limit raising ServerBusyError -> 503
  - a direct test of _run_plan_with_limit forcing the semaphore acquire-timeout.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _reload_main(**env: str):
    for k in (
        "APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN", "CLERK_JWT_ISSUER",
        "CLERK_JWKS_URL", "TEST_DATABASE_URL", "HTTP_RATE_LIMIT_PER_MINUTE",
        "MAX_CONCURRENT_PLANS", "PLAN_ACQUIRE_TIMEOUT_SECONDS",
    ):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("auth", "db", "models", "repository", "main"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    return sys.modules["main"]


_STUB_RESULT = {
    "tickets": [{"tag": "PICK", "name": "GA", "price": 100.0}],
    "transport": [{"tag": "ROUNDTRIP", "summary": "RT", "price": 200.0}],
    "hotel": [{"tag": "HOTEL", "name": "Inn", "price_per_night": 50.0}],
    "itinerary": ["Day 1"],
    "tour": ["Tour A"],
    "budget_summary": {
        "total": 350.0, "budget": 5000.0, "within_budget": True,
        "currency": "EUR", "quote_complete": True,
    },
    "active_constraints": {},
    "messages": [{"agent": "concierge", "text": "done"}],
}

_VALID_BODY = {
    "gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "2026-09-06",
    "origin": "New York", "budget": 5000, "currency": "EUR", "extra_days": 0,
}


class PlanRouteTests(unittest.TestCase):
    def setUp(self):
        self.main = _reload_main(APP_ENV="test")

    def test_invalid_currency_returns_400(self):
        from fastapi.testclient import TestClient

        with TestClient(self.main.app) as client:
            r = client.post("/plan", json={**_VALID_BODY, "currency": "JPY"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported currency", r.json()["detail"])

    def test_happy_path_returns_200_snapshot_shape(self):
        from fastapi.testclient import TestClient

        async def fake_run(payload):
            return _STUB_RESULT

        with patch.object(self.main, "_run_plan_with_limit", side_effect=fake_run):
            with TestClient(self.main.app) as client:
                r = client.post("/plan", json=_VALID_BODY)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Snapshot shape: the documented serializable keys are all present.
        for key in (
            "tickets", "transport", "hotel", "itinerary", "tour",
            "budget_summary", "active_constraints", "messages",
        ):
            self.assertIn(key, body)
        self.assertEqual(body["tour"], ["Tour A"])
        self.assertEqual(body["budget_summary"]["currency"], "EUR")
        self.assertEqual(body["messages"], _STUB_RESULT["messages"])

    def test_server_busy_maps_to_503(self):
        from fastapi.testclient import TestClient

        async def busy(payload):
            raise self.main.ServerBusyError("Server is busy. Please try again shortly.")

        with patch.object(self.main, "_run_plan_with_limit", side_effect=busy):
            with TestClient(self.main.app) as client:
                r = client.post("/plan", json=_VALID_BODY)
        self.assertEqual(r.status_code, 503)
        self.assertIn("busy", r.json()["detail"].lower())


class RunPlanWithLimitSemaphoreTests(unittest.TestCase):
    """Directly exercise the acquire-timeout that raises ServerBusyError."""

    def setUp(self):
        # 1 concurrent plan slot, and a sub-second acquire timeout so the test
        # is fast. PLAN_ACQUIRE_TIMEOUT_SECONDS has minimum=1, so we instead
        # patch the module constant directly after reload.
        self.main = _reload_main(APP_ENV="test", MAX_CONCURRENT_PLANS="1")

    def test_acquire_timeout_raises_server_busy(self):
        async def scenario():
            # Hold the only slot, then attempt another acquire under a tiny
            # timeout so the second one cannot get in -> ServerBusyError.
            await self.main._plan_semaphore.acquire()
            try:
                with patch.object(self.main, "_PLAN_ACQUIRE_TIMEOUT_SECONDS", 0.05):
                    with self.assertRaises(self.main.ServerBusyError):
                        await self.main._run_plan_with_limit(_VALID_BODY)
            finally:
                self.main._plan_semaphore.release()

        asyncio.run(scenario())

    def test_releases_slot_after_run(self):
        async def scenario():
            with patch.object(self.main, "plan_trip", lambda payload: _STUB_RESULT):
                out = await self.main._run_plan_with_limit(_VALID_BODY)
            self.assertEqual(out["tour"], ["Tour A"])
            # The single slot was released, so it is acquirable again.
            self.assertTrue(self.main._plan_semaphore._value >= 1)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
