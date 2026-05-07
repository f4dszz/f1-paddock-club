"""Tests for `backend/tools/_links.py` — F1 Paddock Club URL normalizer.

Verifies the project-specific config produces the right NormalizedLink
shape for the URLs each search_*.py actually emits today, plus the
expected behavior for empty/malformed input.

Run:
    cd backend && python -m pytest tests/test_links.py -v
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class GoogleFlightsTests(unittest.TestCase):
    """SerpAPI Google Flights URL: looks like a deeplink, is actually a search."""

    def test_bare_flights_url_is_search_medium(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.google.com/travel/flights",
            "google_flights",
        )
        # Bare /travel/flights with no path beyond it → homepage
        # since it matches search_pattern but path is "/travel/flights"
        # which is a search root. Either "search" or "homepage" is
        # acceptable; we check it's not "deeplink" (the lying case).
        self.assertNotEqual(result["link_type"], "deeplink")
        self.assertIn(result["booking_confidence"], {"low", "medium"})

    def test_flights_with_tfs_param_is_search_not_deeplink(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.google.com/travel/flights?tfs=CBwQAhom&hl=en",
            "google_flights",
        )
        self.assertEqual(result["link_type"], "search")
        self.assertEqual(result["booking_confidence"], "medium")
        # Essential params survive.
        self.assertIn("tfs=", result["url"])

    def test_booked_path_is_deeplink_high(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.google.com/travel/flights/booked?tfs=abc",
            "google_flights",
        )
        self.assertEqual(result["link_type"], "deeplink")
        self.assertEqual(result["booking_confidence"], "high")


class BookingComTests(unittest.TestCase):

    def test_hotel_path_is_deeplink_high(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.booking.com/hotel/it/foo.html?aid=12345&label=cpc",
            "booking_com",
        )
        self.assertEqual(result["link_type"], "deeplink")
        self.assertEqual(result["booking_confidence"], "high")
        # Affiliate IDs preserved.
        self.assertIn("aid=12345", result["url"])
        self.assertIn("label=cpc", result["url"])

    def test_searchresults_is_search_medium(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.booking.com/searchresults.html?city=Milan",
            "booking_com",
        )
        self.assertEqual(result["link_type"], "search")
        self.assertEqual(result["booking_confidence"], "medium")

    def test_strips_utm_keeps_aid(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.booking.com/hotel/it/foo.html"
            "?utm_source=ig&utm_medium=cpc&fbclid=ABC&aid=99",
            "booking_com",
        )
        self.assertNotIn("utm_source", result["url"])
        self.assertNotIn("utm_medium", result["url"])
        self.assertNotIn("fbclid", result["url"])
        self.assertIn("aid=99", result["url"])


class HomepageFallbackTests(unittest.TestCase):

    def test_empty_url_falls_back_to_homepage(self):
        from tools._links import normalize_link, PROVIDER_HOMEPAGES
        result = normalize_link("", "booking_com")
        self.assertEqual(result["link_type"], "homepage")
        self.assertEqual(result["booking_confidence"], "low")
        self.assertEqual(result["url"], PROVIDER_HOMEPAGES["booking_com"])

    def test_malformed_url_falls_back(self):
        from tools._links import normalize_link
        result = normalize_link("not-a-url", "google_flights")
        self.assertEqual(result["link_type"], "homepage")
        self.assertEqual(result["booking_confidence"], "low")

    def test_javascript_scheme_falls_back(self):
        from tools._links import normalize_link
        result = normalize_link("javascript:alert(1)", "booking_com")
        self.assertEqual(result["link_type"], "homepage")
        self.assertNotIn("javascript", result["url"])

    def test_wrong_host_for_provider_falls_back_to_homepage(self):
        from tools._links import normalize_link, PROVIDER_HOMEPAGES
        # Caller claims it's booking.com but URL is somewhere else.
        result = normalize_link(
            "https://evil.example.com/hotel/it/foo.html",
            "booking_com",
        )
        self.assertEqual(result["link_type"], "homepage")
        self.assertEqual(result["url"], PROVIDER_HOMEPAGES["booking_com"])


class F1OfficialTests(unittest.TestCase):

    def test_racing_year_path_is_deeplink(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.formula1.com/en/racing/2026/monaco/tickets",
            "f1_official",
        )
        self.assertEqual(result["link_type"], "deeplink")
        self.assertEqual(result["booking_confidence"], "high")

    def test_tickets_subdomain_search(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://tickets.formula1.com/en",
            "f1_official",
        )
        # "/en" matches search_patterns -> classified as search.
        # Either way it's not deeplink, which is the bar.
        self.assertNotEqual(result["link_type"], "deeplink")


class GoogleMapsTests(unittest.TestCase):

    def test_maps_place_is_deeplink(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.google.com/maps/place/Hotel+de+Russie/@41.9,12.5,17z",
            "google_maps",
        )
        self.assertEqual(result["link_type"], "deeplink")
        self.assertEqual(result["booking_confidence"], "high")

    def test_maps_search_is_search(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.google.com/maps/search/hotels+near+monza",
            "google_maps",
        )
        self.assertEqual(result["link_type"], "search")

    def test_hotel_website_is_medium_confidence_external_site(self):
        from tools.search_hotels import _try_serpapi_google_maps_hotels

        class FakeGoogleSearch:
            def __init__(self, _params):
                pass

            def get_dict(self):
                return {
                    "local_results": [{
                        "title": "Independent Monza Hotel",
                        "price": "€180",
                        "rating": 4.4,
                        "address": "Monza",
                        "website": "https://hotel.example.com/book",
                    }]
                }

        fake_serpapi = types.SimpleNamespace(GoogleSearch=FakeGoogleSearch)
        with patch.dict(sys.modules, {"serpapi": fake_serpapi}), \
             patch.dict("os.environ", {"SERPAPI_API_KEY": "test"}, clear=False):
            result = _try_serpapi_google_maps_hotels("Monza", None, None, None, "test")

        self.assertEqual(result[0]["link_type"], "homepage")
        self.assertEqual(result[0]["booking_confidence"], "medium")


class UnknownProviderTests(unittest.TestCase):

    def test_unknown_provider_is_low_confidence_homepage(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://example.com/foo",
            "no_such_provider",
        )
        self.assertEqual(result["link_type"], "homepage")
        self.assertEqual(result["booking_confidence"], "low")


class FallbackForTests(unittest.TestCase):

    def test_known_provider_returns_homepage(self):
        from tools._links import fallback_for
        self.assertEqual(
            fallback_for("booking_com"),
            "https://www.booking.com/",
        )

    def test_unknown_provider_returns_empty(self):
        from tools._links import fallback_for
        self.assertEqual(fallback_for("nope"), "")


class ContractShapeTests(unittest.TestCase):
    """The dict shape is what state.py / search_*.py rely on."""

    def test_returns_three_canonical_keys(self):
        from tools._links import normalize_link
        result = normalize_link(
            "https://www.booking.com/hotel/it/foo.html",
            "booking_com",
        )
        self.assertEqual(
            set(result.keys()),
            {"url", "link_type", "booking_confidence"},
        )


if __name__ == "__main__":
    unittest.main()
