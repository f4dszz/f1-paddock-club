"""Ticket agent node."""

from __future__ import annotations

import logging

from state import TravelPlanState
from agents._shared import _msg
from tools._rationale import build_ticket_rationale

logger = logging.getLogger(__name__)


# ── ticket_agent ─────────────────────────────────────────────────────
def _ticket_mock(state: TravelPlanState) -> list[dict]:
    return [
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


def ticket_agent(state: TravelPlanState) -> dict:
    """Search for ticket options. Runs before transport/hotel.

    Phase 3: tries tools.search_tickets first (parallel Firecrawl +
    Bing → LLM extract → LLM estimate), falls back to mock.
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
