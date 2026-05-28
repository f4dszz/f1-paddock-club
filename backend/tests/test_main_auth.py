"""Integration tests for /api/calendar auth behavior using TestClient."""
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
    """Set env vars and reload `main` so module-level constants pick them up."""
    for k in ("APP_ENV", "REQUIRE_CLERK_AUTH", "DEMO_ACCESS_TOKEN",
              "CLERK_JWT_ISSUER", "CLERK_JWKS_URL"):
        os.environ.pop(k, None)
    os.environ.update(env)
    for mod in ("main", "auth"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
        else:
            importlib.import_module(mod)
    return sys.modules["main"]


class CalendarAuthTests(unittest.TestCase):
    def test_dev_no_auth_configured_calendar_is_open(self):
        from fastapi.testclient import TestClient
        main_mod = _reload_main_with_env(APP_ENV="test")
        client = TestClient(main_mod.app)
        r = client.get("/api/calendar")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_dev_with_demo_token_requires_match(self):
        from fastapi.testclient import TestClient
        main_mod = _reload_main_with_env(APP_ENV="test", DEMO_ACCESS_TOKEN="abc123")
        client = TestClient(main_mod.app)
        self.assertEqual(client.get("/api/calendar").status_code, 401)
        ok = client.get("/api/calendar", headers={"Authorization": "Bearer abc123"})
        self.assertEqual(ok.status_code, 200)
        bad = client.get("/api/calendar", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(bad.status_code, 401)

    def test_prod_no_clerk_returns_503(self):
        from fastapi.testclient import TestClient
        main_mod = _reload_main_with_env(APP_ENV="production")
        client = TestClient(main_mod.app)
        r = client.get("/api/calendar")
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()
