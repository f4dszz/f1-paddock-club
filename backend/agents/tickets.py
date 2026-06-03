"""Ticket agent node."""

from __future__ import annotations

import logging
import os

from state import TravelPlanState
from agents._shared import _msg
from tools._rationale import build_ticket_rationale

logger = logging.getLogger(__name__)


# ── ticket_agent ─────────────────────────────────────────────────────
def _ticket_mock(state: TravelPlanState) -> list[dict]:
    tickets: list[dict] = [
        {"name": "General Admission", "price": 195, "currency": "EUR",
         "section": "Free roaming", "tag": "VALUE",
         "link": "https://tickets.formula1.com/en",
         "provider": "Formula 1", "link_type": "search",
         "booking_confidence": "medium"},
        {"name": "Tribuna 25", "price": 380, "currency": "EUR",
         "section": "T2 braking zone", "tag": "PICK",
         "link": "https://tickets.formula1.com/en",
         "provider": "Formula 1", "link_type": "search",
         "booking_confidence": "medium"},
        {"name": "Main Grandstand", "price": 620, "currency": "EUR",
         "section": "Pit lane + podium", "tag": "VIP",
         "link": "https://tickets.formula1.com/en",
         "provider": "Formula 1", "link_type": "search",
         "booking_confidence": "medium"},
    ]

    # Deterministic test-mode unpriced option: produces an item whose
    # price is missing, so selecting it forces budget_summary.quote_complete=False
    # with "Tickets" in missing_price_categories (see tools/recompute.py).
    # Gated by APP_ENV=test + LLM_STUB_MODE=1 — same gate the transport
    # mock uses for its connecting-flight test option, so production
    # never sees a zero-price ticket.
    if (
        os.environ.get("APP_ENV") == "test"
        and os.environ.get("LLM_STUB_MODE") == "1"
    ):
        tickets.append({
            "name": "Paddock Club (price on request)",
            "price": 0,
            "currency": "EUR",
            "section": "Hospitality suite — quote required",
            "tag": "VIP",
            "link": "https://tickets.formula1.com/en",
            "provider": "Formula 1", "link_type": "search",
            "booking_confidence": "low",
        })

    return tickets


def ticket_agent(state: TravelPlanState) -> dict:
    """Search for ticket options. Runs before transport/hotel.

    Tries tools.search_tickets first (parallel Firecrawl + SerpAPI Google
    Search → LLM extract → LLM estimate), falls back to mock.
    """
    try:
        from tools.search_tickets import search_tickets
        tickets, source_summary = search_tickets(gp_name=state["gp_name"])
    except Exception:
        logger.exception("ticket_agent: all tools failed, using mock")
        tickets = _ticket_mock(state)
        source_summary = "source: mock (all data sources failed)"

    for ticket in tickets:
        if isinstance(ticket, dict):
            ticket["_rationale"] = build_ticket_rationale(ticket, tickets, state)

    return {
        "tickets": tickets,
        "messages": [_msg("ticket", f"Found {len(tickets)} ticket options for {state['gp_name']} ({source_summary})")],
    }
