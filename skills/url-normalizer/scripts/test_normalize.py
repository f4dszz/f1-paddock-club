"""Tests for the abstract URL normalizer reference implementation.

Covers the contract callers depend on:
- deeplink detection (host + path pattern -> high confidence)
- search-page detection (host + search pattern -> medium confidence)
- homepage fallback for empty / malformed / unknown-host URLs
- tracking-param stripping (UTM family, fbclid, etc.)
- essential-param preservation (affiliate IDs, search anchors)
- unknown provider -> low confidence, no exceptions

Sample configs in this file are illustrative — real callers vendor their
own.

Run:
    cd skills/url-normalizer/scripts && python test_normalize.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from normalize import (  # noqa: E402
    DEFAULT_TRACKING_BLOCKLIST,
    normalize,
)


# Illustrative provider config — callers ship their own.
SAMPLE_CONFIG: dict = {
    "booking_com": {
        "homepage": "https://www.booking.com/",
        "hosts": ["booking.com", "www.booking.com"],
        "deeplink_patterns": [r"^/hotel/"],
        "search_patterns": [r"^/searchresults"],
        "essential_params": ["aid", "label", "checkin", "checkout"],
    },
    "google_flights": {
        "homepage": "https://www.google.com/travel/flights",
        "hosts": ["google.com", "www.google.com"],
        "deeplink_patterns": [r"^/travel/flights/booked"],
        "search_patterns": [r"^/travel/flights"],
        "essential_params": ["tfs", "hl", "curr"],
    },
    "google_maps": {
        "homepage": "https://www.google.com/maps",
        "hosts": ["google.com", "www.google.com", "maps.google.com"],
        "deeplink_patterns": [r"^/maps/place/"],
        "search_patterns": [r"^/maps/search"],
        "essential_params": ["q"],
    },
}


# ── Deeplink detection ─────────────────────────────────────────────

def test_booking_hotel_path_is_deeplink_high_confidence():
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?aid=12345",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "deeplink"
    assert result["confidence"] == "high"
    assert "aid=12345" in result["url"]


def test_google_flights_booked_path_is_deeplink():
    result = normalize(
        "https://www.google.com/travel/flights/booked?tfs=abc",
        "google_flights",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "deeplink"
    assert result["confidence"] == "high"


# ── Search-page detection ──────────────────────────────────────────

def test_google_flights_search_page_is_search_medium_confidence():
    # Google Flights "search" URLs look like deeplinks but resolve to a
    # search results page, not a booking page.
    result = normalize(
        "https://www.google.com/travel/flights?tfs=CBwQAhom",
        "google_flights",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "search"
    assert result["confidence"] == "medium"


def test_booking_searchresults_path_is_search():
    result = normalize(
        "https://www.booking.com/searchresults.html?city=Milan",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "search"
    assert result["confidence"] == "medium"


# ── Homepage fallback ──────────────────────────────────────────────

def test_empty_url_falls_back_to_homepage():
    result = normalize("", "booking_com", SAMPLE_CONFIG)
    assert result["link_type"] == "homepage"
    assert result["confidence"] == "low"
    assert result["url"] == "https://www.booking.com/"


def test_malformed_url_falls_back_to_homepage():
    result = normalize("not a url at all", "booking_com", SAMPLE_CONFIG)
    assert result["link_type"] == "homepage"
    assert result["confidence"] == "low"


def test_non_http_scheme_falls_back_to_homepage():
    result = normalize(
        "javascript:alert(1)", "booking_com", SAMPLE_CONFIG
    )
    assert result["link_type"] == "homepage"
    assert result["confidence"] == "low"
    # Must not propagate the dangerous scheme.
    assert "javascript" not in result["url"]


def test_wrong_host_for_provider_falls_back_to_homepage():
    # Caller asks us to normalize a URL claiming to be Booking.com but
    # actually pointing at a different host. We don't trust the caller —
    # fall back to the configured homepage.
    result = normalize(
        "https://evil.example.com/hotel/it/foo.html",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "homepage"
    assert result["url"] == "https://www.booking.com/"


def test_root_path_with_known_host_is_homepage():
    result = normalize(
        "https://www.booking.com/",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "homepage"


# ── Tracking-param stripping ───────────────────────────────────────

def test_strips_utm_params():
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?utm_source=ig&utm_medium=cpc&aid=99",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert "utm_source" not in result["url"]
    assert "utm_medium" not in result["url"]
    assert "aid=99" in result["url"]


def test_strips_fbclid_and_gclid():
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?fbclid=XYZ&gclid=ABC&aid=1",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert "fbclid" not in result["url"]
    assert "gclid" not in result["url"]
    assert "aid=1" in result["url"]


def test_preserves_essential_affiliate_params():
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?aid=12345&label=cpc&checkin=2026-09-04",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert "aid=12345" in result["url"]
    assert "label=cpc" in result["url"]
    assert "checkin=2026-09-04" in result["url"]


def test_preserves_unknown_params_conservatively():
    # A param that's neither in the blocklist nor the essential list
    # should be preserved — we don't know what it does.
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?weirdkey=42",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert "weirdkey=42" in result["url"]


def test_drops_fragment():
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?aid=1#room-2",
        "booking_com",
        SAMPLE_CONFIG,
    )
    assert "#" not in result["url"]
    assert "room-2" not in result["url"]


# ── Unknown provider handling ──────────────────────────────────────

def test_unknown_provider_returns_low_confidence_homepage():
    result = normalize(
        "https://example.com/foo",
        "no_such_provider",
        SAMPLE_CONFIG,
    )
    assert result["link_type"] == "homepage"
    assert result["confidence"] == "low"
    # We hand the URL back unchanged so the caller can decide what to do.
    assert result["url"] == "https://example.com/foo"


def test_provider_config_missing_keys_does_not_raise():
    # Provider exists but is missing fields — shouldn't blow up.
    config = {"sparse": {"hosts": ["sparse.example.com"]}}  # no homepage etc.
    result = normalize(
        "https://sparse.example.com/x?utm_source=a",
        "sparse",
        config,
    )
    assert isinstance(result, dict)
    assert "link_type" in result


# ── Subdomain host matching ────────────────────────────────────────

def test_subdomain_matches_configured_host():
    result = normalize(
        "https://m.booking.com/hotel/it/foo.html",
        "booking_com",
        SAMPLE_CONFIG,
    )
    # m.booking.com is a subdomain of booking.com -> should match.
    assert result["link_type"] == "deeplink"


# ── DEFAULT_TRACKING_BLOCKLIST sanity ──────────────────────────────

def test_default_blocklist_covers_common_trackers():
    expected = {"utm_source", "utm_medium", "fbclid", "gclid"}
    assert expected.issubset(DEFAULT_TRACKING_BLOCKLIST)


def test_caller_can_override_blocklist():
    custom = {"aid"}  # weird config that strips affiliate IDs
    result = normalize(
        "https://www.booking.com/hotel/it/foo.html?aid=1&utm_source=x",
        "booking_com",
        SAMPLE_CONFIG,
        tracking_blocklist=custom,
    )
    # aid is essential, so it survives even when blocked globally.
    assert "aid=1" in result["url"]
    # utm_source isn't in the custom blocklist now -> survives too.
    assert "utm_source=x" in result["url"]


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:  # pragma: no cover - exercised by failures
            failures += 1
            print(f"FAIL {name}: {exc}", file=sys.stderr)
        else:
            print(f"PASS {name}")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
