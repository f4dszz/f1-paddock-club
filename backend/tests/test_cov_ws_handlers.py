"""test-coverage-6 + test-coverage-14: WS chat/refine + quote/plan handlers.

These async WS handlers were a blind spot:

  _handle_chat (test-coverage-6):
    - copy-on-write rollback: refine_plan raising ValueError surfaces
      "Refine failed" and leaves the session plan UNCHANGED
    - a generic Exception surfaces "Internal chat error" + unchanged plan
    - RefineDeadlineError surfaces a timeout message + unchanged plan
    - success path commits the new state and emits reply/result/trace/done

  _handle_quote / _handle_plan (test-coverage-14):
    - _handle_quote generic-Exception fallback ("Quote recomputation failed")
    - _handle_plan success path emits message/result/trace/done

Also direct unit tests for refine._convert_eur_to and the
refine_reply / refine_state deterministic helpers.

Approach: a DummyWS records every send_json payload; handlers are driven via
asyncio.run. refine_plan / recompute_budget / _run_plan_with_limit are patched
so no LLM, network, or full DAG runs. The per-identity LLM daily ceiling is
disabled for the duration so repeated handler calls don't trip it.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402
from refine import RefineDeadlineError  # noqa: E402


class DummyWS:
    """Minimal WebSocket stand-in: records every send_json payload."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    def types(self) -> list[str]:
        return [m.get("type") for m in self.sent]

    def first_of(self, type_name: str) -> dict | None:
        for m in self.sent:
            if m.get("type") == type_name:
                return m
        return None


def _session_with_plan(plan: dict) -> dict:
    s = main.create_session()
    s["plan_state"] = plan
    s["user_id"] = "demo-user"
    return s


_BASE_PLAN = {
    "currency": "EUR",
    "tickets": [{"tag": "PICK", "name": "GA", "price": 100.0}],
    "transport": [{"tag": "ROUNDTRIP", "summary": "RT", "price": 200.0}],
    "hotel": [{"tag": "HOTEL", "name": "Inn", "price_per_night": 50.0}],
    "itinerary": ["Day 1"],
    "tour": ["Tour A"],
    "budget_summary": {"total": 1.0, "budget": 9.0, "within_budget": True, "currency": "EUR"},
}


class HandleChatTests(unittest.TestCase):
    def setUp(self):
        # Disable the daily LLM ceiling so repeated handler calls don't 429.
        self._env = patch.dict(os.environ, {"LLM_DAILY_CALL_LIMIT": "0"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_value_error_surfaces_refine_failed_and_keeps_plan(self):
        session = _session_with_plan(dict(_BASE_PLAN))
        original = session["plan_state"]
        ws = DummyWS()

        def boom(state, message, history):
            state["tour"] = ["MUTATED"]  # prove the working copy is discarded
            raise ValueError("bad selection")

        with patch.object(main, "refine_plan", boom):
            asyncio.run(main._handle_chat(ws, "make it direct", session))

        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("Refine failed", err["data"])
        self.assertIn("bad selection", err["data"])
        # Session plan must be untouched (copy-on-write rollback).
        self.assertIs(session["plan_state"], original)
        self.assertEqual(session["plan_state"]["tour"], ["Tour A"])
        # No commit signals on the failure path.
        self.assertNotIn("done", ws.types())
        self.assertNotIn("result", ws.types())

    def test_generic_exception_surfaces_internal_error_and_keeps_plan(self):
        session = _session_with_plan(dict(_BASE_PLAN))
        original = session["plan_state"]
        ws = DummyWS()

        def kaboom(state, message, history):
            raise RuntimeError("provider 500")

        with patch.object(main, "refine_plan", kaboom):
            asyncio.run(main._handle_chat(ws, "anything", session))

        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("Internal chat error", err["data"])
        self.assertIs(session["plan_state"], original)
        self.assertNotIn("done", ws.types())

    def test_deadline_error_surfaces_timeout_and_keeps_plan(self):
        session = _session_with_plan(dict(_BASE_PLAN))
        original = session["plan_state"]
        ws = DummyWS()

        def stall(state, message, history):
            raise RefineDeadlineError("deadline")

        with patch.object(main, "refine_plan", stall):
            asyncio.run(main._handle_chat(ws, "anything", session))

        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("timed out", err["data"].lower())
        self.assertIn("unchanged", err["data"].lower())
        self.assertIs(session["plan_state"], original)

    def test_success_commits_and_emits_reply_result_trace_done(self):
        session = _session_with_plan(dict(_BASE_PLAN))
        ws = DummyWS()

        new_state = dict(_BASE_PLAN)
        new_state["tour"] = ["Replaced Tour"]
        new_state["budget_summary"] = {
            "total": 5.0, "budget": 9.0, "within_budget": True, "currency": "EUR",
        }

        def good(state, message, history):
            return new_state, "Updated tour.", {"failed_tools": [], "updated_fields": ["tour"]}

        with patch.object(main, "refine_plan", good):
            # debug on so the trace event is actually emitted.
            session["debug"] = True
            asyncio.run(main._handle_chat(ws, "replace tour", session))

        types = ws.types()
        # Ordered envelope sequence: message (ack) -> reply -> result -> trace -> done.
        self.assertIn("reply", types)
        self.assertIn("result", types)
        self.assertIn("done", types)
        self.assertLess(types.index("reply"), types.index("result"))
        self.assertLess(types.index("result"), types.index("done"))
        # Session committed to the new state.
        self.assertIs(session["plan_state"], new_state)
        self.assertEqual(session["plan_state"]["tour"], ["Replaced Tour"])
        # The conversation turn was recorded.
        self.assertEqual(main.get_history(session)[-1], ("assistant", "Updated tour."))
        # A state_apply trace event was emitted for the changed 'tour' field.
        trace = ws.first_of("trace")
        self.assertIsNotNone(trace)


class HandleQuoteTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"LLM_DAILY_CALL_LIMIT": "0"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_generic_exception_surfaces_recompute_failed(self):
        session = _session_with_plan(dict(_BASE_PLAN))
        ws = DummyWS()

        def kaboom(state, selections=None):
            raise RuntimeError("unexpected recompute crash")

        with patch.object(main, "recompute_budget", kaboom):
            asyncio.run(main._handle_quote(ws, {"selections": {}}, session))

        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("Quote recomputation failed", err["data"])
        # No quote envelope was emitted on the failure path.
        self.assertIsNone(ws.first_of("quote"))

    def test_no_active_plan_is_user_error(self):
        session = main.create_session()  # empty plan_state
        ws = DummyWS()
        asyncio.run(main._handle_quote(ws, {"selections": {}}, session))
        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("No active plan", err["data"])


class HandlePlanTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"LLM_DAILY_CALL_LIMIT": "0"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_success_emits_message_result_trace_done(self):
        session = main.create_session()
        session["user_id"] = "demo-user"
        session["debug"] = True
        ws = DummyWS()

        stub_result = {
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
            "messages": [{"agent": "concierge", "text": "planning..."}],
        }

        async def fake_run(payload):
            return stub_result

        with patch.object(main, "_run_plan_with_limit", side_effect=fake_run):
            asyncio.run(main._handle_plan(
                ws,
                {"gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "2026-09-06",
                 "origin": "New York", "budget": 5000, "currency": "EUR", "extra_days": 0},
                session,
            ))

        types = ws.types()
        self.assertIn("result", types)
        self.assertIn("done", types)
        self.assertLess(types.index("result"), types.index("done"))
        # Result snapshot carries the stubbed plan.
        result = ws.first_of("result")
        self.assertEqual(result["data"]["tour"], ["Tour A"])
        # Session plan_state was replaced with the run result.
        self.assertEqual(session["plan_state"]["tour"], ["Tour A"])
        # debug=True -> a budget_final trace event is present.
        trace = ws.first_of("trace")
        self.assertIsNotNone(trace)

    def test_invalid_payload_surfaces_error_and_keeps_socket(self):
        session = main.create_session()
        session["user_id"] = "demo-user"
        ws = DummyWS()
        # Unsupported currency is rejected by _validate_plan_payload.
        asyncio.run(main._handle_plan(
            ws,
            {"gp_name": "Italian GP", "currency": "JPY"},
            session,
        ))
        err = ws.first_of("error")
        self.assertIsNotNone(err)
        self.assertIn("Invalid plan input", err["data"])
        self.assertNotIn("done", ws.types())


class ConvertEurToTests(unittest.TestCase):
    def test_eur_identity(self):
        from refine import _convert_eur_to

        self.assertEqual(_convert_eur_to(100.0, "EUR"), 100.0)

    def test_converts_to_usd(self):
        from refine import _convert_eur_to

        self.assertAlmostEqual(_convert_eur_to(100.0, "USD"), 108.0, places=4)

    def test_unknown_currency_is_non_crashing_passthrough(self):
        from refine import _convert_eur_to

        # from_eur fails open for unknown codes -> amount unchanged.
        self.assertEqual(_convert_eur_to(123.45, "JPY"), 123.45)


class RefineReplyHelperTests(unittest.TestCase):
    def test_summary_updated_fields(self):
        from refine_reply import build_deterministic_summary

        state = {
            "currency": "EUR",
            "transport": [{"a": 1}, {"a": 2}],
            "budget_summary": {"total": 1200, "budget": 2000, "within_budget": True},
        }
        out = build_deterministic_summary(
            state, {"transport": True}, [], date_override=False
        )
        self.assertIn("flights (2 options)", out)
        self.assertIn("within budget", out)

    def test_summary_failed_tools(self):
        from refine_reply import build_deterministic_summary

        out = build_deterministic_summary(
            {"currency": "EUR"}, {}, ["search_hotels_tool"], date_override=False
        )
        self.assertIn("Tool call failed", out)
        self.assertIn("hotels", out)

    def test_summary_empty_says_unchanged(self):
        from refine_reply import build_deterministic_summary

        out = build_deterministic_summary({"currency": "EUR"}, {}, [], date_override=False)
        self.assertEqual(out, "Plan unchanged.")

    def test_summary_date_override_note(self):
        from refine_reply import build_deterministic_summary

        out = build_deterministic_summary(
            {"currency": "EUR"}, {}, [], date_override=True
        )
        self.assertIn("alternate dates", out)

    def test_detect_date_override_false_on_empty_messages(self):
        from refine_reply import detect_date_override

        state = {"gp_date": "2026-09-06", "extra_days": 0}
        self.assertFalse(detect_date_override([], state))


class RefineStateHelperTests(unittest.TestCase):
    def test_count_and_collect_failed_tools(self):
        from langchain_core.messages import HumanMessage, ToolMessage

        from refine_state import (
            collect_failed_tool_details,
            collect_failed_tools,
            count_tool_messages,
        )

        msgs = [
            HumanMessage(content="hi"),
            ToolMessage(content="Hotel search failed: timeout. Try again.", name="search_hotels_tool", tool_call_id="1"),
            ToolMessage(content='[{"tag": "PICK"}]', name="search_tickets_tool", tool_call_id="2"),
        ]
        self.assertEqual(count_tool_messages(msgs), 2)
        failed = collect_failed_tools(msgs)
        self.assertEqual(failed, ["search_hotels_tool"])
        details = collect_failed_tool_details(msgs)
        self.assertIn("search_hotels_tool", details)

    def test_apply_tool_updates_writes_state_and_recomputes_budget(self):
        from langchain_core.messages import ToolMessage

        from refine_state import apply_tool_updates

        state = {
            "currency": "EUR", "budget": 5000, "gp_date": "2026-09-06", "extra_days": 0,
            "tickets": [], "transport": [], "hotel": [], "itinerary": [], "tour": [],
        }
        msgs = [
            ToolMessage(
                content='[{"tag": "ROUNDTRIP", "summary": "RT", "price": 200.0, "currency": "EUR"}]',
                name="search_flights_tool",
                tool_call_id="1",
            ),
        ]
        updated = apply_tool_updates(state, msgs)
        self.assertTrue(updated.get("transport"))
        self.assertEqual(len(state["transport"]), 1)
        # budget_summary recomputed as a side effect of a successful update.
        self.assertIn("budget_summary", state)
        self.assertIn("total", state["budget_summary"])

    def test_apply_tool_updates_skips_failed_results(self):
        from langchain_core.messages import ToolMessage

        from refine_state import apply_tool_updates

        state = {"currency": "EUR", "transport": [{"existing": True}]}
        msgs = [
            ToolMessage(
                content="Flight search failed: 429 rate limited.",
                name="search_flights_tool",
                tool_call_id="1",
            ),
        ]
        updated = apply_tool_updates(state, msgs)
        self.assertEqual(updated, {})
        # Existing state untouched on a failed tool result.
        self.assertEqual(state["transport"], [{"existing": True}])


if __name__ == "__main__":
    unittest.main()
