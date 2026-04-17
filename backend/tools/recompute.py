"""Pure-function helpers for budget recomputation and plan validation.

Phase 3.6 / Batch 3: currency-aware end-to-end.

Each item carries a `currency` field (EUR, USD, CNY). All amounts are
converted through EUR to the target currency (read from state.currency,
default EUR) before summing. No more silent mixed-currency addition,
and the final BudgetSummary is denominated in the user-selected currency.

The recompute logic:
- Filters out INFO/supplementary items (tag="INFO" or price=0)
- Picks the cheapest OUT flight + cheapest RET flight (if any) + LOCAL
- Picks the cheapest real hotel and multiplies by nights
- Converts every amount source_currency → target_currency via EUR pivot
- Per-category defaults (tour/food/misc) are defined in EUR and
  converted to target at output time
"""

from __future__ import annotations
import logging
from typing import Any

from ._currency import convert, from_eur

logger = logging.getLogger(__name__)

# Estimated costs baseline, expressed in EUR
_TOUR_EUR = 44.0
_FOOD_EUR = 240.0
_MISC_LOCAL_EUR = 40.0


def _item_price_in(item: dict, target: str, price_key: str = "price") -> float:
    """Extract price from an item and convert to target currency."""
    price = item.get(price_key, 0)
    if not price or price <= 0:
        return 0.0
    source = item.get("currency", "EUR")
    return convert(float(price), source, target)


def _pick_cheapest_in(items: list[dict], tag_filter: str, target: str) -> float:
    """Pick the cheapest item matching a tag, in target currency."""
    candidates = [
        _item_price_in(t, target)
        for t in items
        if t.get("tag") == tag_filter and t.get("price", 0) > 0
    ]
    if not candidates:
        return 0.0
    return min(candidates)


def recompute_budget(state: dict[str, Any]) -> dict:
    """Recompute the budget summary from current state fields.

    All prices are converted to the user-selected currency (state.currency,
    default EUR) before summing. The budget itself is assumed to be
    already denominated in that currency (see CLAUDE.md: the selector
    changes the unit, it does not auto-convert the numeric value).

    Returns a BudgetSummary-shaped dict with per-item breakdown,
    items annotated with the target currency, and total in target.
    """
    target = str(state.get("currency") or "EUR").upper()

    # ── Tickets: pick the PICK-tagged option, or cheapest ────────
    tickets = [t for t in (state.get("tickets") or []) if isinstance(t, dict)]
    real_tickets = [t for t in tickets if t.get("tag") != "INFO" and t.get("price", 0) > 0]
    if real_tickets:
        pick = next((t for t in real_tickets if t.get("tag") == "PICK"), None)
        chosen = pick or min(real_tickets, key=lambda t: _item_price_in(t, target))
        ticket_cost = _item_price_in(chosen, target)
    else:
        ticket_cost = 0.0

    # ── Transport: handle ROUNDTRIP (single price) or OUT+RET ────
    transport = [t for t in (state.get("transport") or []) if isinstance(t, dict)]
    roundtrip_cost = _pick_cheapest_in(transport, "ROUNDTRIP", target)
    if roundtrip_cost > 0:
        # google_flights round-trip: price already covers both directions
        flight_cost = roundtrip_cost
    else:
        # One-way searches or mock data: separate OUT + RET
        out_cost = _pick_cheapest_in(transport, "OUT", target)
        ret_cost = _pick_cheapest_in(transport, "RET", target)
        flight_cost = out_cost + ret_cost
    local_cost = sum(
        _item_price_in(t, target) for t in transport
        if t.get("tag") == "LOCAL" and t.get("price", 0) > 0
    )
    transport_cost = flight_cost + local_cost

    # ── Hotel: cheapest real hotel × nights ──────────────────────
    hotel_list = [h for h in (state.get("hotel") or []) if isinstance(h, dict)]
    real_hotels = [
        h for h in hotel_list
        if h.get("tag") != "INFO" and h.get("price_per_night", 0) > 0
    ]
    if real_hotels:
        cheapest = min(
            real_hotels,
            key=lambda h: _item_price_in(h, target, "price_per_night"),
        )
        per_night = _item_price_in(cheapest, target, "price_per_night")
        nights = cheapest.get("nights", 1) or 1
        trip_days = 3 + int(state.get("extra_days", 0) or 0)
        if nights <= 1:
            nights = trip_days
        hotel_cost = per_night * nights
    else:
        hotel_cost = 0.0

    # ── Estimated costs (EUR baselines → convert to target) ──────
    tour_cost = from_eur(_TOUR_EUR, target)
    food_cost = from_eur(_FOOD_EUR, target)
    misc_local = from_eur(_MISC_LOCAL_EUR, target)

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + misc_local
    budget = float(state.get("budget", 2500))
    within = total <= budget

    items = [
        {"name": "Tickets",         "amount": round(ticket_cost, 2),    "currency": target},
        {"name": "Flights",         "amount": round(transport_cost, 2), "currency": target},
        {"name": "Hotel",           "amount": round(hotel_cost, 2),     "currency": target},
        {"name": "Activities",      "amount": round(tour_cost, 2),      "currency": target},
        {"name": "Food (est.)",     "amount": round(food_cost, 2),      "currency": target},
        {"name": "Local transport", "amount": round(misc_local, 2),     "currency": target},
    ]

    tip = ""
    if not within:
        over = total - budget
        tip = f"Over budget by {target} {over:.0f}. Consider a cheaper hotel or GA tickets."

    return {
        "items": items,
        "total": round(total, 2),
        "budget": budget,
        "currency": target,
        "within_budget": within,
        "savings_tip": tip,
    }
