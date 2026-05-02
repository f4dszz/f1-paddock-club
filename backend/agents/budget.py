"""Budget and retry nodes for the planning graph."""

from __future__ import annotations

from state import TravelPlanState
from agents._shared import _msg


# ── budget_agent ─────────────────────────────────────────────────────
def budget_agent(state: TravelPlanState) -> dict:
    """Aggregate costs and check against budget.

    Phase 3: delegates to tools.recompute.recompute_budget() which
    handles real API data (filtering INFO items, picking cheapest
    per category, multiplying hotel by nights).
    """
    from tools.recompute import recompute_budget

    summary = recompute_budget(state)
    total = summary["total"]
    budget = summary["budget"]
    within = summary["within_budget"]
    cur = summary.get("currency", "EUR")
    retry_exhausted = not within and state.get("retry_count", 0) >= 2

    if retry_exhausted:
        text = (
            f"Total {cur} {total:.0f} / {cur} {budget:.0f} — OVER BUDGET "
            "(retries exhausted: no feasible plan found within budget yet)"
        )
    else:
        text = f"Total {cur} {total:.0f} / {cur} {budget:.0f} — {'within budget' if within else 'OVER BUDGET'}"
    return {
        "budget_summary": summary,
        "budget_ok": within,
        "messages": [_msg("budget", text)],
    }


# ── budget_check (conditional edge function) ─────────────────────────
def should_retry_budget(state: TravelPlanState) -> str:
    """Conditional edge: if over budget and retries remain, go back to hotel."""
    if state.get("budget_ok", False):
        return "done"
    if state.get("retry_count", 0) >= 2:
        return "done"  # give up after 2 retries
    return "retry_hotel"


def increment_retry(state: TravelPlanState) -> dict:
    """Increment retry count before re-running hotel search.

    No explicit clearing of hotel/itinerary/tour is needed here —
    those fields use default replace-semantics in state.py, so when
    hotel_agent / itinerary_agent / tour_agent re-run after this node
    their new outputs replace the previous attempt automatically.
    """
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "messages": [_msg("concierge", "Over budget — asking hotel agent for cheaper options...")],
    }
