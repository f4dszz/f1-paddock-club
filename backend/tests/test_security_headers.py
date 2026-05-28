"""Security header middleware tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _lower_keys(headers):
    return {k.lower() for k in headers.keys()}


class SecurityHeadersTests(unittest.TestCase):
    def _client(self):
        from fastapi.testclient import TestClient
        import main as main_mod
        return TestClient(main_mod.app)

    def setUp(self):
        # Restore APP_ENV after each test.
        self._original_app_env = os.environ.get("APP_ENV", "test")

    def tearDown(self):
        if self._original_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = self._original_app_env

    def test_dev_has_baseline_headers_no_hsts(self):
        os.environ["APP_ENV"] = "test"
        r = self._client().get("/healthz")
        keys = _lower_keys(r.headers)
        self.assertIn("x-content-type-options", keys)
        self.assertIn("referrer-policy", keys)
        self.assertIn("permissions-policy", keys)
        self.assertNotIn("strict-transport-security", keys)
        self.assertNotIn("content-security-policy", keys)

    def test_prod_has_hsts_and_csp(self):
        os.environ["APP_ENV"] = "production"
        r = self._client().get("/healthz")
        keys = _lower_keys(r.headers)
        self.assertIn("strict-transport-security", keys)
        self.assertIn("content-security-policy", keys)
        csp = r.headers.get("content-security-policy") or r.headers.get("Content-Security-Policy")
        self.assertIn("clerk", csp)
        self.assertIn("sentry", csp)


if __name__ == "__main__":
    unittest.main()
