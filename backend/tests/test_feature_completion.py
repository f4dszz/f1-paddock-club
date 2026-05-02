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

    def test_none_prices_are_treated_as_missing_not_crashes(self):
        from tools.recompute import recompute_budget

        state = _sample_state()
        state["tickets"][0]["price"] = None
        state["transport"][0]["price"] = None
        state["hotel"][0]["price_per_night"] = None

        baseline = recompute_budget(state)
        self.assertTrue(baseline["quote_complete"])
        self.assertGreater(baseline["total"], 0)

        quote = recompute_budget(state, selections={"ticket": [0], "transport": [0], "hotel": [0]})
        self.assertFalse(quote["quote_complete"])
        self.assertIn("Tickets", quote["missing_price_categories"])
        self.assertIn("Flights", quote["missing_price_categories"])
        self.assertIn("Hotel", quote["missing_price_categories"])

    def test_invalid_selection_index_rejected(self):
        from tools.recompute import recompute_budget

        with self.assertRaises(ValueError):
            recompute_budget(_sample_state(), selections={"hotel": [99]})

    def test_selection_shape_rejects_unknown_and_string_values(self):
        from tools.recompute import recompute_budget

        with self.assertRaises(ValueError):
            recompute_budget(_sample_state(), selections={"tour": [0]})
        with self.assertRaises(ValueError):
            recompute_budget(_sample_state(), selections={"hotel": ["1"]})
        with self.assertRaises(ValueError):
            recompute_budget(_sample_state(), selections={"hotel": -1})
        self.assertEqual(
            recompute_budget(_sample_state(), selections=None)["basis"],
            "baseline",
        )

    def test_duplicate_selection_indexes_are_deduped(self):
        from tools.recompute import recompute_budget

        single = recompute_budget(_sample_state(), selections={"hotel": [0]})
        duplicated = recompute_budget(_sample_state(), selections={"hotel": [0, 0, 0]})

        self.assertEqual(single["total"], duplicated["total"])

    def test_constraints_merge_and_clear(self):
        from tools._constraints import empty_constraints, merge_constraints, normalize_constraints

        c = merge_constraints(empty_constraints(), "only direct flights and only Marriott or Hilton, vegetarian, wheelchair, avoid luxury")
        self.assertTrue(c["direct_only"])
        self.assertEqual(c["allowed_hotel_brands"], ["Marriott", "Hilton"])
        self.assertTrue(c["accessibility"])
        self.assertTrue(c["avoid_luxury"])
        self.assertEqual(c["budget_strategy"], "cheapest")

        c = merge_constraints(c, "connections are OK and any brand is fine")
        self.assertFalse(c["direct_only"])
        self.assertEqual(c["allowed_hotel_brands"], [])

        normalized = normalize_constraints({"allowed_hotel_brands": ["W", "AC Hotel", "JW Marriott"]})
        self.assertEqual(normalized["allowed_hotel_brands"], ["Marriott"])

    def test_constraint_filter_removes_non_direct_flights_and_non_brand_hotels(self):
        from refine import _apply_constraint_filters

        state = _sample_state()
        state["active_constraints"] = {
            "direct_only": True,
            "allowed_hotel_brands": ["Marriott", "Hilton"],
        }
        state["transport"] = [
            {"tag": "ROUNDTRIP", "summary": "A", "detail": "1 stop(s) - 8h", "price": 200, "currency": "EUR"},
            {"tag": "ROUNDTRIP", "summary": "B", "detail": "Direct - 4h", "price": 300, "currency": "EUR", "stops": 0},
            {"tag": "LOCAL", "summary": "Transit", "detail": "Train", "price": 20, "currency": "EUR"},
        ]
        state["hotel"] = [
            {"tag": "NEAR", "name": "Random Inn", "price_per_night": 80, "currency": "EUR", "nights": 5},
            {"tag": "NEAR", "name": "JW Marriott Downtown", "price_per_night": 180, "currency": "EUR", "nights": 5},
            {"tag": "NEAR", "name": "Hilton Central", "price_per_night": 160, "currency": "EUR", "nights": 5},
        ]

        updated = _apply_constraint_filters(state)

        self.assertEqual(updated, {"transport": True, "hotel": True})
        self.assertFalse(any("stop" in leg.get("detail", "").lower() for leg in state["transport"] if leg.get("tag") != "LOCAL"))
        self.assertEqual([h["name"] for h in state["hotel"]], ["JW Marriott Downtown", "Hilton Central"])

    def test_constraint_filter_distrusts_bad_structured_direct_flag(self):
        from refine import _apply_constraint_filters

        state = _sample_state()
        state["active_constraints"] = {"direct_only": True}
        state["transport"] = [
            {
                "tag": "ROUNDTRIP",
                "summary": "Lisbon to Singapore — 1 stop on Emirates via Dubai",
                "detail": "Structured field says direct, but display text says 1 stop.",
                "stops": 0,
                "price": 700,
                "currency": "EUR",
            },
            {"tag": "ROUNDTRIP", "summary": "Lisbon to Singapore", "detail": "Direct - 14h", "stops": 0, "price": 900, "currency": "EUR"},
        ]

        updated = _apply_constraint_filters(state, updated_fields={"transport": True}, force=True)

        self.assertEqual(updated, {"transport": True})
        self.assertEqual(len(state["transport"]), 1)
        self.assertEqual(state["transport"][0]["detail"], "Direct - 14h")

    def test_constraint_filter_skips_unrelated_turn_when_constraints_unchanged(self):
        from refine import _apply_constraint_filters

        state = _sample_state()
        state["active_constraints"] = {"direct_only": True}
        state["transport"] = [
            {"tag": "ROUNDTRIP", "summary": "A", "detail": "1 stop(s) - 8h", "price": 200, "currency": "EUR"},
            {"tag": "ROUNDTRIP", "summary": "B", "detail": "Direct - 4h", "price": 300, "currency": "EUR", "stops": 0},
        ]

        updated = _apply_constraint_filters(state, updated_fields={"tour": True}, force=False)

        self.assertEqual(updated, {})
        self.assertEqual(len(state["transport"]), 2)

    def test_recompute_budget_tool_ignores_non_whitelisted_state_overrides(self):
        from refine import _build_tools

        state = _sample_state()
        tool = next(t for t in _build_tools(state, "check the budget") if t.name == "recompute_budget_tool")

        baseline = json.loads(tool.invoke({"state_json": ""}))
        dict_result = json.loads(tool.invoke({
            "state_json": {
                "currency": "EUR",
                "hotel": [{"name": "Injected Free Hotel", "price_per_night": 1, "currency": "EUR"}],
            }
        }))
        empty_result = json.loads(tool.invoke({"state_json": ""}))

        self.assertEqual(dict_result["currency"], "EUR")
        self.assertEqual(empty_result["currency"], "EUR")
        self.assertEqual(dict_result["total"], baseline["total"])
        self.assertGreater(dict_result["total"], 0)
        self.assertGreater(empty_result["total"], 0)

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
        state["itinerary"] = [
            {"day": 1, "title": "Thursday", "items": ["Arrive", "Check in"]},
            {"day": 2, "title": "Friday", "items": ["FP1", "FP2"]},
            {"day": "Day 3", "title": "Saturday", "items": ["Qualifying", "Dinner in Monza"]},
        ]
        tool = next(t for t in _build_tools(state, "Move Saturday dinner to Brera") if t.name == "update_itinerary_tool")
        self.assertNotIn("current_itinerary_json", tool.args)
        content = tool.invoke({"request": "Move Saturday dinner to Brera vegetarian restaurant"})
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
        state["tour"] = [
            {"name": "Duomo", "price": "€0-€25", "description": "Cathedral visit"},
            {"name": "Design Museum", "price": "€15", "description": "Design culture"},
        ]
        tool = next(t for t in _build_tools(state, "把景点改成米兰设计博物馆") if t.name == "update_tour_tool")
        self.assertNotIn("current_tour_json", tool.args)
        content = tool.invoke({"request": "把景点改成米兰设计博物馆"})
        data = json.loads(content)

        self.assertTrue(any("米兰设计博物馆" in line for line in data))
        self.assertTrue(any(line.startswith("米兰设计博物馆 —") for line in data))
        self.assertNotIn("{'name'", "\n".join(data))

    def test_update_tour_tool_targets_named_existing_item(self):
        from refine import _build_tools

        state = _sample_state()
        state["tour"] = [
            "Autodromo Nazionale Monza (€30) — race museum",
            "Pinacoteca di Brera, Milan (€15) — classic art museum",
        ]
        tool = next(t for t in _build_tools(state, "把景点改成米兰设计博物馆") if t.name == "update_tour_tool")
        content = tool.invoke({"request": "把景点改成米兰设计博物馆，替换当前的 Pinacoteca di Brera, Milan"})
        data = json.loads(content)

        self.assertEqual(data[0], "Autodromo Nazionale Monza (€30) — race museum")
        self.assertTrue(data[1].startswith("米兰设计博物馆 —"))

    def test_update_tour_tool_replaces_english_with_targeted_item(self):
        from refine import _build_tools

        state = _sample_state()
        state["tour"] = [
            "Singapore F1 Pit Building & Circuit Park Walk (€0) — motorsport walk",
            "Gardens by the Bay (€0-€12) — accessible waterfront paths",
        ]
        tool = next(t for t in _build_tools(state, "Replace Gardens by the Bay with National Gallery Singapore") if t.name == "update_tour_tool")
        content = tool.invoke({
            "request": "Replace Gardens by the Bay with National Gallery Singapore in the Singapore GP trip recommendations"
        })
        data = json.loads(content)

        self.assertEqual(data[0], "Singapore F1 Pit Building & Circuit Park Walk (€0) — motorsport walk")
        self.assertTrue(data[1].startswith("National Gallery Singapore —"))
        self.assertEqual(data[1].split(" — ", 1)[0], "National Gallery Singapore")

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

    async def test_ws_quote_rejects_invalid_selection_shapes_without_mutating(self):
        from main import _handle_quote

        class DummyWS:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        invalid_payloads = [
            {"selections": []},
            {"selections": None},
            {"selections": {"tour": [0]}},
            {"selections": {"hotel": ["1"]}},
            {"selections": {"hotel": [None]}},
            {"selections": {"hotel": -1}},
            {"selections": {"hotel": [99]}},
        ]

        for payload in invalid_payloads:
            state = _sample_state()
            original = copy.deepcopy(state)
            ws = DummyWS()
            await _handle_quote(ws, payload, {"plan_state": state})
            self.assertEqual(state, original)
            self.assertEqual(ws.sent[0]["type"], "error")
            self.assertIn("Invalid quote selection", ws.sent[0]["data"])


if __name__ == "__main__":
    unittest.main()
