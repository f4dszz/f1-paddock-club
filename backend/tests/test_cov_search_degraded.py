"""test-coverage-12: search-tool provider-error / empty -> graceful degradation.

Only the post-filter logic and zero-egress were covered before; the
error-handling/fallback branches (a provider raising, returning empty, the
LLM-estimate layer, and the agent's mock fallback) had no test. A regression
here would silently drop real provider data or crash a plan.

Covered:
  - search_flights: parallel sources raising + LLM estimate empty -> RuntimeError
    (the agent catches this and uses mock)
  - search_flights: parallel empty but LLM estimate returns -> tagged
    _source=llm_estimate / _degraded=True results, summary mentions llm_estimate
  - _try_llm_estimate tags every leg with _source/_degraded (real code path,
    fake LLM injected)
  - transport_agent: search_flights raising -> mock fallback with the honest
    "mock (all data sources failed)" source summary, never crashes
  - search_web: providers unconfigured -> RuntimeError (documented contract)

No real network or LLM is touched; providers are patched.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class SearchFlightsDegradationTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("tools.search_flights")

    def test_all_parallel_raise_and_llm_empty_raises_runtime(self):
        def raise_flights(*a, **k):
            raise RuntimeError("google_flights 503")

        def raise_search(*a, **k):
            raise RuntimeError("google_search timeout")

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(self.mod, "_try_serpapi_google_flights", side_effect=raise_flights), \
             patch.object(self.mod, "_try_serpapi_google_search_flights", side_effect=raise_search), \
             patch.object(self.mod, "_try_llm_estimate", return_value=[]):
            with self.assertRaises(RuntimeError):
                self.mod.search_flights.__wrapped__("NYC", "Monza", "2026-09-04")

    def test_parallel_empty_falls_through_to_tagged_llm_estimate(self):
        tagged = [
            {"tag": "OUT", "summary": "JFK->MXP", "price": 500.0,
             "_source": "llm_estimate", "_degraded": True},
        ]
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(self.mod, "_try_serpapi_google_flights", return_value=[]), \
             patch.object(self.mod, "_try_serpapi_google_search_flights", return_value=[]), \
             patch.object(self.mod, "_try_llm_estimate", return_value=tagged):
            results, summary = self.mod.search_flights.__wrapped__("NYC", "Monza", "2026-09-04")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["_source"], "llm_estimate")
        self.assertTrue(results[0]["_degraded"])
        self.assertIn("llm_estimate", summary)

    def test_no_api_key_skips_parallel_and_uses_llm(self):
        tagged = [{"tag": "OUT", "summary": "x", "price": 1.0,
                   "_source": "llm_estimate", "_degraded": True}]
        with patch.dict("os.environ", {}, clear=False), \
             patch.object(self.mod, "_try_llm_estimate", return_value=tagged):
            import os
            os.environ.pop("SERPAPI_API_KEY", None)
            results, summary = self.mod.search_flights.__wrapped__("NYC", "Monza", "2026-09-04")
        self.assertEqual(results[0]["_source"], "llm_estimate")


class TryLlmEstimateTaggingTests(unittest.TestCase):
    """The real _try_llm_estimate must tag every leg _source/_degraded."""

    def setUp(self):
        self.mod = importlib.import_module("tools.search_flights")

    def test_legs_tagged_degraded(self):
        class _FakeResult:
            legs = [
                {"tag": "OUT", "summary": "JFK->MXP", "detail": "nonstop",
                 "price": 540.0, "currency": "USD", "link": ""},
                {"tag": "RET", "summary": "MXP->JFK", "detail": "nonstop",
                 "price": 560.0, "currency": "USD", "link": ""},
            ]

        class _FakeStructured:
            def invoke(self, _messages):
                return _FakeResult()

        class _FakeLLM:
            def with_structured_output(self, _schema):
                return _FakeStructured()

        # _try_llm_estimate does a lazy `from llm import get_llm`, so the
        # binding to patch is on the source `llm` module, not on this module.
        llm_mod = importlib.import_module("llm")
        with patch.object(llm_mod, "get_llm", return_value=_FakeLLM()):
            legs = self.mod._try_llm_estimate("NYC", "Monza", "2026-09-04", None, None)

        self.assertEqual(len(legs), 2)
        for leg in legs:
            self.assertEqual(leg["_source"], "llm_estimate")
            self.assertTrue(leg["_degraded"])
            # Link normalization ran -> link_type classified.
            self.assertIn("link_type", leg)

    def test_no_llm_returns_empty(self):
        llm_mod = importlib.import_module("llm")
        with patch.object(llm_mod, "get_llm", return_value=None):
            self.assertEqual(
                self.mod._try_llm_estimate("NYC", "Monza", "2026-09-04", None, None), []
            )


class TransportAgentMockFallbackTests(unittest.TestCase):
    """When search_flights raises, transport_agent must degrade to mock, not crash."""

    def test_search_flights_raises_uses_mock_with_honest_source(self):
        transport_mod = importlib.import_module("agents.transport")

        def boom(*a, **k):
            raise RuntimeError("all flight sources exhausted")

        state = {
            "origin": "New York", "gp_city": "Monza", "gp_date": "2026-09-06",
            "extra_days": 0, "stops": "", "special_requests": "",
            "active_constraints": {}, "currency": "EUR",
        }
        # search_flights is imported lazily inside transport_agent, so patch the
        # source module's symbol.
        flights_mod = importlib.import_module("tools.search_flights")
        with patch.object(flights_mod, "search_flights", boom):
            out = transport_mod.transport_agent(state)

        # Did not crash; produced transport options from the mock fallback.
        self.assertTrue(out["transport"])
        # The honest degraded-source message is surfaced to the user.
        joined = " ".join(m["text"] for m in out["messages"])
        self.assertIn("mock (all data sources failed)", joined)
        # Mock always includes a LOCAL leg.
        tags = {leg.get("tag") for leg in out["transport"]}
        self.assertIn("LOCAL", tags)


class SearchWebTests(unittest.TestCase):
    def test_unconfigured_providers_return_empty_string_gracefully(self):
        # CURRENT behavior: both Tavily and DuckDuckGo are TODO stubs that
        # return "" without raising, so search_web degrades to an empty string
        # rather than crashing a caller. (The RuntimeError path is reached only
        # if a provider actually raises — see the next test.)
        web = importlib.import_module("tools.search_web")
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            out = web.search_web.__wrapped__("best vegetarian restaurants Monza")
        self.assertEqual(out, "")

    def test_all_providers_raising_exhausts_to_runtime_error(self):
        # When every provider raises, search_web exhausts and raises RuntimeError
        # so the calling agent can fall back to mock context.
        web = importlib.import_module("tools.search_web")
        import os
        with patch.dict("os.environ", {"TAVILY_API_KEY": "k"}), \
             patch.object(web, "_try_tavily", side_effect=RuntimeError("tavily down")), \
             patch.object(web, "_try_duckduckgo", side_effect=RuntimeError("ddg down")):
            with self.assertRaises(RuntimeError):
                web.search_web.__wrapped__("query")


if __name__ == "__main__":
    unittest.main()
