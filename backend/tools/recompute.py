"""Pure-function helpers for budget recomputation and plan validation.

Phase 3.6 / Batch 3: currency-aware end-to-end.

Each item carries a `currency` field (EUR, USD, CNY). All amounts are
converted through EUR to the target currency (read from state.currency,
default EUR) before summing. No more silent mixed-currency addition,
and the final BudgetSummary is denominated in the user-selected currency.

The recompute logic:
- Filters out INFO/supplementary items (tag="INFO" or price=0)
- Picks the cheapest ROUNDTRIP flight, or cheapest OUT + RET pair, plus LOCAL
- Picks the cheapest real hotel and multiplies by nights
- Converts every amount source_currency → target_currency via EUR pivot
- Per-category defaults (tour/food/misc) are defined in EUR and
  converted to target at output time
"""

from __future__ import annotations
import logging
from typing import Any

from ._currency import convert, from_eur
from ._trip_dates import trip_nights

logger = logging.getLogger(__name__)

# Estimated costs baseline, expressed in EUR
_TOUR_EUR = 44.0
_FOOD_EUR = 240.0
_MISC_LOCAL_EUR = 40.0


def _positive_float(value: Any) -> float:
    """Return a positive float, or 0.0 for missing/unpriced values."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount > 0 else 0.0


def _item_nights(item: dict, state: dict[str, Any]) -> int:
    try:
        nights = int(item.get("nights", 1) or 1)
    except (TypeError, ValueError):
        nights = 1
    if nights <= 1:
        nights = trip_nights(state)
    return nights


def _item_price_in(item: dict, target: str, price_key: str = "price") -> float:
    """Extract price from an item and convert to target currency."""
    price = _positive_float(item.get(price_key, 0))
    if price <= 0:
        return 0.0
    source = item.get("currency", "EUR")
    return convert(price, source, target)


def _pick_cheapest_in(items: list[dict], tag_filter: str, target: str) -> float:
    """Pick the cheapest item matching a tag, in target currency."""
    candidates = [
        _item_price_in(t, target)
        for t in items
        if t.get("tag") == tag_filter and _positive_float(t.get("price", 0)) > 0
    ]
    if not candidates:
        return 0.0
    return min(candidates)


def _pick_cheapest_item(items: list[dict], tag_filter: str, target: str) -> dict | None:
    """Pick the cheapest priced item matching a tag."""
    candidates = [
        item for item in items
        if item.get("tag") == tag_filter and _positive_float(item.get("price", 0)) > 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: _item_price_in(item, target))


def _display_items(items: list[dict]) -> list[dict]:
    return [item for item in items if isinstance(item, dict) and item.get("tag") != "INFO"]


_SELECTION_KEYS = {"ticket", "transport", "hotel"}


def _normalize_selections(selections: dict[str, Any] | None) -> dict[str, list[int]]:
    normalized: dict[str, list[int]] = {}
    if selections is None:
        return normalized
    if not isinstance(selections, dict):
        raise ValueError("selections must be an object")
    if not selections:
        return normalized
    unknown = sorted(set(selections) - _SELECTION_KEYS)
    if unknown:
        raise ValueError(f"Unknown selection category: {', '.join(unknown)}")
    for key in ("ticket", "transport", "hotel"):
        raw = selections.get(key, [])
        if isinstance(raw, bool):
            raise ValueError(f"Selection index for {key} must be an integer")
        if isinstance(raw, int):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError(f"Selections for {key} must be an integer or list of integers")
        values = []
        for idx in raw:
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise ValueError(f"Selection index for {key} must be an integer")
            if idx < 0:
                raise ValueError(f"Selection index for {key} must be non-negative")
            if idx not in values:
                values.append(idx)
        if values:
            normalized[key] = values
    return normalized


def _selected_items(items: list[dict], selections: dict[str, list[int]], key: str) -> list[dict]:
    if key not in selections:
        return []
    picked: list[dict] = []
    for idx in selections.get(key, []):
        if idx < 0 or idx >= len(items):
            raise ValueError(f"Invalid selection index for {key}: {idx}")
        picked.append(items[idx])
    return picked


def _price_or_missing(
    item: dict,
    target: str,
    missing: set[str],
    category: str,
    price_key: str = "price",
) -> float:
    amount = _item_price_in(item, target, price_key)
    if amount <= 0:
        missing.add(category)
    return amount


def recompute_budget(state: dict[str, Any], selections: dict[str, Any] | None = None) -> dict:
    """Recompute the budget summary from current state fields.

    All prices are converted to the user-selected currency (state.currency,
    default EUR) before summing. The budget itself is assumed to be
    already denominated in that currency (see CLAUDE.md: the selector
    changes the unit, it does not auto-convert the numeric value).

    Returns a BudgetSummary-shaped dict with per-item breakdown,
    items annotated with the target currency, and total in target.
    """
    target = str(state.get("currency") or "EUR").upper()
    normalized_selections = _normalize_selections(selections)
    basis = "selected" if normalized_selections else "baseline"
    missing_categories: set[str] = set()

    # ── Tickets: pick the PICK-tagged option, or cheapest ────────
    tickets = _display_items(state.get("tickets") or [])
    selected_tickets = _selected_items(tickets, normalized_selections, "ticket")
    if selected_tickets:
        ticket_cost = sum(
            _price_or_missing(t, target, missing_categories, "Tickets")
            for t in selected_tickets
        )
    else:
        real_tickets = [t for t in tickets if _positive_float(t.get("price", 0)) > 0]
        if real_tickets:
            pick = next((t for t in real_tickets if t.get("tag") == "PICK"), None)
            chosen = pick or min(real_tickets, key=lambda t: _item_price_in(t, target))
            ticket_cost = _item_price_in(chosen, target)
        else:
            ticket_cost = 0.0
            if tickets:
                missing_categories.add("Tickets")

    # ── Transport: handle ROUNDTRIP (single price) or OUT+RET ────
    transport = _display_items(state.get("transport") or [])
    selected_transport = _selected_items(transport, normalized_selections, "transport")
    local_items = [t for t in transport if t.get("tag") == "LOCAL" and _positive_float(t.get("price", 0)) > 0]
    selected_flights = [t for t in selected_transport if t.get("tag") != "LOCAL"]
    if selected_transport:
        if not selected_flights:
            raise ValueError("Transport selection must reference a flight option")

        selected_roundtrips = [t for t in selected_flights if t.get("tag") == "ROUNDTRIP"]
        selected_out = [t for t in selected_flights if t.get("tag") == "OUT"]
        selected_ret = [t for t in selected_flights if t.get("tag") == "RET"]

        if selected_roundtrips:
            flight_cost = sum(
                _price_or_missing(t, target, missing_categories, "Flights")
                for t in selected_roundtrips
            )
        else:
            if selected_out:
                out_cost = sum(
                    _price_or_missing(t, target, missing_categories, "Flights")
                    for t in selected_out
                )
            else:
                paired_out = _pick_cheapest_item(transport, "OUT", target)
                out_cost = _price_or_missing(paired_out, target, missing_categories, "Flights") if paired_out else 0.0
                if out_cost <= 0:
                    missing_categories.add("Flights")

            if selected_ret:
                ret_cost = sum(
                    _price_or_missing(t, target, missing_categories, "Flights")
                    for t in selected_ret
                )
            else:
                paired_ret = _pick_cheapest_item(transport, "RET", target)
                ret_cost = _price_or_missing(paired_ret, target, missing_categories, "Flights") if paired_ret else 0.0
                if ret_cost <= 0:
                    missing_categories.add("Flights")

            flight_cost = out_cost + ret_cost

        # Local transit is part of the trip baseline, not a selectable flight.
        local_cost = sum(_item_price_in(t, target) for t in local_items)
    else:
        roundtrip_cost = _pick_cheapest_in(transport, "ROUNDTRIP", target)
        if roundtrip_cost > 0:
            # google_flights round-trip: price already covers both directions
            flight_cost = roundtrip_cost
        else:
            # One-way searches or mock data: separate OUT + RET
            out_cost = _pick_cheapest_in(transport, "OUT", target)
            ret_cost = _pick_cheapest_in(transport, "RET", target)
            flight_cost = out_cost + ret_cost
            # A one-way-only flight set (priced OUT but no priced RET, or vice
            # versa) is an INCOMPLETE quote, not a free return leg. Mirror the
            # selection path so the baseline can't show a green within-budget
            # total for a half-priced trip.
            flight_legs = [t for t in transport if t.get("tag") in {"OUT", "RET", "ROUNDTRIP"}]
            if flight_legs and (out_cost <= 0 or ret_cost <= 0):
                missing_categories.add("Flights")
        if flight_cost <= 0 and transport:
            missing_categories.add("Flights")
        local_cost = sum(_item_price_in(t, target) for t in local_items)
    transport_cost = flight_cost + local_cost

    # ── Hotel: cheapest real hotel × nights ──────────────────────
    hotel_list = _display_items(state.get("hotel") or [])
    selected_hotels = _selected_items(hotel_list, normalized_selections, "hotel")
    if selected_hotels:
        hotel_cost = 0.0
        for hotel in selected_hotels:
            per_night = _price_or_missing(
                hotel,
                target,
                missing_categories,
                "Hotel",
                "price_per_night",
            )
            nights = _item_nights(hotel, state)
            hotel_cost += per_night * nights
    else:
        real_hotels = [h for h in hotel_list if _positive_float(h.get("price_per_night", 0)) > 0]
        if real_hotels:
            cheapest = min(
                real_hotels,
                key=lambda h: _item_price_in(h, target, "price_per_night"),
            )
            per_night = _item_price_in(cheapest, target, "price_per_night")
            # Item may not carry a valid nights count. Use the canonical
            # helper so this matches the user's explicit dates.
            nights = _item_nights(cheapest, state)
            hotel_cost = per_night * nights
        else:
            hotel_cost = 0.0
            if hotel_list:
                missing_categories.add("Hotel")

    # ── Estimated costs (EUR baselines → convert to target) ──────
    tour_cost = from_eur(_TOUR_EUR, target)
    food_cost = from_eur(_FOOD_EUR, target)
    misc_local = from_eur(_MISC_LOCAL_EUR, target)

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + misc_local
    budget = float(state.get("budget", 2500))
    quote_complete = not missing_categories
    within = total <= budget and quote_complete
    retry_exhausted = not within and int(state.get("retry_count", 0) or 0) >= 2

    items = [
        {"name": "Tickets",         "amount": round(ticket_cost, 2),    "currency": target},
        {"name": "Flights",         "amount": round(transport_cost, 2), "currency": target},
        {"name": "Hotel",           "amount": round(hotel_cost, 2),     "currency": target},
        {"name": "Activities",      "amount": round(tour_cost, 2),      "currency": target},
        {"name": "Food (est.)",     "amount": round(food_cost, 2),      "currency": target},
        {"name": "Local transport", "amount": round(misc_local, 2),     "currency": target},
    ]

    tip = ""
    if not quote_complete:
        missing = ", ".join(sorted(missing_categories))
        tip = f"Quote incomplete: pending price for {missing}. Budget status is not final."
    elif not within:
        over = total - budget
        if retry_exhausted:
            tip = (
                f"No feasible plan under {target} {budget:.0f} was found after "
                f"budget retries; current plan is over by {target} {over:.0f}."
            )
        else:
            tip = f"Over budget by {target} {over:.0f}. Consider a cheaper hotel or GA tickets."

    return {
        "items": items,
        "total": round(total, 2),
        "budget": budget,
        "currency": target,
        "within_budget": within,
        "retry_exhausted": retry_exhausted,
        "feasible_under_budget_found": within,
        "basis": basis,
        "quote_complete": quote_complete,
        "missing_price_categories": sorted(missing_categories),
        "selected_indices": normalized_selections,
        "savings_tip": tip,
    }
