"""Deterministic rationale builders for the "Why this card?" panel.

Each builder explains a ticket, flight, hotel, or tour recommendation
using data already present in the card and the shared plan state. These
helpers are intentionally read-only: they never call external services
and never mutate the source lists.

The returned ``fallback_chain`` is a user-facing source path inferred
from the card's final source. It is not a complete runtime attempt log.
For example, a mock hotel reports ["serpapi", "llm_estimate", "mock"]
as the product's configured data path, not proof that every source was
called for this exact card.
"""

from __future__ import annotations

import re
from typing import Any

from ._constraints import extract_hotel_brands, normalize_constraints


_HOTEL_SOURCE_CHAIN = ["serpapi", "llm_estimate", "mock"]
_FLIGHT_SOURCE_CHAIN = ["serpapi", "llm_estimate", "mock"]
_TICKET_SOURCE_CHAIN = ["firecrawl", "llm_estimate", "mock"]
_TOUR_SOURCE_CHAIN = ["llm", "mock"]

_HOTEL_REAL = {"google_hotels", "google_maps", "serpapi"}
_FLIGHT_REAL = {"google_flights", "google_search", "serpapi"}
_TICKET_REAL = {"firecrawl", "google_search"}

_DISTANCE_KM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|miles?|mi)\b", re.IGNORECASE)


def _normalize_source(item: dict, default: str = "mock") -> str:
    src = item.get("_source")
    if isinstance(src, str) and src.strip():
        return src.strip()
    return default


def _infer_source_path(source: str, card_type: str) -> list[str]:
    """Infer the configured data path from the final card source."""
    if card_type == "hotel":
        if source in _HOTEL_REAL:
            return ["serpapi"]
        if source == "llm_estimate":
            return ["serpapi", "llm_estimate"]
        return list(_HOTEL_SOURCE_CHAIN)
    if card_type == "flight":
        if source in _FLIGHT_REAL:
            return ["serpapi"]
        if source == "llm_estimate":
            return ["serpapi", "llm_estimate"]
        return list(_FLIGHT_SOURCE_CHAIN)
    if card_type == "ticket":
        if source in _TICKET_REAL:
            return ["firecrawl"]
        if source == "llm_estimate":
            return ["firecrawl", "llm_estimate"]
        return list(_TICKET_SOURCE_CHAIN)
    if card_type == "tour":
        if source in {"llm", "openai", "anthropic"}:
            return ["llm"]
        return list(_TOUR_SOURCE_CHAIN)
    return [source]


def _parse_distance_km(distance_str: str | None) -> float | None:
    if not distance_str or not isinstance(distance_str, str):
        return None
    match = _DISTANCE_KM_RE.search(distance_str)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("mi"):
        value *= 1.609
    return round(value, 2)


def _provider_label(item: dict) -> str:
    return str(item.get("provider") or item.get("_source") or "").strip()


def _format_price(item: dict, key: str = "price") -> str:
    price = item.get(key, 0) or 0
    if price <= 0:
        return ""
    currency = str(item.get("currency") or "EUR").upper()
    sym = {"EUR": "EUR ", "USD": "$", "CNY": "CNY "}.get(currency, currency + " ")
    return f"{sym}{price:.0f}"


def _budget_headroom(state: dict[str, Any]) -> float | None:
    budget = state.get("budget")
    summary = state.get("budget_summary") or {}
    total = summary.get("total")
    if budget is None or total is None:
        return None
    try:
        return float(budget) - float(total)
    except (TypeError, ValueError):
        return None


def _hotel_price_per_night(hotel: dict) -> float:
    try:
        return float(hotel.get("price_per_night", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _hotel_trade_offs(hotel: dict, alternatives: list[dict]) -> list[dict]:
    out: list[dict] = []
    name = hotel.get("name", "")
    here_price = _hotel_price_per_night(hotel)
    here_dist = _parse_distance_km(hotel.get("distance"))
    currency = str(hotel.get("currency") or "EUR").upper()
    sym = {"EUR": "EUR ", "USD": "$", "CNY": "CNY "}.get(currency, currency + " ")
    for alt in alternatives:
        if not isinstance(alt, dict) or alt.get("name") == name:
            continue
        alt_price = _hotel_price_per_night(alt)
        if alt_price <= 0:
            continue
        adv: list[str] = []
        cost: list[str] = []
        diff = here_price - alt_price
        if diff < -0.5:
            adv.append(f"{sym}{abs(diff):.0f}/night cheaper")
        elif diff > 0.5:
            cost.append(f"+{sym}{diff:.0f}/night")
        alt_dist = _parse_distance_km(alt.get("distance"))
        if here_dist is not None and alt_dist is not None:
            d = here_dist - alt_dist
            if d < -0.1:
                adv.append(f"{abs(d):.1f} km closer to circuit")
            elif d > 0.1:
                cost.append(f"{d:.1f} km farther from circuit")
        if not adv and not cost:
            continue
        out.append({
            "against": alt.get("name", "alternative"),
            "advantage": "; ".join(adv) if adv else "comparable",
            "cost": "; ".join(cost) if cost else "comparable",
        })
        if len(out) >= 3:
            break
    return out


def _flight_price(item: dict) -> float:
    try:
        return float(item.get("price", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _flight_trade_offs(flight: dict, alternatives: list[dict]) -> list[dict]:
    out: list[dict] = []
    here_price = _flight_price(flight)
    here_stops = flight.get("stops")
    currency = str(flight.get("currency") or "EUR").upper()
    sym = {"EUR": "EUR ", "USD": "$", "CNY": "CNY "}.get(currency, currency + " ")
    for alt in alternatives:
        if not isinstance(alt, dict) or alt.get("tag") in {"LOCAL", "INFO"}:
            continue
        if alt is flight:
            continue
        if (
            alt.get("summary") == flight.get("summary")
            and alt.get("detail") == flight.get("detail")
            and alt.get("tag") == flight.get("tag")
        ):
            continue
        alt_price = _flight_price(alt)
        if alt_price <= 0:
            continue
        adv: list[str] = []
        cost: list[str] = []
        diff = here_price - alt_price
        if diff < -0.5:
            adv.append(f"{sym}{abs(diff):.0f} cheaper")
        elif diff > 0.5:
            cost.append(f"+{sym}{diff:.0f}")
        alt_stops = alt.get("stops")
        if here_stops == 0 and isinstance(alt_stops, int) and alt_stops > 0:
            adv.append("direct vs connection")
        elif isinstance(here_stops, int) and here_stops > 0 and alt_stops == 0:
            cost.append("connection vs direct")
        if not adv and not cost:
            continue
        out.append({
            "against": alt.get("summary") or alt.get("detail") or "alternative",
            "advantage": "; ".join(adv) if adv else "comparable",
            "cost": "; ".join(cost) if cost else "comparable",
        })
        if len(out) >= 3:
            break
    return out


def _ticket_price(item: dict) -> float:
    try:
        return float(item.get("price", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _ticket_trade_offs(ticket: dict, alternatives: list[dict]) -> list[dict]:
    out: list[dict] = []
    name = ticket.get("name", "")
    here_price = _ticket_price(ticket)
    here_tag = ticket.get("tag", "")
    currency = str(ticket.get("currency") or "EUR").upper()
    sym = {"EUR": "EUR ", "USD": "$", "CNY": "CNY "}.get(currency, currency + " ")
    for alt in alternatives:
        if not isinstance(alt, dict) or alt.get("name") == name:
            continue
        alt_price = _ticket_price(alt)
        if alt_price <= 0:
            continue
        adv: list[str] = []
        cost: list[str] = []
        diff = here_price - alt_price
        if diff < -0.5:
            adv.append(f"{sym}{abs(diff):.0f} cheaper")
        elif diff > 0.5:
            cost.append(f"+{sym}{diff:.0f}")
        alt_tag = alt.get("tag", "")
        if here_tag == "PICK" and alt_tag in {"VALUE", "VIP"}:
            adv.append(f"balanced against {alt_tag}")
        elif here_tag == "VALUE" and alt_tag in {"PICK", "VIP"}:
            adv.append("most affordable option")
        elif here_tag == "VIP" and alt_tag in {"VALUE", "PICK"}:
            adv.append("premium experience")
        if not adv and not cost:
            continue
        out.append({
            "against": alt.get("name", "alternative"),
            "advantage": "; ".join(adv) if adv else "comparable",
            "cost": "; ".join(cost) if cost else "comparable",
        })
        if len(out) >= 3:
            break
    return out


def _tour_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("title") or "")
    if isinstance(item, str):
        return item
    return ""


def _tour_trade_offs(tour_item: Any, alternatives: list) -> list[dict]:
    out: list[dict] = []
    here = _tour_label(tour_item)
    for alt in alternatives:
        alt_label = _tour_label(alt)
        if not alt_label or alt_label == here:
            continue
        out.append({
            "against": alt_label[:80],
            "advantage": "different focus or venue",
            "cost": "skips the alternative experience",
        })
        if len(out) >= 2:
            break
    return out


def build_hotel_rationale(hotel: dict, alternatives: list[dict], state: dict[str, Any]) -> dict:
    constraints = normalize_constraints(state.get("active_constraints"))
    source = _normalize_source(hotel)
    source_path = _infer_source_path(source, "hotel")

    reasons: list[str] = []
    distance_km = _parse_distance_km(hotel.get("distance"))
    if distance_km is not None:
        sibling_dists = [
            _parse_distance_km(a.get("distance"))
            for a in alternatives
            if isinstance(a, dict) and a.get("name") != hotel.get("name")
        ]
        sibling_dists = [d for d in sibling_dists if d is not None]
        if sibling_dists and distance_km <= min(sibling_dists):
            reasons.append(f"Distance: {distance_km} km from circuit (closest among options)")
        else:
            reasons.append(f"Distance: {distance_km} km from circuit")
    elif hotel.get("distance"):
        reasons.append(f"Distance: {hotel.get('distance')}")

    constraint_matches: dict[str, Any] = {}
    allowed_brands = constraints.get("allowed_hotel_brands") or []
    if allowed_brands:
        matched_brands = extract_hotel_brands(hotel.get("name", ""))
        matched = next((brand for brand in allowed_brands if brand in matched_brands), None)
        if matched:
            constraint_matches["allowed_hotel_brands"] = {"matched": matched}
            reasons.append(f"Brand: {matched} portfolio (matched per request)")
        else:
            reasons.append(f"Brand: outside requested list ({', '.join(allowed_brands)})")

    if constraints.get("avoid_luxury"):
        tag = (hotel.get("tag") or "").upper()
        is_budgety = tag in {"BUDGET", "SAVE"} or _hotel_price_per_night(hotel) < 120
        if is_budgety:
            constraint_matches["avoid_luxury"] = True

    per_night = _hotel_price_per_night(hotel)
    nights = hotel.get("nights") or 1
    if per_night > 0:
        currency = str(hotel.get("currency") or "EUR").upper()
        sym = {"EUR": "EUR ", "USD": "$", "CNY": "CNY "}.get(currency, currency + " ")
        total = per_night * nights
        headroom = _budget_headroom(state)
        if headroom is not None:
            reasons.append(
                f"Price: {sym}{per_night:.0f}/night x {nights} nights = "
                f"{sym}{total:.0f}; budget headroom {sym}{headroom:.0f}"
            )
        else:
            reasons.append(f"Price: {sym}{per_night:.0f}/night x {nights} nights = {sym}{total:.0f}")

    if hotel.get("rating"):
        reasons.append(f"Rating: {hotel.get('rating')}")
    provider = _provider_label(hotel)
    if provider:
        reasons.append(f"Source: {provider}")

    return {
        "card_type": "hotel",
        "source": source,
        "fallback_chain": source_path,
        "source_path_note": "Configured data path inferred from the final card source.",
        "reasons": reasons[:5],
        "constraint_matches": constraint_matches,
        "trade_offs": _hotel_trade_offs(hotel, alternatives),
    }


def build_flight_rationale(flight: dict, alternatives: list[dict], state: dict[str, Any]) -> dict:
    constraints = normalize_constraints(state.get("active_constraints"))
    source = _normalize_source(flight)
    source_path = _infer_source_path(source, "flight")

    reasons: list[str] = []
    constraint_matches: dict[str, Any] = {}
    stops = flight.get("stops")
    if constraints.get("direct_only"):
        if stops == 0:
            constraint_matches["direct_only"] = True
            reasons.append("Direct flight (per your request)")
        else:
            constraint_matches["direct_only"] = False
    elif stops == 0:
        reasons.append("Direct flight")

    if flight.get("summary"):
        reasons.append(f"Route: {flight.get('summary')}")
    if flight.get("detail"):
        reasons.append(f"Schedule: {flight.get('detail')}")
    price_str = _format_price(flight)
    if price_str:
        reasons.append(f"Price: {price_str}")
    provider = _provider_label(flight)
    if provider:
        reasons.append(f"Provider: {provider}")

    return {
        "card_type": "flight",
        "source": source,
        "fallback_chain": source_path,
        "source_path_note": "Configured data path inferred from the final card source.",
        "reasons": reasons[:5],
        "constraint_matches": constraint_matches,
        "trade_offs": _flight_trade_offs(flight, alternatives),
    }


def build_ticket_rationale(ticket: dict, alternatives: list[dict], state: dict[str, Any]) -> dict:
    source = _normalize_source(ticket)
    source_path = _infer_source_path(source, "ticket")

    reasons: list[str] = []
    tag = (ticket.get("tag") or "").upper()
    if tag == "PICK":
        reasons.append("Tag: PICK (recommended balance of price and view)")
    elif tag == "VALUE":
        reasons.append("Tag: VALUE (most affordable option)")
    elif tag == "VIP":
        reasons.append("Tag: VIP (premium grandstand experience)")
    if ticket.get("section"):
        reasons.append(f"Section: {ticket.get('section')}")
    price_str = _format_price(ticket)
    if price_str:
        reasons.append(f"Price: {price_str}")
    provider = _provider_label(ticket)
    if provider:
        reasons.append(f"Source: {provider}")

    constraint_matches: dict[str, Any] = {}
    constraints = normalize_constraints(state.get("active_constraints"))
    if constraints.get("avoid_luxury") and tag in {"VALUE", "PICK"}:
        constraint_matches["avoid_luxury"] = True

    return {
        "card_type": "ticket",
        "source": source,
        "fallback_chain": source_path,
        "source_path_note": "Configured data path inferred from the final card source.",
        "reasons": reasons[:5],
        "constraint_matches": constraint_matches,
        "trade_offs": _ticket_trade_offs(ticket, alternatives),
    }


def build_tour_rationale(tour_item: Any, alternatives: list, state: dict[str, Any]) -> dict:
    source = "llm" if isinstance(tour_item, str) else _normalize_source(tour_item, default="llm")
    source_path = _infer_source_path(source, "tour")

    reasons: list[str] = []
    label = _tour_label(tour_item)
    if label:
        reasons.append(f"Recommendation: {label[:120]}")
    special = (state.get("special_requests") or "").strip()
    if special:
        reasons.append(f"Aligned with special request: {special[:80]}")

    constraints = normalize_constraints(state.get("active_constraints"))
    constraint_matches: dict[str, Any] = {}
    if constraints.get("accessibility"):
        text = label.lower()
        if any(token in text for token in ("accessible", "wheelchair", "step-free", "无障碍", "輪椅", "轮椅")):
            constraint_matches["accessibility"] = True
    if constraints.get("dietary"):
        constraint_matches.setdefault("dietary", str(constraints.get("dietary")))

    return {
        "card_type": "tour",
        "source": source,
        "fallback_chain": source_path,
        "source_path_note": "Configured data path inferred from the final card source.",
        "reasons": reasons[:5],
        "constraint_matches": constraint_matches,
        "trade_offs": _tour_trade_offs(tour_item, alternatives),
    }
