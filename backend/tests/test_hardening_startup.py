"""Hardening tests: startup fail-fast on misconfigured production (deploy-cicd-8).

In a non-local environment with Clerk auth enforced, a missing CLERK_JWT_ISSUER
must raise at startup (so the platform healthcheck reflects a dead app instead
of reporting green and 503ing every authenticated request). A missing
CLERK_AUDIENCE in production is a WARNING, not a crash (per GLOBAL DECISIONS),
and a missing LLM key is a WARNING (mock is a valid degradation path). Local/dev
is exempt entirely.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


class StartupConfigCheckTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in (
                "APP_ENV", "REQUIRE_CLERK_AUTH", "CLERK_JWT_ISSUER",
                "CLERK_JWKS_URL", "CLERK_AUDIENCE",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            )
        }
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_local_env_is_exempt(self):
        # Local: even with nothing configured, startup checks must not raise.
        with mock.patch.object(main, "_IS_LOCAL_ENV", True):
            main._startup_config_checks()  # no exception

    def test_prod_clerk_enforced_missing_issuer_fails_fast(self):
        os.environ["APP_ENV"] = "production"  # _require_clerk() -> True
        with mock.patch.object(main, "_IS_LOCAL_ENV", False):
            with self.assertRaises(RuntimeError) as ctx:
                main._startup_config_checks()
        self.assertIn("CLERK_JWT_ISSUER", str(ctx.exception))

    def test_prod_clerk_enforced_with_issuer_passes(self):
        os.environ["APP_ENV"] = "production"
        os.environ["CLERK_JWT_ISSUER"] = "https://acme.clerk.example"
        os.environ["CLERK_AUDIENCE"] = "my-api"
        os.environ["OPENAI_API_KEY"] = "sk-test"  # avoid the mock-LLM warning path
        with mock.patch.object(main, "_IS_LOCAL_ENV", False):
            main._startup_config_checks()  # no exception

    def test_prod_missing_audience_is_warning_not_crash(self):
        os.environ["APP_ENV"] = "production"
        os.environ["CLERK_JWT_ISSUER"] = "https://acme.clerk.example"
        os.environ["OPENAI_API_KEY"] = "sk-test"
        # CLERK_AUDIENCE intentionally unset.
        with mock.patch.object(main, "_IS_LOCAL_ENV", False):
            with self.assertLogs("main", level="WARNING") as logs:
                main._startup_config_checks()
        self.assertTrue(any("CLERK_AUDIENCE" in m for m in logs.output))

    def test_prod_missing_llm_key_warns_does_not_crash(self):
        # Clerk not enforced (REQUIRE_CLERK_AUTH unset, not prod-by-name) but a
        # non-local env with no provider key must warn about mock LLM.
        os.environ["APP_ENV"] = "staging"  # non-local, _require_clerk() False
        # No OPENAI_API_KEY -> warning expected for the default openai provider.
        with mock.patch.object(main, "_IS_LOCAL_ENV", False):
            with mock.patch("llm.PROVIDER", "openai"):
                with self.assertLogs("main", level="WARNING") as logs:
                    main._startup_config_checks()  # no exception
        self.assertTrue(any("MOCK" in m for m in logs.output))


if __name__ == "__main__":
    unittest.main()
