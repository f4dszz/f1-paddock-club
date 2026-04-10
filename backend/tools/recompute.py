"""Pure-function helpers for budget recomputation and plan validation.

WHY these functions need to be smarter now (Phase 3):
With mock data, transport had exactly 3 items (OUT + RET + LOCAL) and
hotel had exactly 2 items. budget_agent could just sum(transport) and
min(hotel). With real API data, transport might have 6 outbound options,
3 INFO links from Bing, and no return flight. Hotel might have 5 real
hotels plus 3 Bing INFO items with price=0.

The recompute logic now:
- Filters out INFO/supplementary items (tag="INFO" or _source="bing" with price=0)
- Picks the cheapest OUT flight + cheapest RET flight (if any) + LOCAL
- Picks the cheapest real hotel and multiplies by nights
- All other agents' costs use sensible defaults
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _pick_cheapest(items: list[dict], tag_filter: str) -> float:
    """Pick the cheapest item matching a tag, ignoring INFO/zero-price items."""
    candidates = [
        t for t in items
        if t.get("tag") == tag_filter
        and t.get("price", 0) > 0
    ]
    if not candidates:
        return 0
    return min(c["price"] for c in candidates)


def recompute_budget(state: dict[str, Any]) -> dict:
    """Recompute the budget summary from current state fields.

    Handles both mock data (simple sums) and real API data (needs
    filtering and picking logic).

    Returns a BudgetSummary-shaped dict.
    """
    # ── Tickets: pick the PICK-tagged option, or cheapest ────────
    tickets = state.get("tickets") or []
    real_tickets = [t for t in tickets if t.get("tag") != "INFO" and t.get("price", 0) > 0]
    if real_tickets:
        pick = next((t for t in real_tickets if t.get("tag") == "PICK"), None)
        ticket_cost = pick["price"] if pick else min(t["price"] for t in real_tickets)
    else:
        ticket_cost = 0

    # ── Transport: cheapest OUT + cheapest RET + sum of LOCAL ────
    transport = state.get("transport") or []
    out_cost = _pick_cheapest(transport, "OUT")
    ret_cost = _pick_cheapest(transport, "RET")
    local_cost = sum(
        t.get("price", 0) for t in transport
        if t.get("tag") == "LOCAL" and t.get("price", 0) > 0
    )
    transport_cost = out_cost + ret_cost + local_cost

    # ── Hotel: cheapest real hotel × nights ──────────────────────
    hotel_list = state.get("hotel") or []
    real_hotels = [
        h for h in hotel_list
        if h.get("tag") != "INFO" and h.get("price_per_night", 0) > 0
    ]
    if real_hotels:
        cheapest = min(real_hotels, key=lambda h: h["price_per_night"])
        nights = cheapest.get("nights", 1) or 1
        # If nights is 1 (per-night from API), use trip days instead
        trip_days = 3 + int(state.get("extra_days", 0) or 0)
        if nights <= 1:
            nights = trip_days
        hotel_cost = cheapest["price_per_night"] * nights
    else:
        hotel_cost = 0

    # ── Estimated costs ──────────────────────────────────────────
    tour_cost = 44
    food_cost = 240
    misc_local = 40

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + misc_local
    budget = float(state.get("budget", 2500))
    within = total <= budget

    items = [
        {"name": "Tickets", "amount": ticket_cost},
        {"name": "Flights", "amount": transport_cost},
        {"name": "Hotel", "amount": hotel_cost},
        {"name": "Activities", "amount": tour_cost},
        {"name": "Food (est.)", "amount": food_cost},
        {"name": "Local transport", "amount": misc_local},
    ]

    return {
        "items": items,
        "total": total,
        "budget": budget,
        "currency": "EUR",
        "within_budget": within,
        "savings_tip": "" if within else "Consider a cheaper hotel or GA tickets to save money.",
    }
