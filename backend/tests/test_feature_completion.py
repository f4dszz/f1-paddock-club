from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from langchain_core.messages import ToolMessage


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _sample_state() -> dict:
    return {
        "currency": "EUR",
        "budget": 2000,
        "depart_date": "2026-09-04",
        "return_date": "2026-09-09",
        "tickets": [
            {"tag": "VALUE", "name": "GA", "price": 100, "currency": "EUR", "link": "https://tickets.formula1.com"},
            {"tag": "PICK", "name": "Grandstand", "price": 300, "currency": "EUR", "link": "https://tickets.formula1.com"},
        ],
        "transport": [
            {"tag": "ROUNDTRIP", "summary": "A", "detail": "Direct", "price": 400, "currency": "EUR", "link": "https://www.google.com/travel/flights"},
            {"tag": "ROUNDTRIP", "summary": "B", "detail": "Direct", "price": 900, "currency": "EUR", "link": "https://www.google.com/travel/flights"},
            {"tag": "LOCAL", "summary": "Transit", "detail": "Train", "price": 20, "currency": "EUR", "link": ""},
        ],
        "hotel": [
            {"tag": "BUDGET", "name": "Cheap", "price_per_night": 80, "currency": "EUR", "nights": 5, "link": "https://www.booking.com"},
            {"tag": "TOP", "name": "Fancy", "price_per_night": 200, "currency": "EUR", "nights": 5, "link": "https://www.booking.com"},
        ],
        "itinerary": ["Day 1 (Friday): Arrive.", "Day 2 (Saturday): Dinner in Monza."],
        "tour": ["🏎 Monza Circuit Museum (€15) — race history"],
        "retry_count": 0,
    }


class FeatureCompletionTests(unittest.TestCase):
    def test_recompute_budget_reacts_to_selected_hotel(self):
        from tools.recompute import recompute_budget

        state = _sample_state()
        baseline = recompute_budget(state)
        selected = recompute_budget(state, selections={"hotel": [1]})

        self.assertEqual(baseline["basis"], "baseline")
        self.assertEqual(selected["basis"], "selected")
        self.assertGreater(selected["total"], baseline["total"])
        self.assertEqual(selected["selected_indices"], {"hotel": [1]})

    def test_unpriced_selection_marks_quote_incomplete(self):
        from tools.recompute import recompute_budget

        state = _sample_state()
        state["transport"].insert(0, {
            "tag": "ROUNDTRIP",
            "summary": "Unpriced direct",
            "detail": "Direct",
            "price": 0,
            "currency": "EUR",
            "link": "https://www.google.com/travel/flights",
        })

        quote = recompute_budget(state, selections={"transport": [0]})
        self.assertFalse(quote["quote_complete"])
        self.assertFalse(quote["within_budget"])
        self.assertIn("Flights", quote["missing_price_categories"])

    def test_invalid_selection_index_rejected(self):
        from tools.recompute import recompute_budget

        with self.assertRaises(ValueError):
            recompute_budget(_sample_state(), selections={"hotel": [99]})

    def test_constraints_merge_and_clear(self):
        from tools._constraints import empty_constraints, merge_constraints

        c = merge_constraints(empty_constraints(), "only direct flights and only Marriott or Hilton, vegetarian, wheelchair, avoid luxury")
        self.assertTrue(c["direct_only"])
        self.assertEqual(c["allowed_hotel_brands"], ["Marriott", "Hilton"])
        self.assertTrue(c["accessibility"])
        self.assertTrue(c["avoid_luxury"])
        self.assertEqual(c["budget_strategy"], "cheapest")

        c = merge_constraints(c, "connections are OK and any brand is fine")
        self.assertFalse(c["direct_only"])
        self.assertEqual(c["allowed_hotel_brands"], [])

    def test_update_itinerary_tool_persists_via_tool_mapping(self):
        from refine import _apply_tool_updates, _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "Move Saturday dinner to Brera") if t.name == "update_itinerary_tool")
        content = tool.invoke({"request": "Move Saturday dinner to Brera vegetarian restaurant"})
        data = json.loads(content)
        self.assertTrue(any("Brera vegetarian restaurant" in line for line in data))

        updated = _apply_tool_updates(state, [
            ToolMessage(content=content, name="update_itinerary_tool", tool_call_id="call-1")
        ])
        self.assertEqual(updated, {"itinerary": True})
        self.assertTrue(any("Brera vegetarian restaurant" in line for line in state["itinerary"]))

    def test_update_itinerary_tool_normalizes_dict_input_and_targets_day(self):
        from refine import _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "Move Saturday dinner to Brera") if t.name == "update_itinerary_tool")
        content = tool.invoke({
            "request": "Move Saturday dinner to Brera vegetarian restaurant",
            "current_itinerary_json": json.dumps([
                {"day": 1, "title": "Thursday", "items": ["Arrive", "Check in"]},
                {"day": 2, "title": "Friday", "items": ["FP1", "FP2"]},
                {"day": "Day 3", "title": "Saturday", "items": ["Qualifying", "Dinner in Monza"]},
            ]),
        })
        data = json.loads(content)

        self.assertTrue(data[2].startswith("Day 3 (Saturday):"))
        self.assertIn("Brera vegetarian restaurant", data[2])
        self.assertNotIn("{'day'", "\n".join(data))

    def test_update_tour_tool_persists_via_tool_mapping(self):
        from refine import _apply_tool_updates, _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "把景点改成米兰设计博物馆") if t.name == "update_tour_tool")
        content = tool.invoke({"request": "把景点改成米兰设计博物馆"})
        data = json.loads(content)
        self.assertTrue(any("米兰设计博物馆" in line for line in data))

        updated = _apply_tool_updates(state, [
            ToolMessage(content=content, name="update_tour_tool", tool_call_id="call-2")
        ])
        self.assertEqual(updated, {"tour": True})
        self.assertTrue(any("米兰设计博物馆" in line for line in state["tour"]))

    def test_update_tour_tool_normalizes_dict_input(self):
        from refine import _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "把景点改成米兰设计博物馆") if t.name == "update_tour_tool")
        content = tool.invoke({
            "request": "把景点改成米兰设计博物馆",
            "current_tour_json": json.dumps([
                {"name": "Duomo", "price": "€0-€25", "description": "Cathedral visit"},
                {"name": "Design Museum", "price": "€15", "description": "Design culture"},
            ]),
        })
        data = json.loads(content)

        self.assertTrue(any("米兰设计博物馆" in line for line in data))
        self.assertTrue(any(line.startswith("米兰设计博物馆 —") for line in data))
        self.assertNotIn("{'name'", "\n".join(data))

    def test_update_tour_tool_targets_named_existing_item(self):
        from refine import _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "把景点改成米兰设计博物馆") if t.name == "update_tour_tool")
        content = tool.invoke({
            "request": "把景点改成米兰设计博物馆，替换当前的 Pinacoteca di Brera, Milan",
            "current_tour_json": json.dumps([
                "Autodromo Nazionale Monza (€30) — race museum",
                "Pinacoteca di Brera, Milan (€15) — classic art museum",
            ]),
        })
        data = json.loads(content)

        self.assertEqual(data[0], "Autodromo Nazionale Monza (€30) — race museum")
        self.assertTrue(data[1].startswith("米兰设计博物馆 —"))

    def test_link_metadata_defaults_are_present_in_agent_mocks(self):
        from agents import _hotel_mock, _ticket_mock, _transport_mock

        state = {
            "gp_name": "Italian GP",
            "gp_city": "Monza",
            "gp_date": "2026-09-06",
            "origin": "New York",
            "depart_date": "2026-09-04",
            "return_date": "2026-09-09",
            "extra_days": 2,
        }
        items = _ticket_mock(state) + _transport_mock(state) + _hotel_mock(state)
        for item in items:
            self.assertIn("provider", item)
            self.assertIn("link_type", item)
            self.assertIn("booking_confidence", item)


class QuoteWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_ws_quote_does_not_mutate_plan_state(self):
        from main import _handle_quote

        class DummyWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        state = _sample_state()
        original = copy.deepcopy(state)
        session = {"plan_state": state}
        ws = DummyWS()

        await _handle_quote(ws, {"quote_id": 7, "selections": {"hotel": [1]}}, session)

        self.assertEqual(session["plan_state"], original)
        self.assertEqual(ws.sent[0]["type"], "quote")
        self.assertEqual(ws.sent[0]["data"]["quote_id"], 7)
        self.assertEqual(ws.sent[0]["data"]["budget_summary"]["basis"], "selected")

    async def test_ws_quote_before_plan_returns_error(self):
        from main import _handle_quote

        class DummyWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = DummyWS()
        await _handle_quote(ws, {"selections": {"hotel": [0]}}, {"plan_state": {}})
        self.assertEqual(ws.sent[0]["type"], "error")
        self.assertIn("No active plan", ws.sent[0]["data"])


if __name__ == "__main__":
    unittest.main()
