"""Pure-function helpers for budget recomputation and plan validation.

These are NOT cached — they're deterministic computations over the
current state, not external API calls. They exist as tool functions
so the refinement agent (Lane 2) can call them after updating one
part of the plan (e.g., swapping hotels).

Usage:
    from tools.recompute import recompute_budget
    summary = recompute_budget(state)
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def recompute_budget(state: dict[str, Any]) -> dict:
    """Recompute the budget summary from current state fields.

    This is extracted from the existing budget_agent logic so both
    Lane 1 (budget_agent node) and Lane 2 (refinement agent tool)
    can use the same calculation.

    Args:
        state: A dict with at least tickets, transport, hotel, budget keys.

    Returns:
        A BudgetSummary-shaped dict:
        {"items": [...], "total": float, "budget": float,
         "currency": "EUR", "within_budget": bool, "savings_tip": str}
    """
    # Pick the recommended ticket (index 1 = "PICK" tag by convention)
    tickets = state.get("tickets") or []
    ticket_cost = tickets[1]["price"] if len(tickets) > 1 else 0

    transport_cost = sum(t["price"] for t in (state.get("transport") or []))

    hotel_list = state.get("hotel") or []
    hotel_cost = min(h["total_price"] for h in hotel_list) if hotel_list else 0

    # Estimated costs for items we don't have real data for yet
    tour_cost = 44    # placeholder from mock era
    food_cost = 240   # placeholder
    local_cost = 40   # placeholder

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + local_cost
    budget = float(state.get("budget", 2500))
    within = total <= budget

    items = [
        {"name": "Tickets", "amount": ticket_cost},
        {"name": "Flights", "amount": transport_cost},
        {"name": "Hotel", "amount": hotel_cost},
        {"name": "Activities", "amount": tour_cost},
        {"name": "Food (est.)", "amount": food_cost},
        {"name": "Local transport", "amount": local_cost},
    ]

    return {
        "items": items,
        "total": total,
        "budget": budget,
        "currency": "EUR",
        "within_budget": within,
        "savings_tip": "" if within else "Consider a cheaper hotel or GA tickets to save money.",
    }
