from __future__ import annotations

import sys
import unittest
import importlib
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class P0TrustFixTests(unittest.TestCase):
    def test_no_tool_itinerary_change_gets_unapplied_reply(self):
        from refine import _requests_unpersisted_change, _unapplied_change_reply

        msg = "Move Saturday dinner to Brera vegetarian restaurant"
        self.assertTrue(_requests_unpersisted_change(msg))
        reply = _unapplied_change_reply(msg).lower()
        self.assertIn("no plan cards were changed", reply)
        self.assertNotIn("updated the itinerary", reply)

    def test_chinese_itinerary_change_gets_unapplied_reply(self):
        from refine import _requests_unpersisted_change, _unapplied_change_reply

        msg = "把周六晚餐改到 Brera，周日早点回酒店"
        self.assertTrue(_requests_unpersisted_change(msg))
        reply = _unapplied_change_reply(msg)
        self.assertIn("没有应用", reply)

    def test_direct_flight_filter_drops_stops_and_unknowns(self):
        from tools.search_flights import _filter_by_max_stops

        results = [
            {"tag": "ROUNDTRIP", "detail": "Direct - 2h30m", "price": 300},
            {"tag": "ROUNDTRIP", "detail": "1 stop(s) - 5h10m", "price": 200},
            {"tag": "INFO", "detail": "Search snippets about direct flights", "price": 0},
            {"tag": "ROUNDTRIP", "detail": "Duration 4h", "price": 250},
        ]

        filtered = _filter_by_max_stops(results, 0)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["stops"], 0)
        self.assertTrue(filtered[0]["constraint_match"])
        self.assertNotIn("1 stop", filtered[0]["detail"])

    def test_direct_flight_filter_distrusts_bad_structured_zero_stops(self):
        from tools.search_flights import _filter_by_max_stops

        results = [
            {"tag": "ROUNDTRIP", "detail": "1 stop on Emirates via Dubai", "stops": 0, "price": 300},
            {"tag": "ROUNDTRIP", "detail": "Direct - 2h30m", "stops": 0, "price": 500},
        ]

        filtered = _filter_by_max_stops(results, 0)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["detail"], "Direct - 2h30m")

    def test_chinese_direct_flight_intent_is_detected(self):
        from refine import _intent_max_stops
        from agents import _direct_only_requested

        self.assertEqual(_intent_max_stops("只要直航，不要中转"), 0)
        self.assertTrue(_direct_only_requested("请安排直达航班"))

    def test_direct_flight_search_post_filter_enforces_real_sources(self):
        flights_module = importlib.import_module("tools.search_flights")

        def fake_google_flights(*args, **kwargs):
            return [
                {"tag": "ROUNDTRIP", "summary": "JFK -> MXP", "detail": "Direct - 8h00m", "price": 500},
                {"tag": "ROUNDTRIP", "summary": "JFK -> MXP", "detail": "1 stop(s) - 12h00m", "price": 300},
            ]

        def fake_google_search(*args, **kwargs):
            return [{"tag": "INFO", "summary": "Flights from $300", "detail": "1 stop fares are cheaper", "price": 0}]

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(flights_module, "_try_serpapi_google_flights", side_effect=fake_google_flights), \
             patch.object(flights_module, "_try_serpapi_google_search_flights", side_effect=fake_google_search):
            results, _summary = flights_module.search_flights.__wrapped__(
                origin="New York",
                dest="Monza",
                date="2026-09-04",
                return_date="2026-09-09",
                stops=0,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["stops"], 0)
        self.assertNotIn("1 stop", results[0]["detail"])

    def test_direct_flight_search_does_not_fallback_to_connecting_price(self):
        flights_module = importlib.import_module("tools.search_flights")

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(flights_module, "_try_serpapi_google_flights", return_value=[
                 {"tag": "ROUNDTRIP", "summary": "JFK -> MXP", "detail": "1 stop(s) - 12h00m", "price": 300},
             ]), \
             patch.object(flights_module, "_try_serpapi_google_search_flights", return_value=[
                 {"tag": "INFO", "summary": "Flights from $300", "detail": "1 stop fares are cheaper", "price": 0},
             ]), \
             patch.object(flights_module, "_try_llm_estimate", return_value=[]):
            with self.assertRaises(RuntimeError):
                flights_module.search_flights.__wrapped__(
                    origin="New York",
                    dest="Monza",
                    date="2026-09-04",
                    return_date="2026-09-09",
                    stops=0,
                )

    def test_hotel_brand_filter_keeps_only_matching_brands(self):
        from tools.search_hotels import _filter_by_allowed_brands

        results = [
            {"name": "Moxy Milan Linate"},
            {"name": "Hilton Garden Inn Milan North"},
            {"name": "B&B Hotel Milano"},
            {"name": "Hotel Royal Falcone"},
        ]

        filtered = _filter_by_allowed_brands(results, "Marriott or Hilton", True)
        names = [item["name"] for item in filtered]
        self.assertEqual(names, ["Moxy Milan Linate", "Hilton Garden Inn Milan North"])
        self.assertTrue(all(item["constraint_match"] for item in filtered))

    def test_chinese_hotel_brand_intent_and_filter(self):
        from refine import _intent_allowed_brands
        from agents import _requested_hotel_brands
        from tools.search_hotels import _filter_by_allowed_brands

        self.assertIn("万豪", _intent_allowed_brands("只要万豪或希尔顿，靠近赛道"))
        self.assertIn("希尔顿", _requested_hotel_brands("只要万豪或希尔顿，靠近赛道"))

        results = [
            {"name": "Moxy Milan Linate"},
            {"name": "Hilton Garden Inn Milan North"},
            {"name": "B&B Hotel Milano"},
        ]

        filtered = _filter_by_allowed_brands(results, "万豪或希尔顿", True)
        names = [item["name"] for item in filtered]
        self.assertEqual(names, ["Moxy Milan Linate", "Hilton Garden Inn Milan North"])

    def test_hotel_search_strict_brand_post_filter_enforces_real_sources(self):
        hotels_module = importlib.import_module("tools.search_hotels")

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(hotels_module, "_try_serpapi_google_hotels", return_value=[
                 {"name": "Moxy Milan Linate", "price_per_night": 180, "tag": "NEAR"},
                 {"name": "B&B Hotel Milano", "price_per_night": 90, "tag": "BUDGET"},
             ]), \
             patch.object(hotels_module, "_try_serpapi_google_maps_hotels", return_value=[
                 {"name": "Hilton Garden Inn Milan North", "price_per_night": 155, "tag": "NEAR"},
                 {"name": "Hotel Royal Falcone", "price_per_night": 120, "tag": "NEAR"},
             ]):
            results, _summary = hotels_module.search_hotels.__wrapped__(
                city="Monza",
                checkin="2026-09-04",
                checkout="2026-09-09",
                brand="Marriott or Hilton",
                strict_brand=True,
            )

        names = [item["name"] for item in results]
        self.assertEqual(names, ["Moxy Milan Linate", "Hilton Garden Inn Milan North"])
        self.assertNotIn("B&B Hotel Milano", names)
        self.assertNotIn("Hotel Royal Falcone", names)

    def test_hotel_search_strict_brand_no_match_does_not_fallback_to_other_brands(self):
        hotels_module = importlib.import_module("tools.search_hotels")

        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}), \
             patch.object(hotels_module, "_try_serpapi_google_hotels", return_value=[
                 {"name": "B&B Hotel Milano", "price_per_night": 90, "tag": "BUDGET"},
             ]), \
             patch.object(hotels_module, "_try_serpapi_google_maps_hotels", return_value=[]), \
             patch.object(hotels_module, "_try_llm_estimate", return_value=[
                 {"name": "Hotel Royal Falcone", "price_per_night": 120, "tag": "NEAR"},
             ]):
            with self.assertRaises(RuntimeError):
                hotels_module.search_hotels.__wrapped__(
                    city="Monza",
                    checkin="2026-09-04",
                    checkout="2026-09-09",
                    brand="Marriott",
                    strict_brand=True,
                )

    def test_failed_tool_summary_preserves_reason(self):
        from refine import _build_deterministic_summary

        reply = _build_deterministic_summary(
            state={"currency": "EUR", "budget_summary": {"total": 1200, "budget": 2000, "within_budget": True}},
            updated_fields={},
            failed_tools=["search_hotels_tool"],
            date_override=False,
            failed_tool_details={
                "search_hotels_tool": "Hotel search failed: No hotel options matched required brand(s): Marriott. Try adjusting criteria."
            },
        )

        self.assertIn("No hotel options matched required brand", reply)

    def test_budget_retry_exhaustion_is_marked_honestly(self):
        from agents import budget_agent

        state = {
            "currency": "EUR",
            "budget": 100,
            "retry_count": 2,
            "tickets": [{"tag": "PICK", "price": 300, "currency": "EUR"}],
            "transport": [],
            "hotel": [],
            "tour": [],
        }

        result = budget_agent(state)
        summary = result["budget_summary"]
        message = result["messages"][0]["text"]
        self.assertFalse(summary["within_budget"])
        self.assertTrue(summary["retry_exhausted"])
        self.assertIn("no feasible plan found within budget", message)


if __name__ == "__main__":
    unittest.main()
