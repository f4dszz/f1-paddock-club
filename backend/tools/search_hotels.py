"""Search for hotel options via SerpAPI Google Hotels engine.

Phase 3.0: skeleton — raises NotImplementedError so the calling agent
falls back to its own mock. Fill in the TODO once SerpAPI key is ready.

TTL: 3 hours — hotel prices shift but not minute-by-minute.

Usage:
    from tools.search_hotels import search_hotels
    options = search_hotels("Monza", "2026-09-04", "2026-09-09")
"""

from __future__ import annotations
import logging
import os

from ._cache import cached

logger = logging.getLogger(__name__)

_TTL = 3 * 3600  # 3 hours


@cached(ttl=_TTL)
def search_hotels(
    city: str,
    checkin: str,
    checkout: str,
    brand: str | None = None,
    stars: int | None = None,
    max_price: float | None = None,
    near: str | None = None,
    excluded_ids: list[str] | None = None,
) -> list[dict]:
    """Search for hotels and return a list of HotelOption-shaped dicts.

    Args:
        city: City name (e.g. "Monza")
        checkin / checkout: Date strings, ISO format preferred
        brand: Filter by brand name (e.g. "Marriott", "Hilton"). None = any.
        stars: Minimum star rating (1-5). None = any.
        max_price: Maximum total price in EUR. None = no limit.
        near: Landmark or address to prefer proximity to (e.g. "Autodromo").
        excluded_ids: Hotel IDs to skip (for "show me different ones" refinement).

    Returns:
        List of dicts matching the HotelOption shape:
        [{"name": str, "price_per_night": float, "total_price": float,
          "currency": str, "nights": int, "distance": str,
          "rating": str, "tag": str, "link": str}]

    Raises:
        NotImplementedError: when SERPAPI_API_KEY not set.
    """
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise NotImplementedError(
            "SERPAPI_API_KEY not set — hotel search unavailable, "
            "agent should fall back to mock data"
        )

    # ── TODO (Phase 3.2): real SerpAPI call ──────────────────────
    #
    # from serpapi import GoogleSearch
    # params = {
    #     "engine": "google_hotels",
    #     "q": f"hotels in {city}" + (f" {brand}" if brand else ""),
    #     "check_in_date": checkin,
    #     "check_out_date": checkout,
    #     "min_rating": stars * 2 if stars else None,  # Google uses 1-10
    #     "max_price": max_price,
    #     "api_key": api_key,
    # }
    # raw = GoogleSearch(params).get_dict()
    #
    # Then normalize raw["properties"] into our HotelOption shape.
    # Filter out any hotel whose id is in excluded_ids.
    # If `near` is set, sort by distance to that landmark.
    # ─────────────────────────────────────────────────────────────

    raise NotImplementedError("SerpAPI hotel search not yet wired")
