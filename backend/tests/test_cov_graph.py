"""test-coverage-4: graph orchestration (build_graph wiring + budget retry loop).

The conditional retry loop (should_retry_budget -> increment_retry -> hotel)
and its termination were untested end to end. Here we:
  - drive should_retry_budget through every branch directly, and
  - run a real compiled graph with STUB agent nodes (patched into the graph
    module namespace) so an over-budget plan routes back through
    increment_retry -> hotel and eventually terminates, asserting
    retry_count increments and the loop stops at the cap (2 retries).

Stubbing the nodes keeps the test hermetic (no LLM / no network) and lets us
force the over-budget condition deterministically.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import graph as graph_mod  # noqa: E402
from agents.budget import increment_retry, should_retry_budget  # noqa: E402


class ShouldRetryBudgetBranchTests(unittest.TestCase):
    def test_within_budget_is_done(self):
        self.assertEqual(should_retry_budget({"budget_ok": True, "retry_count": 0}), "done")

    def test_over_budget_with_retries_left_routes_to_hotel(self):
        self.assertEqual(
            should_retry_budget({"budget_ok": False, "retry_count": 0}), "retry_hotel"
        )
        self.assertEqual(
            should_retry_budget({"budget_ok": False, "retry_count": 1}), "retry_hotel"
        )

    def test_over_budget_retries_exhausted_is_done(self):
        # At the cap (>= 2) we give up rather than loop forever.
        self.assertEqual(
            should_retry_budget({"budget_ok": False, "retry_count": 2}), "done"
        )
        self.assertEqual(
            should_retry_budget({"budget_ok": False, "retry_count": 5}), "done"
        )

    def test_increment_retry_bumps_count(self):
        out = increment_retry({"retry_count": 0})
        self.assertEqual(out["retry_count"], 1)
        out2 = increment_retry({"retry_count": 4})
        self.assertEqual(out2["retry_count"], 5)
        # Emits a concierge status message so the user sees the retry.
        self.assertTrue(out["messages"])
        self.assertEqual(out["messages"][0]["agent"], "concierge")


class StubbedGraphRetryLoopTests(unittest.TestCase):
    """Run the real compiled graph with stub agent nodes that force over-budget.

    The hotel node is the loop body re-entered on retry, so we count its
    invocations to prove the loop ran and then terminated at the cap.
    """

    def setUp(self):
        # Snapshot the names graph.py bound at import so we can restore them.
        self._orig = {
            name: getattr(graph_mod, name)
            for name in (
                "parse_input", "ticket_agent", "transport_agent", "hotel_agent",
                "itinerary_agent", "tour_agent", "budget_agent",
            )
        }
        self.hotel_calls = 0

        def stub_parse(state):
            return {"messages": [], "budget_ok": False, "retry_count": 0}

        def stub_ticket(state):
            return {"tickets": [{"tag": "PICK", "name": "GA", "price": 100.0}], "messages": []}

        def stub_transport(state):
            return {"transport": [{"tag": "ROUNDTRIP", "summary": "RT", "price": 200.0}], "messages": []}

        def stub_hotel(state):
            self.hotel_calls += 1
            # Hotel never gets cheap enough -> always over budget.
            return {"hotel": [{"tag": "HOTEL", "name": "Pricey", "price_per_night": 9999.0}], "messages": []}

        def stub_itinerary(state):
            return {"itinerary": ["Day 1"], "messages": []}

        def stub_tour(state):
            return {"tour": ["Tour A"], "messages": []}

        def stub_budget(state):
            # Deterministically OVER budget; mirrors budget_agent's control
            # outputs (budget_ok + budget_summary) without the recompute math.
            retry = state.get("retry_count", 0)
            return {
                "budget_ok": False,
                "budget_summary": {
                    "total": 99999.0, "budget": 100.0, "within_budget": False,
                    "currency": "EUR", "retry_exhausted": retry >= 2,
                },
                "messages": [],
            }

        graph_mod.parse_input = stub_parse
        graph_mod.ticket_agent = stub_ticket
        graph_mod.transport_agent = stub_transport
        graph_mod.hotel_agent = stub_hotel
        graph_mod.itinerary_agent = stub_itinerary
        graph_mod.tour_agent = stub_tour
        graph_mod.budget_agent = stub_budget

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(graph_mod, name, fn)

    def test_over_budget_loops_then_terminates_at_cap(self):
        result = graph_mod.plan_trip({
            "gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "2026-09-06",
            "origin": "New York", "budget": 100, "currency": "EUR", "extra_days": 0,
        })
        # Loop terminated (did not hang) and hit the retry cap of 2.
        self.assertEqual(result["retry_count"], 2)
        # hotel ran: once initially + once per retry = 3 total.
        self.assertEqual(self.hotel_calls, 3)
        bs = result["budget_summary"]
        self.assertFalse(bs["within_budget"])
        self.assertTrue(bs["retry_exhausted"])

    def test_within_budget_does_not_retry(self):
        # Re-point budget to report within-budget on the first pass.
        def ok_budget(state):
            return {
                "budget_ok": True,
                "budget_summary": {
                    "total": 50.0, "budget": 100.0, "within_budget": True,
                    "currency": "EUR",
                },
                "messages": [],
            }

        graph_mod.budget_agent = ok_budget
        result = graph_mod.plan_trip({
            "gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "2026-09-06",
            "origin": "New York", "budget": 100, "currency": "EUR", "extra_days": 0,
        })
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(self.hotel_calls, 1)  # no retry -> hotel ran exactly once
        self.assertTrue(result["budget_summary"]["within_budget"])


if __name__ == "__main__":
    unittest.main()
