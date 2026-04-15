"""Search for hotel options via SerpAPI (Google Hotels + Google Maps parallel).

Data flow:
    1. Parallel: google_hotels + google_maps (both via SerpAPI)
    2. LLM estimation fallback
    3. Raise → agent mock

google_hotels returns booking-oriented data (prices, availability).
Google Maps returns location-oriented data (ratings, addresses, reviews).
Together they give a complete picture.

TTL: 3 hours.
"""

from __future__ import annotations
import json
import logging
import os
import re
from pydantic import BaseModel, Field

from ._cache import cached
from ._parallel import query_parallel
from ._date_util import normalize_date, compute_checkout

logger = logging.getLogger(__name__)

_TTL = 3 * 3600  # 3 hours

_HOTEL_LOCATION_ALIASES: dict[str, set[str]] = {
    "monza": {"monza", "milan", "brianza"},
    "monaco": {"monaco", "monte", "carlo", "nice"},
    "silverstone": {"silverstone", "northampton", "towcester", "milton", "keynes"},
    "spa": {"spa", "stavelot", "francorchamps", "liege", "liège", "brussels"},
    "imola": {"imola", "bologna"},
    "zandvoort": {"zandvoort", "amsterdam", "haarlem"},
    "interlagos": {"interlagos", "sao", "paulo"},
    "las vegas": {"las", "vegas"},
    "abu dhabi": {"abu", "dhabi", "yas"},
    "miami": {"miami", "gardens"},
    "suzuka": {"suzuka", "nagoya"},
}


def _location_tokens(city: str, near: str | None = None) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", city.lower())
        if len(token) >= 3
    }
    tokens |= _HOTEL_LOCATION_ALIASES.get(city.lower(), set())
    if near:
        tokens |= {
            token
            for token in re.findall(r"[a-z0-9]+", near.lower())
            if len(token) >= 4 and token not in {"hotel", "hotels", "circuit"}
        }
    return tokens


def _filter_location_relevant_hotels(results: list[dict], city: str, near: str | None = None) -> list[dict]:
    tokens = _location_tokens(city, near)
    if not tokens:
        return results

    filtered: list[dict] = []
    for item in results:
        text = " ".join(
            str(item.get(key, ""))
            for key in ("name", "distance", "link")
        ).lower()
        if any(token in text for token in tokens):
            filtered.append(item)

    if filtered or not results:
        return filtered

    logger.warning(
        "search_hotels: filtered out %d location-mismatched results for city=%s",
        len(results),
        city,
    )
    return []


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


def _try_serpapi_google_maps_hotels(
    city: str, near: str | None, brand: str | None,
    stars: int | None, api_key: str,
) -> list[dict]:
    """WHY Google Maps as second source for hotels?
    google_hotels returns booking-oriented data (prices, availability).
    Google Maps returns LOCATION-oriented data (rating, distance,
    real photos, verified reviews). Together they give a complete
    picture. Also, Google Maps works even when google_hotels can't
    find results for a small city — Maps always has local business data.
    """
    from serpapi import GoogleSearch

    query = f"hotels in {city}"
    if brand:
        query += f" {brand}"
    if near:
        query += f" near {near}"

    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "api_key": api_key,
    }
    raw = GoogleSearch(params).get_dict()

    results = []
    for p in (raw.get("local_results") or [])[:6]:
        price_str = p.get("price", "")
        # Parse "$84" or "€84" into float
        price_num = float("".join(c for c in str(price_str) if c.isdigit() or c == ".") or "0")

        rating = p.get("rating", 0)
        try:
            star_rating = float(rating)
        except (ValueError, TypeError):
            star_rating = 0

        if stars and star_rating < stars:
            continue

        results.append({
            "name": p.get("title", "Unknown Hotel"),
            "price_per_night": price_num,
            "total_price": 0,  # Will be computed by recompute_budget
            "currency": "USD",
            "nights": 0,
            "distance": p.get("address", ""),
            "rating": str(rating),
            "tag": _classify_hotel(price_num, rating),
            "link": p.get("website", p.get("link", "")),
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
    except Exception:
        logger.warning("structured_output failed for hotel estimate, trying raw JSON")
        try:
            raw_response = llm.invoke([
                ("system", "You are a hotel pricing expert. Return ONLY valid JSON, no other text."),
                ("user", prompt + "\n\nReturn JSON: {\"hotels\": [{\"name\": str, \"price_per_night\": float, \"total_price\": float, \"currency\": \"USD\"|\"EUR\", \"nights\": int, \"distance\": str, \"rating\": str, \"tag\": str, \"link\": str}]}")
            ])
            text = raw_response.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(text)
            hotels = parsed.get("hotels", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(hotels, list):
                hotels = []
        except Exception:
            logger.exception("LLM hotel estimation failed (both methods)")
            return []

    for hotel in hotels:
        if isinstance(hotel, dict):
            hotel["_source"] = "llm_estimate"
            hotel["_degraded"] = True
    return [hotel for hotel in hotels if isinstance(hotel, dict)]


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
            "google_maps": lambda: _try_serpapi_google_maps_hotels(
                city, near, brand, stars, api_key,
            ),
        }

        results, report = query_parallel(sources, timeout=20)
        results = [item for item in results if isinstance(item, dict)]
        results = _filter_location_relevant_hotels(results, city, near)

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
