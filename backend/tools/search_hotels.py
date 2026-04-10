"""Search for hotel options via SerpAPI Google Hotels (+ Bing parallel).

Same data flow pattern as search_flights:
    1. Parallel: google_hotels + bing (both via SerpAPI)
    2. LLM estimation fallback
    3. Raise → agent mock

WHY google_hotels engine specifically?
SerpAPI's google_hotels engine returns structured data: property name,
price, rating, GPS coords, amenities, images. This is MUCH richer
than scraping a booking page. For Chinese routes, Bing supplements
with local OTA results that Google Hotels might miss.

TTL: 3 hours.
"""

from __future__ import annotations
import logging
import os
from pydantic import BaseModel, Field

from ._cache import cached
from ._parallel import query_parallel
from ._date_util import normalize_date, compute_checkout

logger = logging.getLogger(__name__)

_TTL = 3 * 3600  # 3 hours


class HotelEstimate(BaseModel):
    hotels: list[dict] = Field(
        description=(
            "List of hotel options. Each dict: name, price_per_night (float), "
            "total_price (float), currency (EUR), nights (int), distance (str), "
            "rating (str like '8.5'), tag (NEAR/SAVE/BUDGET/LUXURY), "
            "link (booking URL)."
        )
    )


def _try_serpapi_google_hotels(
    city: str, checkin: str, checkout: str,
    brand: str | None, stars: int | None, max_price: float | None,
    near: str | None, excluded_ids: list[str] | None, api_key: str,
) -> list[dict]:
    from serpapi import GoogleSearch

    query = f"hotels in {city}"
    if brand:
        query += f" {brand}"
    if near:
        query += f" near {near}"

    checkin_iso = normalize_date(checkin)
    checkout_iso = normalize_date(checkout) if checkout else compute_checkout(checkin, 5)

    params = {
        "engine": "google_hotels",
        "q": query,
        "check_in_date": checkin_iso,
        "check_out_date": checkout_iso,
        "api_key": api_key,
    }
    if stars:
        params["hotel_class"] = str(stars)

    raw = GoogleSearch(params).get_dict()
    properties = raw.get("properties", [])

    results = []
    excluded = set(excluded_ids or [])

    for p in properties[:8]:
        hotel_id = p.get("name", "")
        if hotel_id in excluded:
            continue

        rate = p.get("rate_per_night", {})
        price_str = rate.get("lowest", "0")
        # Parse "$123" or "€123" into float
        price_per_night = float("".join(c for c in price_str if c.isdigit() or c == ".") or "0")

        nights = p.get("total_rate", {}).get("nights", 1) or 1
        total = price_per_night * nights

        if max_price and total > max_price:
            continue

        results.append({
            "name": p.get("name", "Unknown Hotel"),
            "price_per_night": price_per_night,
            "total_price": total,
            "currency": "USD",
            "nights": nights,
            "distance": p.get("nearby_places", [{}])[0].get("name", "") if p.get("nearby_places") else "",
            "rating": str(p.get("overall_rating", "")),
            "tag": _classify_hotel(price_per_night, p.get("overall_rating", 0)),
            "link": p.get("link", "https://www.booking.com"),
        })

    return results[:5]


def _classify_hotel(price: float, rating) -> str:
    """Assign a display tag based on price/rating heuristics."""
    try:
        r = float(rating)
    except (ValueError, TypeError):
        r = 0
    if price < 80:
        return "BUDGET"
    if price > 250:
        return "LUXURY"
    if r >= 8.5:
        return "TOP"
    return "NEAR"


def _try_serpapi_bing_hotels(city: str, checkin: str, api_key: str) -> list[dict]:
    from serpapi import GoogleSearch

    params = {
        "engine": "bing",
        "q": f"hotels in {city} {checkin} booking prices",
        "api_key": api_key,
    }
    raw = GoogleSearch(params).get_dict()

    results = []
    for r in (raw.get("organic_results") or [])[:3]:
        snippet = r.get("snippet", "")
        if snippet:
            results.append({
                "name": r.get("title", "")[:80],
                "price_per_night": 0,
                "total_price": 0,
                "currency": "USD",
                "nights": 0,
                "distance": "",
                "rating": "",
                "tag": "INFO",
                "link": r.get("link", ""),
                "detail": snippet[:150],
            })
    return results


def _try_llm_estimate(
    city: str, checkin: str, checkout: str,
    brand: str | None, stars: int | None, max_price: float | None,
) -> list[dict]:
    try:
        from llm import get_llm
        llm = get_llm(temperature=0.3, max_tokens=800)
        if llm is None:
            return []
    except Exception:
        return []

    constraints = []
    if brand:
        constraints.append(f"Brand preference: {brand}")
    if stars:
        constraints.append(f"Minimum {stars} stars")
    if max_price:
        constraints.append(f"Max total price: ${max_price}")

    prompt = (
        f"Estimate 2-3 realistic hotel options in {city} "
        f"for check-in {checkin}, check-out {checkout}. "
        f"Use real hotel names from that city. "
        f"{'Constraints: ' + '; '.join(constraints) if constraints else ''}"
    )

    try:
        structured = llm.with_structured_output(HotelEstimate)
        result = structured.invoke([
            ("system", "You are a hotel pricing expert. Return realistic estimates with real property names."),
            ("user", prompt),
        ])

        hotels = result.hotels if result.hotels else []
        for h in hotels:
            h["_source"] = "llm_estimate"
            h["_degraded"] = True
        return hotels
    except Exception:
        logger.exception("LLM hotel estimation failed")
        return []


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
) -> tuple[list[dict], str]:
    """Search for hotels. Returns (results, degradation_summary)."""
    api_key = os.environ.get("SERPAPI_API_KEY")

    # ── Layer 1: Parallel real sources ───────────────────────────
    if api_key:
        sources = {
            "google_hotels": lambda: _try_serpapi_google_hotels(
                city, checkin, checkout, brand, stars, max_price,
                near, excluded_ids, api_key,
            ),
            "bing": lambda: _try_serpapi_bing_hotels(city, checkin, api_key),
        }

        results, report = query_parallel(sources, timeout=20)

        if results:
            logger.info("search_hotels: parallel success — %s", report.summary())
            degradation_msg = ""
            if report.any_failed:
                degradation_msg = f" (partial: {', '.join(report.failed)} failed)"
            return results, f"sources: {', '.join(report.succeeded)}{degradation_msg}"

        logger.warning("search_hotels: all parallel sources failed — %s", report.summary())

    # ── Layer 2: LLM estimation ──────────────────────────────────
    logger.info("search_hotels: trying LLM estimation fallback")
    llm_results = _try_llm_estimate(city, checkin, checkout, brand, stars, max_price)
    if llm_results:
        return llm_results, "source: llm_estimate (real-time data unavailable)"

    # ── Layer 3: Everything failed ───────────────────────────────
    raise RuntimeError(f"All hotel data sources exhausted for {city}")
