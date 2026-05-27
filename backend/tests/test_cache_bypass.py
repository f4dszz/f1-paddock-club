"""Prove the @cached decorator does not read/write disk when APP_ENV=test.

Reviewer R9 non-negotiable: the deterministic E2E lane must not be
polluted by stale developer cache. The disk cache wrapper now
short-circuits under APP_ENV=test — no JSON load, no JSON save, every
call hits the underlying function.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class CacheBypassTests(unittest.TestCase):
    def setUp(self):
        # Reload so the module picks up our patched os.environ each test.
        if "tools._cache" in sys.modules:
            del sys.modules["tools._cache"]

    def _load_cached(self):
        from tools._cache import cached, _load, _save  # noqa: F401
        return cached

    def test_test_env_bypasses_read_and_write(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "test"}, clear=False):
            cached = self._load_cached()
            from tools import _cache

            calls = {"n": 0}

            @cached(ttl=3600)
            def double(x):
                calls["n"] += 1
                return x * 2

            with mock.patch.object(_cache, "_load") as load_mock, \
                 mock.patch.object(_cache, "_save") as save_mock:
                self.assertEqual(double(2), 4)
                self.assertEqual(double(2), 4)  # repeat — would normally hit cache
                self.assertEqual(double(3), 6)

                load_mock.assert_not_called()
                save_mock.assert_not_called()

            # Underlying function executed every call — three real invocations.
            self.assertEqual(calls["n"], 3)

    def test_non_test_env_still_caches(self):
        # Sanity: with APP_ENV unset, the cache must still work normally.
        env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
        with mock.patch.dict(os.environ, env, clear=True):
            cached = self._load_cached()

            calls = {"n": 0}

            @cached(ttl=3600)
            def triple(x):
                calls["n"] += 1
                return x * 3

            self.assertEqual(triple(2), 6)
            self.assertEqual(triple(2), 6)  # cache HIT — no second call

            self.assertEqual(calls["n"], 1)

            # Cleanup cache file the test just wrote.
            from tools._cache import CACHE_DIR
            cache_file = CACHE_DIR / "triple.json"
            if cache_file.exists():
                cache_file.unlink()


if __name__ == "__main__":
    unittest.main()
