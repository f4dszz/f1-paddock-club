"""Hardening tests: LLM client timeout/retry, refine hard deadline, and the
per-identity daily LLM call ceiling.

Covers findings:
- backend-completeness-2: ChatOpenAI/ChatAnthropic carry timeout + max_retries;
  refine.supervisor.invoke runs under a hard wall-clock deadline.
- BS-15: per-identity daily LLM call ceiling (LLM_DAILY_CALL_LIMIT).

These tests never touch the network: the provider client classes are patched
to capture their constructor kwargs, and the deadline helper is driven with a
fake blocking callable.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import llm  # noqa: E402
import refine  # noqa: E402


class _FakeChatClient:
    """Stand-in for ChatOpenAI/ChatAnthropic that records its kwargs."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


class LLMTimeoutRetryTests(unittest.TestCase):
    """backend-completeness-2: clients must be built with timeout + max_retries."""

    def setUp(self):
        # Ensure a key is present so _get_* does not short-circuit to None.
        self._saved = {k: os.environ.get(k) for k in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "LLM_REQUEST_TIMEOUT_SECONDS", "LLM_MAX_RETRIES",
        )}
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        _FakeChatClient.last_kwargs = {}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_openai_client_has_timeout_and_retries(self):
        with mock.patch("langchain_openai.ChatOpenAI", _FakeChatClient):
            client = llm._get_openai(temperature=0.5, max_tokens=512)
        self.assertIsNotNone(client)
        self.assertIn("timeout", _FakeChatClient.last_kwargs)
        self.assertIn("max_retries", _FakeChatClient.last_kwargs)
        self.assertGreaterEqual(_FakeChatClient.last_kwargs["timeout"], 1.0)
        self.assertGreaterEqual(_FakeChatClient.last_kwargs["max_retries"], 0)

    def test_anthropic_client_has_timeout_and_retries(self):
        with mock.patch("langchain_anthropic.ChatAnthropic", _FakeChatClient):
            client = llm._get_anthropic(temperature=0.5, max_tokens=512)
        self.assertIsNotNone(client)
        self.assertIn("timeout", _FakeChatClient.last_kwargs)
        self.assertIn("max_retries", _FakeChatClient.last_kwargs)

    def test_timeout_is_env_configurable(self):
        os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = "42"
        os.environ["LLM_MAX_RETRIES"] = "5"
        with mock.patch("langchain_openai.ChatOpenAI", _FakeChatClient):
            llm._get_openai(temperature=0.5, max_tokens=512)
        self.assertEqual(_FakeChatClient.last_kwargs["timeout"], 42.0)
        self.assertEqual(_FakeChatClient.last_kwargs["max_retries"], 5)

    def test_timeout_garbage_env_falls_back_to_default(self):
        os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = "not-a-number"
        self.assertEqual(llm._llm_timeout_seconds(), 60.0)

    def test_timeout_has_minimum_floor(self):
        os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = "0"
        self.assertGreaterEqual(llm._llm_timeout_seconds(), 1.0)


class RefineDeadlineTests(unittest.TestCase):
    """backend-completeness-2: supervisor.invoke runs under a hard deadline."""

    def test_fast_callable_returns_result(self):
        out = refine._run_with_deadline(lambda: 7, deadline=5.0)
        self.assertEqual(out, 7)

    def test_slow_callable_raises_deadline_error(self):
        def slow():
            time.sleep(2.0)
            return "never"

        with self.assertRaises(refine.RefineDeadlineError):
            refine._run_with_deadline(slow, deadline=0.2)

    def test_zero_deadline_disables_guard(self):
        # deadline<=0 runs inline (used by tests / explicit opt-out).
        out = refine._run_with_deadline(lambda: "inline", deadline=0)
        self.assertEqual(out, "inline")

    def test_deadline_propagates_callable_exception(self):
        def boom():
            raise ValueError("kaboom")

        with self.assertRaises(ValueError):
            refine._run_with_deadline(boom, deadline=5.0)

    def test_deadline_seconds_env_configurable(self):
        with mock.patch.dict(os.environ, {"REFINE_DEADLINE_SECONDS": "30"}):
            self.assertEqual(refine._refine_deadline_seconds(), 30.0)

    def test_deadline_seconds_garbage_falls_back(self):
        with mock.patch.dict(os.environ, {"REFINE_DEADLINE_SECONDS": "x"}):
            self.assertEqual(refine._refine_deadline_seconds(), 120.0)


class LLMDailyQuotaTests(unittest.TestCase):
    """BS-15: per-identity daily LLM call ceiling."""

    def setUp(self):
        llm.reset_llm_quota_for_tests()
        self._saved = os.environ.get("LLM_DAILY_CALL_LIMIT")

    def tearDown(self):
        llm.reset_llm_quota_for_tests()
        if self._saved is None:
            os.environ.pop("LLM_DAILY_CALL_LIMIT", None)
        else:
            os.environ["LLM_DAILY_CALL_LIMIT"] = self._saved

    def test_under_limit_allows(self):
        os.environ["LLM_DAILY_CALL_LIMIT"] = "3"
        # 3 calls allowed, 4th rejected.
        llm.check_llm_quota("user-a")
        llm.check_llm_quota("user-a")
        llm.check_llm_quota("user-a")
        with self.assertRaises(llm.LLMDailyLimitError):
            llm.check_llm_quota("user-a")

    def test_limit_is_per_identity(self):
        os.environ["LLM_DAILY_CALL_LIMIT"] = "1"
        llm.check_llm_quota("user-a")
        with self.assertRaises(llm.LLMDailyLimitError):
            llm.check_llm_quota("user-a")
        # A different identity has its own bucket.
        llm.check_llm_quota("user-b")

    def test_zero_disables_guard(self):
        os.environ["LLM_DAILY_CALL_LIMIT"] = "0"
        for _ in range(50):
            llm.check_llm_quota("user-a")  # never raises

    def test_none_identity_collapses_to_anonymous(self):
        os.environ["LLM_DAILY_CALL_LIMIT"] = "1"
        llm.check_llm_quota(None)
        with self.assertRaises(llm.LLMDailyLimitError):
            llm.check_llm_quota("")  # same anonymous bucket

    def test_counter_is_threadsafe(self):
        os.environ["LLM_DAILY_CALL_LIMIT"] = "100"
        errors = []

        def worker():
            try:
                for _ in range(10):
                    llm.check_llm_quota("shared")
            except llm.LLMDailyLimitError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        # 10 threads * 10 calls = 100 == exactly the limit; the 101st rejects.
        with self.assertRaises(llm.LLMDailyLimitError):
            llm.check_llm_quota("shared")


if __name__ == "__main__":
    unittest.main()
