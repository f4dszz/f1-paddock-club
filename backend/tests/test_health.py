"""Health and readiness endpoint tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("APP_ENV", "test")


class HealthTests(unittest.TestCase):
    def _client(self):
        # Lazy import so a clean env applies to module-level constants.
        from fastapi.testclient import TestClient
        import main as main_mod
        return TestClient(main_mod.app)

    def test_healthz_returns_200_ok(self):
        r = self._client().get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_readyz_ok_when_db_reachable(self):
        r = self._client().get("/readyz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["db"], "ok")

    def test_response_carries_request_id_header(self):
        r = self._client().get("/healthz")
        self.assertIn("x-request-id", {k.lower() for k in r.headers.keys()})

    def test_response_echoes_request_id_when_supplied(self):
        r = self._client().get("/healthz", headers={"x-request-id": "abc-123"})
        # Match case-insensitively because httpx normalizes header keys.
        rid = r.headers.get("x-request-id") or r.headers.get("X-Request-Id")
        self.assertEqual(rid, "abc-123")


if __name__ == "__main__":
    unittest.main()
