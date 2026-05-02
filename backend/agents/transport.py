"""Transport agent node."""

from __future__ import annotations

import logging

from state import TravelPlanState
from agents._shared import _direct_only_requested, _msg
from tools._constraints import normalize_constraints
from tools._rationale import build_flight_rationale

logger = logging.getLogger(__name__)


# ── transport_agent ──────────────────────────────────────────────────
def _transport_mock(state: TravelPlanState) -> list[dict]:
    """Fallback transport options — shown when every external tool fails.

    Must reflect the user's actual trip (city, dates) instead of
    hardcoded Milan/Monza defaults. Fallback is product behavior:
    when SerpAPI / LLM estimation both error, the user sees these
    strings, so they have to be truthful.
    """
    from tools._trip_dates import compute_trip_dates
    origin = state.get("origin", "") or "your origin"
    city = state.get("gp_city", "") or "destination"
    dates = compute_trip_dates(
        state.get("gp_date", ""),
        state.get("extra_days", 0),
        state.get("depart_date", "") or "",
        state.get("return_date", "") or "",
    )
    out_date = dates.get("outbound_date", "?")
    ret_date = dates.get("return_date", "?")
    return [
        {"tag": "OUT", "summary": f"{origin} → {city}",
         "detail": f"Estimated direct route · {out_date}",
         "price": 485, "currency": "EUR",
         "link": "https://www.google.com/travel/flights",
         "provider": "Google Flights", "link_type": "flight_search",
         "booking_confidence": "search"},
        {"tag": "RET", "summary": f"{city} → {origin}",
         "detail": f"Estimated direct route · {ret_date}",
         "price": 520, "currency": "EUR",
         "link": "https://www.google.com/travel/flights",
         "provider": "Google Flights", "link_type": "flight_search",
         "booking_confidence": "search"},
        {"tag": "LOCAL", "summary": f"{city} ↔ Circuit",
         "detail": "Local transit (varies by circuit)",
         "price": 5, "currency": "EUR",
         "link": "", "provider": "Local transit",
         "link_type": "local_info", "booking_confidence": "low"},
    ]


def transport_agent(state: TravelPlanState) -> dict:
    """Search for flights and local transport. Parallel with hotel_agent.

    Phase 3: tries tools.search_flights first, falls back to mock.
    """
    origin = state.get("origin", "NYC")
    city = state.get("gp_city", "Milan")
    stops = state.get("stops", "")
    constraints = normalize_constraints(state.get("active_constraints"))
    request_text = f"{stops} {state.get('special_requests', '')}"
    max_stops = 0 if constraints.get("direct_only") or _direct_only_requested(request_text) else None

    try:
        from tools.search_flights import search_flights
        from tools._trip_dates import compute_trip_dates
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
        transport, source_summary = search_flights(
            origin=origin, dest=city,
            date=dates["outbound_date"],
            return_date=dates["return_date"],
            stops=max_stops,
        )
    except Exception:
        logger.exception("transport_agent: all tools failed, using mock")
        transport = _transport_mock(state)
        source_summary = "source: mock (all data sources failed)"

    flight_legs = [
        leg for leg in transport
        if isinstance(leg, dict) and leg.get("tag") in {"ROUNDTRIP", "OUT", "RET"}
    ]
    for leg in flight_legs:
        leg["_rationale"] = build_flight_rationale(leg, flight_legs, state)

    msgs = [_msg("transport", f"Found flights {origin} <-> {city} ({source_summary})")]
    if stops:
        msgs.append(_msg("transport", f"Multi-stop route noted: {stops}"))
    if max_stops == 0:
        msgs.append(_msg("transport", "Applied hard constraint: direct flights only"))

    return {"transport": transport, "messages": msgs}
