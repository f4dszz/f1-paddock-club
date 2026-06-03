"""test-coverage-13: infra-module smoke tests.

Lower-risk config/wiring modules that had no DIRECT test and could regress
silently. The wave-1 hardening suite already covers llm.py's timeout/retry/
daily-quota and observability.py's Sentry scrubber, so this file deliberately
fills the REMAINING gaps:

  llm.py            get_llm() returns None with no key / unknown provider (the
                    mock-fallback path the agents depend on); provider_label().
  logging_config.py setup_logging() returns a Path and is idempotent — without
                    permanently polluting the real root logger / logs dir.
  agents/_shared.py _direct_only_requested, _requested_hotel_brands, _msg
                    shape, parse_input first-node defaults.

No network, no real LLM, no Sentry. setup_logging is exercised against a temp
dir with full save/restore of module + root-logger state so it neither races
other test files nor leaves a stray handler behind.
"""
from __future__ import annotations

import importlib
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class GetLlmFallbackTests(unittest.TestCase):
    """get_llm must degrade to None (-> agents use mock) when unusable."""

    def setUp(self):
        self.llm = importlib.import_module("llm")

    def test_openai_no_key_returns_none(self):
        with patch.object(self.llm, "PROVIDER", "openai"), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OPENAI_API_KEY", None)
            self.assertIsNone(self.llm.get_llm())

    def test_anthropic_no_key_returns_none(self):
        with patch.object(self.llm, "PROVIDER", "anthropic"), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertIsNone(self.llm.get_llm())

    def test_unknown_provider_returns_none(self):
        with patch.object(self.llm, "PROVIDER", "nope-llm"):
            self.assertIsNone(self.llm.get_llm())

    def test_provider_label_known_and_unknown(self):
        with patch.object(self.llm, "PROVIDER", "openai"):
            self.assertEqual(self.llm.provider_label(), "OpenAI")
        with patch.object(self.llm, "PROVIDER", "anthropic"):
            self.assertEqual(self.llm.provider_label(), "Anthropic")
        with patch.object(self.llm, "PROVIDER", "weird"):
            # Falls back to the raw provider string, never raises.
            self.assertEqual(self.llm.provider_label(), "weird")


class SetupLoggingTests(unittest.TestCase):
    """setup_logging returns a path and is idempotent — exercised in isolation."""

    def setUp(self):
        self.lc = importlib.import_module("logging_config")
        # Snapshot module + root-logger state so the real config is untouched.
        self._saved_configured = self.lc._configured
        self._saved_active = self.lc._active_log_file
        self._saved_log_dir = self.lc._LOG_DIR
        self._root = logging.getLogger()
        self._saved_handlers = list(self._root.handlers)
        self._saved_level = self._root.level
        self._tmp = tempfile.TemporaryDirectory()
        # Force a clean, isolated run into a throwaway dir.
        self.lc._configured = False
        self.lc._active_log_file = None
        self.lc._LOG_DIR = Path(self._tmp.name) / "logs"

    def tearDown(self):
        # Remove any handler we added before restoring, then restore state.
        for h in list(self._root.handlers):
            if h not in self._saved_handlers:
                self._root.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        self._root.handlers[:] = self._saved_handlers
        self._root.setLevel(self._saved_level)
        self.lc._configured = self._saved_configured
        self.lc._active_log_file = self._saved_active
        self.lc._LOG_DIR = self._saved_log_dir
        self._tmp.cleanup()

    def test_returns_existing_log_path(self):
        path = self.lc.setup_logging()
        self.assertIsInstance(path, Path)
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, self.lc._LOG_DIR)

    def test_idempotent_same_path_no_duplicate_handler(self):
        before = len(self._root.handlers)
        first = self.lc.setup_logging()
        after_first = len(self._root.handlers)
        second = self.lc.setup_logging()
        after_second = len(self._root.handlers)
        self.assertEqual(first, second)
        # Exactly one file handler added; the repeat call adds nothing.
        self.assertEqual(after_first, before + 1)
        self.assertEqual(after_second, after_first)

    def test_log_level_env_honored(self):
        with patch.dict("os.environ", {"LOG_LEVEL": "WARNING"}):
            self.lc.setup_logging()
        self.assertEqual(self._root.level, logging.WARNING)


class SharedHelperTests(unittest.TestCase):
    def setUp(self):
        self.shared = importlib.import_module("agents._shared")

    def test_direct_only_requested(self):
        # Matches the real regex phrasings: "direct only", "non-stop",
        # "no stops", and the Chinese 直飞 variant.
        self.assertTrue(self.shared._direct_only_requested("please book direct only"))
        self.assertTrue(self.shared._direct_only_requested("nonstop please"))
        self.assertTrue(self.shared._direct_only_requested("no stops if possible"))
        self.assertTrue(self.shared._direct_only_requested("我要直飞"))
        # "direct flights" alone (no only/non-stop qualifier) is NOT a match.
        self.assertFalse(self.shared._direct_only_requested("direct flights are nice"))
        self.assertFalse(self.shared._direct_only_requested("anything is fine"))
        self.assertFalse(self.shared._direct_only_requested(""))
        self.assertFalse(self.shared._direct_only_requested(None))

    def test_requested_hotel_brands_matches_known_only(self):
        brands = self.shared._requested_hotel_brands("I want a Hilton or Marriott")
        self.assertIn("hilton", [b.lower() for b in brands])
        self.assertIn("marriott", [b.lower() for b in brands])
        # No known brand -> empty list, not an error.
        self.assertEqual(self.shared._requested_hotel_brands("a cheap hostel"), [])
        self.assertEqual(self.shared._requested_hotel_brands(None), [])

    def test_msg_shape(self):
        m = self.shared._msg("concierge", "hello")
        self.assertEqual(m["agent"], "concierge")
        self.assertEqual(m["text"], "hello")
        self.assertEqual(m["type"], "status")

    def test_parse_input_seeds_defaults(self):
        state = {"gp_name": "Italian GP", "origin": "New York"}
        out = self.shared.parse_input(state)
        self.assertFalse(out["budget_ok"])
        self.assertEqual(out["retry_count"], 0)
        self.assertEqual(len(out["messages"]), 1)
        # The status message echoes the GP + origin so the user sees progress.
        text = out["messages"][0]["text"]
        self.assertIn("Italian GP", text)
        self.assertIn("New York", text)


if __name__ == "__main__":
    unittest.main()
