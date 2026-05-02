from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _state(active: dict | None = None, **overrides) -> dict:
    base = {
        "gp_name": "Italian GP",
        "gp_city": "Monza",
        "gp_date": "2026-09-06",
        "origin": "New York",
        "budget": 2500,
        "currency": "EUR",
        "depart_date": "2026-09-04",
        "return_date": "2026-09-09",
        "special_requests": "",
        "active_constraints": active or {},
    }
    base.update(overrides)
    return base


class RationaleBuilderTests(unittest.TestCase):
    def test_hotel_rationale_includes_distance_brand_and_price(self):
        from tools._rationale import build_hotel_rationale

        hotels = [
            {
                "name": "Moxy Milan Linate",
                "price_per_night": 145,
                "currency": "EUR",
                "nights": 5,
                "distance": "8.2 km to circuit",
                "rating": "8.4",
                "tag": "NEAR",
                "_source": "google_hotels",
            },
            {
                "name": "Hotel de la Ville",
                "price_per_night": 135,
                "currency": "EUR",
                "nights": 5,
                "distance": "10 km to circuit",
                "rating": "8.2",
                "tag": "NEAR",
                "_source": "google_hotels",
            },
        ]
        r = build_hotel_rationale(
            hotels[0],
            hotels,
            _state(active={"allowed_hotel_brands": ["Marriott"]}),
        )

        self.assertEqual(r["card_type"], "hotel")
        self.assertEqual(r["source"], "google_hotels")
        self.assertEqual(r["fallback_chain"], ["serpapi"])
        self.assertIn("inferred from the final card source", r["source_path_note"])
        joined = "\n".join(r["reasons"])
        self.assertIn("8.2", joined)
        self.assertIn("Marriott", joined)
        self.assertIn("145", joined)
        self.assertEqual(r["constraint_matches"]["allowed_hotel_brands"]["matched"], "Marriott")

    def test_flight_rationale_marks_direct_only_constraint(self):
        from tools._rationale import build_flight_rationale

        flights = [
            {
                "tag": "ROUNDTRIP",
                "summary": "JFK -> MXP",
                "detail": "Direct - 8h00m",
                "price": 500,
                "currency": "USD",
                "stops": 0,
                "_source": "google_flights",
                "provider": "Google Flights",
            },
            {
                "tag": "ROUNDTRIP",
                "summary": "JFK -> MXP",
                "detail": "1 stop - 12h00m",
                "price": 320,
                "currency": "USD",
                "stops": 1,
                "_source": "google_flights",
            },
        ]
        r = build_flight_rationale(flights[0], flights, _state(active={"direct_only": True}))

        self.assertEqual(r["card_type"], "flight")
        self.assertTrue(r["constraint_matches"].get("direct_only"))
        self.assertTrue(any("Direct" in line for line in r["reasons"]))
        self.assertTrue(any("Google Flights" in line for line in r["reasons"]))

    def test_ticket_rationale_marks_pick_tag(self):
        from tools._rationale import build_ticket_rationale

        tickets = [
            {"name": "GA", "price": 195, "currency": "EUR", "section": "Free roaming", "tag": "VALUE"},
            {
                "name": "Tribuna 25",
                "price": 380,
                "currency": "EUR",
                "section": "T2 braking zone",
                "tag": "PICK",
                "provider": "Formula 1",
            },
            {"name": "Main Grandstand", "price": 620, "currency": "EUR", "section": "Pit lane + podium", "tag": "VIP"},
        ]
        r = build_ticket_rationale(tickets[1], tickets, _state())

        self.assertEqual(r["card_type"], "ticket")
        self.assertTrue(any("PICK" in line for line in r["reasons"]))
        self.assertTrue(any("T2 braking zone" in line for line in r["reasons"]))

    def test_trade_offs_bounded_to_three(self):
        from tools._rationale import build_hotel_rationale

        primary = {
            "name": "Hotel A",
            "price_per_night": 150,
            "currency": "EUR",
            "nights": 3,
            "distance": "5 km",
        }
        alternatives = [primary] + [
            {
                "name": f"Hotel {chr(ord('B') + i)}",
                "price_per_night": 100 + i * 20,
                "currency": "EUR",
                "nights": 3,
                "distance": f"{6 + i} km",
            }
            for i in range(5)
        ]
        r = build_hotel_rationale(primary, alternatives, _state())
        self.assertGreaterEqual(len(r["trade_offs"]), 1)
        self.assertLessEqual(len(r["trade_offs"]), 3)
        for entry in r["trade_offs"]:
            self.assertIn("against", entry)
            self.assertIn("advantage", entry)
            self.assertIn("cost", entry)

    def test_mock_path_is_source_path_not_attempt_log(self):
        from tools._rationale import build_flight_rationale, build_hotel_rationale, build_ticket_rationale

        hotel = {"name": "Mock H", "price_per_night": 80, "currency": "EUR", "nights": 3}
        r = build_hotel_rationale(hotel, [hotel], _state())
        self.assertEqual(r["source"], "mock")
        self.assertEqual(r["fallback_chain"], ["serpapi", "llm_estimate", "mock"])
        self.assertIn("inferred from the final card source", r["source_path_note"])

        flight = {"tag": "OUT", "summary": "A->B", "detail": "Direct", "price": 300, "currency": "EUR", "stops": 0}
        rf = build_flight_rationale(flight, [flight], _state())
        self.assertEqual(rf["fallback_chain"], ["serpapi", "llm_estimate", "mock"])

        ticket = {"name": "GA", "price": 100, "currency": "EUR", "tag": "VALUE", "section": "Free"}
        rt = build_ticket_rationale(ticket, [ticket], _state())
        self.assertEqual(rt["fallback_chain"], ["firecrawl", "llm_estimate", "mock"])

    def test_empty_alternatives_and_missing_fields_no_crash(self):
        from tools._rationale import build_flight_rationale, build_hotel_rationale, build_tour_rationale

        h = {"name": "Solo Hotel", "price_per_night": 0, "currency": "EUR"}
        r = build_hotel_rationale(h, [], _state())
        self.assertEqual(r["trade_offs"], [])
        self.assertIsInstance(r["reasons"], list)

        f = {"tag": "ROUNDTRIP", "summary": "", "detail": "", "price": 0, "currency": "EUR"}
        rf = build_flight_rationale(f, [], _state())
        self.assertEqual(rf["card_type"], "flight")

        rt = build_tour_rationale("Monza Museum (EUR 15)", ["Duomo (EUR 14)"], _state())
        self.assertEqual(rt["card_type"], "tour")
        self.assertEqual(rt["fallback_chain"], ["llm"])

    def test_llm_estimate_intermediate_source_path(self):
        from tools._rationale import build_flight_rationale, build_hotel_rationale

        hotel = {
            "name": "Estimated Stay",
            "price_per_night": 110,
            "currency": "EUR",
            "nights": 4,
            "_source": "llm_estimate",
        }
        r = build_hotel_rationale(hotel, [hotel], _state())
        self.assertEqual(r["source"], "llm_estimate")
        self.assertEqual(r["fallback_chain"], ["serpapi", "llm_estimate"])

        flight = {
            "tag": "OUT",
            "summary": "A->B",
            "detail": "Estimated",
            "price": 400,
            "currency": "EUR",
            "_source": "llm_estimate",
        }
        rf = build_flight_rationale(flight, [flight], _state())
        self.assertEqual(rf["fallback_chain"], ["serpapi", "llm_estimate"])

    def test_agent_attaches_rationale_to_cards(self):
        from agents import hotel_agent, ticket_agent, transport_agent

        state = _state()
        with unittest.mock.patch.dict(
            os.environ,
            {
                "SERPAPI_API_KEY": "",
                "FIRECRAWL_API_KEY": "",
                "OPENAI_API_KEY": "",
                "ANTHROPIC_API_KEY": "",
            },
            clear=False,
        ):
            tickets = ticket_agent({**state, "gp_name": "Italian GP"})
            hotels = hotel_agent({**state, "gp_city": "Monza", "extra_days": 2, "retry_count": 0})
            transport = transport_agent({**state, "origin": "New York", "gp_city": "Monza", "extra_days": 2, "stops": ""})

        for ticket in tickets["tickets"]:
            self.assertIn("_rationale", ticket)
            self.assertEqual(ticket["_rationale"]["card_type"], "ticket")
        for hotel in hotels["hotel"]:
            self.assertIn("_rationale", hotel)
            self.assertEqual(hotel["_rationale"]["card_type"], "hotel")
        flight_legs = [leg for leg in transport["transport"] if leg.get("tag") in {"ROUNDTRIP", "OUT", "RET"}]
        self.assertTrue(flight_legs, "expected at least one flight leg in mock transport")
        for leg in flight_legs:
            self.assertIn("_rationale", leg)
            self.assertEqual(leg["_rationale"]["card_type"], "flight")
        for leg in transport["transport"]:
            if leg.get("tag") == "LOCAL":
                self.assertNotIn("_rationale", leg)


if __name__ == "__main__":
    unittest.main()
