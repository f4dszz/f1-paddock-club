"""Search for flight options via SerpAPI Google Flights engine.

Phase 3.0: skeleton with mock return (raises NotImplementedError
so the calling agent falls back to its own mock). Once SerpAPI key
is configured, fill in the TODO section.

TTL: 3 hours — flight prices are volatile intraday.

Usage:
    from tools.search_flights import search_flights
    legs = search_flights("New York", "Milan", "2026-09-05")
"""

from __future__ import annotations
import logging
import os

from ._cache import cached

logger = logging.getLogger(__name__)

_TTL = 3 * 3600  # 3 hours


@cached(ttl=_TTL)
def search_flights(
    origin: str,
    dest: str,
    date: str,
    return_date: str | None = None,
    stops: int | None = None,
    cabin: str | None = None,
) -> list[dict]:
    """Search for flights and return a list of TransportLeg-shaped dicts.

    Args:
        origin: Departure city or airport code (e.g. "New York" or "JFK")
        dest: Arrival city or airport code
        date: Outbound date, ISO format preferred
        return_date: Optional return date for round-trip
        stops: Max number of stops (0 = direct only). None = any.
        cabin: "economy" | "business" | "first" | None

    Returns:
        List of dicts matching the TransportLeg shape:
        [{"tag": "OUT"|"RET"|"LOCAL", "summary": str, "detail": str,
          "price": float, "currency": str, "link": str}]

    Raises:
        NotImplementedError: when SERPAPI_API_KEY is not set (Phase 3.0).
        Exception: on API errors (caller should catch and fall back).
    """
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise NotImplementedError(
            "SERPAPI_API_KEY not set — flight search unavailable, "
            "agent should fall back to mock data"
        )

    # ── TODO (Phase 3.2): real SerpAPI call ──────────────────────
    #
    # from serpapi import GoogleSearch
    # params = {
    #     "engine": "google_flights",
    #     "departure_id": origin,
    #     "arrival_id": dest,
    #     "outbound_date": date,
    #     "return_date": return_date or "",
    #     "stops": stops,
    #     "travel_class": {"economy": 1, "business": 2, "first": 3}.get(cabin, 1),
    #     "api_key": api_key,
    # }
    # raw = GoogleSearch(params).get_dict()
    #
    # Then normalize raw["best_flights"] + raw["other_flights"] into
    # our TransportLeg shape and return.
    # ─────────────────────────────────────────────────────────────

    raise NotImplementedError("SerpAPI flight search not yet wired")
