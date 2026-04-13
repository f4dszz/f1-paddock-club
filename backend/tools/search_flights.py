"""Search for flight options via SerpAPI (multiple engines in parallel).

Data flow:
    1. Parallel query: google_flights + bing (if SERPAPI_API_KEY set)
    2. If parallel returns results → merge, deduplicate, cache, return
    3. If ALL parallel sources fail → try LLM estimation
    4. If LLM also fails → raise (agent falls back to mock)

Each result dict carries:
    _source:   "google_flights" | "bing" | "llm_estimate"
    _degraded: False (real data) | True (estimated)

TTL: 3 hours.

Teaching notes inline — search for "WHY:" comments.
"""

from __future__ import annotations
import json
import logging
import os
from pydantic import BaseModel, Field

from ._cache import cached
from ._parallel import query_parallel, DegradationReport
from ._date_util import normalize_date

logger = logging.getLogger(__name__)

_TTL = 3 * 3600  # 3 hours


# ── Pydantic schema for LLM estimation (structured output) ──────────

# ── City-to-IATA mapping (common F1 cities + major hubs) ─────────────
# WHY: SerpAPI's google_flights engine requires IATA airport codes,
# but users type city names ("New York", "Shanghai"). This mapping
# bridges the gap. If a city isn't here, we pass the raw string and
# hope SerpAPI can resolve it (sometimes it can).

_CITY_TO_IATA: dict[str, str] = {
    # Major departure cities
    "new york": "JFK", "nyc": "JFK", "los angeles": "LAX", "chicago": "ORD",
    "london": "LHR", "paris": "CDG", "tokyo": "NRT", "shanghai": "PVG",
    "beijing": "PEK", "sydney": "SYD", "dubai": "DXB", "singapore": "SIN",
    "hong kong": "HKG", "seoul": "ICN", "mumbai": "BOM", "toronto": "YYZ",
    "sao paulo": "GRU", "mexico city": "MEX", "berlin": "BER", "madrid": "MAD",
    "amsterdam": "AMS", "frankfurt": "FRA", "zurich": "ZRH", "istanbul": "IST",
    # F1 GP host cities / nearest airports
    "monza": "MXP", "milan": "MXP", "monaco": "NCE", "monte carlo": "NCE",
    "barcelona": "BCN", "montreal": "YUL", "spa": "BRU", "brussels": "BRU",
    "budapest": "BUD", "zandvoort": "AMS", "baku": "GYD", "jeddah": "JED",
    "bahrain": "BAH", "abu dhabi": "AUH", "austin": "AUS", "miami": "MIA",
    "las vegas": "LAS", "suzuka": "NGO", "melbourne": "MEL", "imola": "BLQ",
    "spielberg": "GRZ", "silverstone": "LHR", "interlagos": "GRU",
    "lusail": "DOH", "qatar": "DOH",
}


def _resolve_iata(city_or_code: str) -> str:
    """Convert a city name to IATA code, or pass through if already a code."""
    if len(city_or_code) == 3 and city_or_code.isupper():
        return city_or_code  # Already an IATA code
    return _CITY_TO_IATA.get(city_or_code.lower(), city_or_code)


class FlightEstimate(BaseModel):
    """WHY a Pydantic schema here?
    When we fall back to LLM estimation, we use with_structured_output()
    which needs a schema to guarantee the LLM returns data in the exact
    shape we expect. Without this, the LLM might return free-form text
    that we'd have to regex-parse — fragile and error-prone.
    """
    legs: list[dict] = Field(
        description=(
            "List of flight legs. Each dict must have: "
            "tag (OUT/RET/LOCAL), summary (route string), "
            "detail (duration + date), price (float), "
            "currency (EUR/USD), link (booking URL)."
        )
    )


# ── SerpAPI source: Google Flights engine ────────────────────────────

def _try_serpapi_google_flights(
    origin: str, dest: str, date: str, return_date: str | None,
    stops: int | None, cabin: str | None, api_key: str,
) -> list[dict]:
    """WHY a separate function per engine?
    Each SerpAPI engine has different parameter names and response
    shapes. Isolating them means changing Google Flights parsing
    doesn't risk breaking Bing parsing. Single Responsibility.

    When return_date is provided, searches round-trip (type=1).
    google_flights returns round-trip prices in this mode — the price
    per flight_group covers BOTH directions. We tag these as ROUNDTRIP
    so recompute_budget handles them correctly (total flight cost, not
    OUT + RET separately).
    """
    from serpapi import GoogleSearch

    is_roundtrip = bool(return_date)

    params = {
        "engine": "google_flights",
        "departure_id": _resolve_iata(origin),
        "arrival_id": _resolve_iata(dest),
        "outbound_date": normalize_date(date),
        "type": "1" if is_roundtrip else "2",
        "api_key": api_key,
    }
    if return_date:
        params["return_date"] = normalize_date(return_date)
    if stops is not None:
        params["stops"] = str(stops)
    if cabin:
        cabin_map = {"economy": "1", "premium_economy": "2", "business": "3", "first": "4"}
        params["travel_class"] = cabin_map.get(cabin, "1")

    raw = GoogleSearch(params).get_dict()

    results = []
    tag = "ROUNDTRIP" if is_roundtrip else "OUT"

    for flight_group in (raw.get("best_flights") or []) + (raw.get("other_flights") or []):
        flights_in_group = flight_group.get("flights", [])
        if not flights_in_group:
            continue

        first_leg = flights_in_group[0]
        last_leg = flights_in_group[-1]
        num_stops = len(flights_in_group) - 1
        duration = flight_group.get("total_duration", 0)
        price = flight_group.get("price", 0)

        detail_date = f"{date} → {return_date}" if is_roundtrip else date
        results.append({
            "tag": tag,
            "summary": f"{first_leg.get('departure_airport', {}).get('id', origin)} -> "
                       f"{last_leg.get('arrival_airport', {}).get('id', dest)}",
            "detail": f"{'Direct' if num_stops == 0 else f'{num_stops} stop(s)'} - "
                      f"{duration // 60}h{duration % 60:02d}m - {detail_date}",
            "price": float(price),
            "currency": "USD",
            "link": "https://www.google.com/travel/flights",
            "airline": first_leg.get("airline", ""),
        })

    return results[:6]


# ── SerpAPI source: Bing search engine (补充信息，中文友好) ────────────

def _try_serpapi_bing(
    origin: str, dest: str, date: str, api_key: str,
) -> list[dict]:
    """WHY Bing as a second source?
    Bing returns web results (not structured flight data), but its
    snippets often contain price ranges and airline names that
    Google Flights might miss — especially for Chinese airlines and
    routes. We extract structured data from snippets via simple parsing.
    """
    from serpapi import GoogleSearch

    query = f"flights {origin} to {dest} {date} price"
    params = {
        "engine": "bing",
        "q": query,
        "api_key": api_key,
    }
    raw = GoogleSearch(params).get_dict()
    organic = raw.get("organic_results", [])

    # WHY: we don't try to deeply parse Bing results into TransportLeg
    # shape. We extract what we can (title + snippet + link) and mark
    # them as supplementary info. The supervisor/frontend can show
    # these as "also found on web" links rather than structured cards.
    results = []
    for r in organic[:3]:
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        title = r.get("title", "")
        if snippet and link:
            results.append({
                "tag": "INFO",
                "summary": title[:80],
                "detail": snippet[:150],
                "price": 0,  # Can't reliably extract price from snippets
                "currency": "USD",
                "link": link,
            })

    return results


# ── SerpAPI source: Google Search (price snippets as cross-reference) ─

def _try_serpapi_google_search_flights(
    origin: str, dest: str, date: str, api_key: str,
) -> list[dict]:
    """WHY Google Search as second source for flights?
    Google Flights engine gives us structured data (airline, price, duration).
    Google Search gives us organic results with price RANGES ("from $234")
    and booking site links. These serve as cross-references: if Google
    Flights says $365 and Google Search says "from $234", the user gets
    a fuller picture. Also, if google_flights fails, these snippets
    are enough for the LLM estimation layer to work with.
    """
    from serpapi import GoogleSearch

    iata_origin = _resolve_iata(origin)
    iata_dest = _resolve_iata(dest)
    iso_date = normalize_date(date)

    # WHY this specific query formulation?
    # - "airline tickets" not "flights" → avoids flight simulator noise
    # - IATA codes → more precise than city names
    # - "airfare" → strong purchase-intent signal for search engines
    # - "one way price" → matches how Google shows fare snippets
    params = {
        "engine": "google",
        "q": f"airline tickets {iata_origin} to {iata_dest} {iso_date} airfare one way price",
        "api_key": api_key,
    }
    raw = GoogleSearch(params).get_dict()

    results = []
    for r in (raw.get("organic_results") or [])[:4]:
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        title = r.get("title", "")
        if snippet and link:
            results.append({
                "tag": "INFO",
                "summary": title[:80],
                "detail": snippet[:200],
                "price": 0,
                "currency": "USD",
                "link": link,
            })

    return results


# ── LLM estimation fallback ─────────────────────────────────────────

def _try_llm_estimate(
    origin: str, dest: str, date: str,
    stops: int | None, cabin: str | None,
) -> list[dict]:
    """WHY an LLM estimation layer between real APIs and mock?

    Mock data is hardcoded Italian GP data — it returns "NYC -> Monza"
    even if you're searching for "Shanghai -> Singapore". LLM estimation
    uses the model's training knowledge to generate CONTEXTUAL data:
    real airline names, realistic prices for that specific route, actual
    airport codes. It's not live data, but it's route-specific.

    The results are marked _degraded=True so the frontend can show
    "estimated prices — actual prices may differ".
    """
    # Lazy import to avoid circular dependency and to handle
    # the case where llm.py can't initialize (no LLM key).
    try:
        from llm import get_llm
        llm = get_llm(temperature=0.3, max_tokens=800)
        if llm is None:
            return []
    except Exception:
        return []

    prompt = (
        f"Estimate realistic flight options for {origin} to {dest} "
        f"around {date}. Return 2-3 options with real airline names, "
        f"approximate prices in USD, and realistic durations. "
        f"Include one outbound (tag=OUT) and one return (tag=RET) option."
        f"{f' Prefer direct flights (stops=0).' if stops == 0 else ''}"
        f"{f' Cabin class: {cabin}.' if cabin else ''}"
    )

    try:
        structured = llm.with_structured_output(FlightEstimate)
        result = structured.invoke([
            ("system", "You are an airline pricing expert. Return realistic estimates."),
            ("user", prompt),
        ])
        legs = result.legs if result.legs else []
    except Exception:
        logger.warning("structured_output failed for flight estimate, trying raw JSON")
        try:
            raw_response = llm.invoke([
                ("system", "You are an airline pricing expert. Return ONLY valid JSON, no other text."),
                ("user", prompt + "\n\nReturn JSON: {\"legs\": [{\"tag\": \"OUT\"|\"RET\"|\"LOCAL\", \"summary\": str, \"detail\": str, \"price\": float, \"currency\": \"USD\"|\"EUR\", \"link\": str}]}")
            ])
            text = raw_response.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(text)
            legs = parsed.get("legs", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(legs, list):
                legs = []
        except Exception:
            logger.exception("LLM flight estimation failed (both methods)")
            return []

    for leg in legs:
        if isinstance(leg, dict):
            leg["_source"] = "llm_estimate"
            leg["_degraded"] = True
    return [leg for leg in legs if isinstance(leg, dict)]


# ── Main entry point ─────────────────────────────────────────────────

@cached(ttl=_TTL)
def search_flights(
    origin: str,
    dest: str,
    date: str,
    return_date: str | None = None,
    stops: int | None = None,
    cabin: str | None = None,
) -> tuple[list[dict], str]:
    """Search for flights. Returns (results, degradation_summary).

    WHY return a tuple (results, summary) instead of just results?
    Because the caller (agent) needs the summary string to include in
    its status message to the user. Example:
        "Found 5 flights (google_flights + bing)"
        "Found 2 flights (estimated — google_flights failed: timeout)"

    The summary is a human-readable one-liner from DegradationReport.

    Raises:
        RuntimeError: when ALL sources (parallel + LLM) fail.
        The calling agent catches this and falls back to mock.
    """
    api_key = os.environ.get("SERPAPI_API_KEY")

    # ── Layer 1: Parallel real sources ───────────────────────────
    if api_key:
        # Two complementary sources (tested: Bing returned locale-dependent
        # noise — flight simulators or Chinese social media. Not worth it.):
        # - google_flights: structured airline data (primary, one-level source)
        # - google_search: price snippets as cross-reference (two-level source)
        # True redundancy (another one-level source) would need Amadeus API.
        sources = {
            "google_flights": lambda: _try_serpapi_google_flights(
                origin, dest, date, return_date, stops, cabin, api_key,
            ),
            "google_search": lambda: _try_serpapi_google_search_flights(
                origin, dest, date, api_key,
            ),
        }

        results, report = query_parallel(sources, timeout=20)

        if results:
            logger.info("search_flights: parallel success — %s", report.summary())
            degradation_msg = ""
            if report.any_failed:
                degradation_msg = f" (partial: {', '.join(report.failed)} failed)"
            return results, f"sources: {', '.join(report.succeeded)}{degradation_msg}"

        # All parallel sources failed
        logger.warning("search_flights: all parallel sources failed — %s", report.summary())

    # ── Layer 2: LLM estimation ──────────────────────────────────
    logger.info("search_flights: trying LLM estimation fallback")
    llm_results = _try_llm_estimate(origin, dest, date, stops, cabin)
    if llm_results:
        logger.info("search_flights: LLM estimation returned %d results", len(llm_results))
        return llm_results, "source: llm_estimate (real-time data unavailable)"

    # ── Layer 3: Everything failed ───────────────────────────────
    raise RuntimeError(
        f"All flight data sources exhausted for {origin} -> {dest} {date}"
    )
