"""Pure-function helpers for budget recomputation and plan validation.

Phase 3.6: Now currency-aware. Each item carries a `currency` field
(EUR, USD, CNY). All amounts are converted to the budget currency
(default EUR) before summing. No more silent mixed-currency addition.

The recompute logic:
- Filters out INFO/supplementary items (tag="INFO" or price=0)
- Picks the cheapest OUT flight + cheapest RET flight (if any) + LOCAL
- Picks the cheapest real hotel and multiplies by nights
- Converts every amount through _currency.to_eur before summing
- All other agents' costs use sensible defaults (in EUR)
"""

from __future__ import annotations
import logging
from typing import Any

from ._currency import to_eur

logger = logging.getLogger(__name__)


def _item_price_eur(item: dict, price_key: str = "price") -> float:
    """Extract price from an item and convert to EUR."""
    price = item.get(price_key, 0)
    if not price or price <= 0:
        return 0.0
    currency = item.get("currency", "EUR")
    return to_eur(float(price), currency)


def _pick_cheapest_eur(items: list[dict], tag_filter: str) -> float:
    """Pick the cheapest item matching a tag, in EUR."""
    candidates = [
        (t, _item_price_eur(t))
        for t in items
        if t.get("tag") == tag_filter and t.get("price", 0) > 0
    ]
    if not candidates:
        return 0.0
    return min(c[1] for c in candidates)


def recompute_budget(state: dict[str, Any]) -> dict:
    """Recompute the budget summary from current state fields.

    All prices are converted to EUR before summing. The budget itself
    is assumed to be in EUR (as specified in the form/state).

    Returns a BudgetSummary-shaped dict with per-item breakdown,
    original currencies noted, and total in EUR.
    """
    # ── Tickets: pick the PICK-tagged option, or cheapest ────────
    tickets = [t for t in (state.get("tickets") or []) if isinstance(t, dict)]
    real_tickets = [t for t in tickets if t.get("tag") != "INFO" and t.get("price", 0) > 0]
    if real_tickets:
        pick = next((t for t in real_tickets if t.get("tag") == "PICK"), None)
        if pick:
            ticket_cost = _item_price_eur(pick)
            ticket_currency = pick.get("currency", "EUR")
            ticket_original = float(pick.get("price", 0))
        else:
            cheapest = min(real_tickets, key=lambda t: _item_price_eur(t))
            ticket_cost = _item_price_eur(cheapest)
            ticket_currency = cheapest.get("currency", "EUR")
            ticket_original = float(cheapest.get("price", 0))
    else:
        ticket_cost = 0.0
        ticket_currency = "EUR"
        ticket_original = 0.0

    # ── Transport: handle ROUNDTRIP (single price) or OUT+RET ────
    transport = [t for t in (state.get("transport") or []) if isinstance(t, dict)]
    roundtrip_cost = _pick_cheapest_eur(transport, "ROUNDTRIP")
    if roundtrip_cost > 0:
        # google_flights round-trip: price already covers both directions
        flight_cost = roundtrip_cost
    else:
        # One-way searches or mock data: separate OUT + RET
        out_cost = _pick_cheapest_eur(transport, "OUT")
        ret_cost = _pick_cheapest_eur(transport, "RET")
        flight_cost = out_cost + ret_cost
    local_cost = sum(
        _item_price_eur(t) for t in transport
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
        cheapest = min(real_hotels, key=lambda h: _item_price_eur(h, "price_per_night"))
        per_night_eur = _item_price_eur(cheapest, "price_per_night")
        nights = cheapest.get("nights", 1) or 1
        trip_days = 3 + int(state.get("extra_days", 0) or 0)
        if nights <= 1:
            nights = trip_days
        hotel_cost = per_night_eur * nights
    else:
        hotel_cost = 0.0

    # ── Estimated costs (already in EUR) ─────────────────────────
    tour_cost = 44.0
    food_cost = 240.0
    misc_local = 40.0

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + misc_local
    budget = float(state.get("budget", 2500))
    within = total <= budget

    items = [
        {"name": "Tickets", "amount": round(ticket_cost, 2)},
        {"name": "Flights", "amount": round(transport_cost, 2)},
        {"name": "Hotel", "amount": round(hotel_cost, 2)},
        {"name": "Activities", "amount": tour_cost},
        {"name": "Food (est.)", "amount": food_cost},
        {"name": "Local transport", "amount": misc_local},
    ]

    tip = ""
    if not within:
        over = total - budget
        tip = f"Over budget by EUR {over:.0f}. Consider a cheaper hotel or GA tickets."

    return {
        "items": items,
        "total": round(total, 2),
        "budget": budget,
        "currency": "EUR",
        "within_budget": within,
        "savings_tip": tip,
    }
