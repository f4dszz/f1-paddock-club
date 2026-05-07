"""Hotel agent node."""

from __future__ import annotations

import logging

from state import TravelPlanState
from agents._shared import _msg, _requested_hotel_brands, _trip_days
from tools._constraints import normalize_constraints
from tools._rationale import build_hotel_rationale

logger = logging.getLogger(__name__)


# ── hotel_agent ──────────────────────────────────────────────────────
def _hotel_mock(state: TravelPlanState, budget_retry: bool = False) -> list[dict]:
    city = state.get("gp_city", "Monza")
    days = _trip_days(state)
    if budget_retry:
        return [
            {"name": f"Budget Hostel {city}", "price_per_night": 55,
             "total_price": 55 * days, "currency": "EUR", "nights": days,
             "distance": "20min bus", "rating": "7.2", "tag": "BUDGET",
             "link": "https://www.booking.com",
             "provider": "Booking.com", "link_type": "homepage",
             "booking_confidence": "low"},
            {"name": f"Airbnb {city} Outskirts", "price_per_night": 65,
             "total_price": 65 * days, "currency": "EUR", "nights": days,
             "distance": "25min train", "rating": "4.3", "tag": "SAVE",
             "link": "https://www.airbnb.com",
             "provider": "Airbnb", "link_type": "homepage",
             "booking_confidence": "low"},
        ]
    return [
        {"name": "Hotel de la Ville", "price_per_night": 135,
         "total_price": 135 * days, "currency": "EUR", "nights": days,
         "distance": "2km to circuit", "rating": "8.4", "tag": "NEAR",
         "link": "https://www.booking.com",
         "provider": "Booking.com", "link_type": "homepage",
         "booking_confidence": "low"},
        {"name": f"Airbnb {city} Central", "price_per_night": 95,
         "total_price": 95 * days, "currency": "EUR", "nights": days,
         "distance": "15min train", "rating": "4.6", "tag": "SAVE",
         "link": "https://www.airbnb.com",
         "provider": "Airbnb", "link_type": "homepage",
         "booking_confidence": "low"},
    ]


def hotel_agent(state: TravelPlanState) -> dict:
    """Search for hotels. Parallel with transport_agent.

    Phase 3: tries tools.search_hotels first, falls back to mock.
    On budget retry (retry_count > 0), passes a lower max_price hint
    to the tool so it returns cheaper options.
    """
    retry = state.get("retry_count", 0)
    city = state.get("gp_city", "Monza")
    days = _trip_days(state)
    constraints = normalize_constraints(state.get("active_constraints"))
    requested_brands = constraints.get("allowed_hotel_brands") or _requested_hotel_brands(state.get("special_requests", ""))
    strict_brand = bool(requested_brands)
    brand = " or ".join(requested_brands)

    try:
        from tools.search_hotels import search_hotels
        from tools._trip_dates import compute_trip_dates
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
        max_price = None
        if retry > 0:
            budget_remaining = float(state.get("budget", 2500)) * 0.3
            max_price = budget_remaining / days if days > 0 else None
        hotel, source_summary = search_hotels(
            city=city,
            checkin=dates["hotel_checkin"],
            checkout=dates["hotel_checkout"],
            max_price=max_price,
            brand=brand or None,
            strict_brand=strict_brand,
        )
    except Exception:
        logger.exception("hotel_agent: all tools failed, using mock")
        if strict_brand:
            hotel = []
            source_summary = f"no hotel options matched required brand(s): {brand}"
        else:
            hotel = _hotel_mock(state, budget_retry=(retry > 0))
            source_summary = "source: mock (all data sources failed)"

    for h in hotel:
        if isinstance(h, dict):
            h["_rationale"] = build_hotel_rationale(h, hotel, state)

    if retry > 0:
        return {
            "hotel": hotel,
            "messages": [_msg("hotel", f"Found cheaper options (retry #{retry}, {source_summary})")],
        }

    return {
        "hotel": hotel,
        "messages": [_msg("hotel", f"Found {len(hotel)} stays in {city} ({days} nights, {source_summary})")],
    }
