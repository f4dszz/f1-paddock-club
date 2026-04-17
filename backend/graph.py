"""LangGraph orchestrator for the F1 Travel Planning pipeline.

Graph structure:
    parse_input
        ↓
    ticket_agent
        ↓
    ┌─────────────────┐
    │ transport_agent  │  (parallel)
    │ hotel_agent      │
    └─────────────────┘
        ↓
    ┌─────────────────┐
    │ itinerary_agent  │  (parallel)
    │ tour_agent       │
    └─────────────────┘
        ↓
    budget_agent
        ↓
    [budget_ok?] ──no──→ increment_retry → hotel_agent (loop)
        ↓ yes
       END
"""

import logging
import sys

from langgraph.graph import StateGraph, START, END

from logging_config import setup_logging
from state import TravelPlanState
from agents import (
    parse_input,
    ticket_agent,
    transport_agent,
    hotel_agent,
    itinerary_agent,
    tour_agent,
    budget_agent,
    should_retry_budget,
    increment_retry,
)

# File logging is initialized only when this module is the entry point
# (CLI test via `python graph.py`) or when the FastAPI app starts up.
# Library imports (e.g. `from graph import plan_trip` in a script)
# do not write to the log file. See logging_config.setup_logging.
logger = logging.getLogger(__name__)


def _configure_console_output() -> None:
    """Avoid demo crashes on terminals that cannot encode Unicode glyphs."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            continue


def build_graph() -> StateGraph:
    """Build and compile the travel planning graph."""

    builder = StateGraph(TravelPlanState)

    # ── Add all nodes ──
    builder.add_node("parse_input", parse_input)
    builder.add_node("ticket_agent", ticket_agent)
    builder.add_node("transport_agent", transport_agent)
    builder.add_node("hotel_agent", hotel_agent)
    builder.add_node("itinerary_agent", itinerary_agent)
    builder.add_node("tour_agent", tour_agent)
    builder.add_node("budget_agent", budget_agent)
    builder.add_node("increment_retry", increment_retry)

    # ── Sequential: START → parse → tickets ──
    builder.add_edge(START, "parse_input")
    builder.add_edge("parse_input", "ticket_agent")

    # ── Parallel tier 1: tickets → [transport, hotel] ──
    builder.add_edge("ticket_agent", "transport_agent")
    builder.add_edge("ticket_agent", "hotel_agent")

    # ── Parallel tier 2: [transport, hotel] → [itinerary, tour] ──
    # Both transport and hotel must finish before itinerary/tour start.
    # LangGraph waits for all incoming edges automatically.
    builder.add_edge("transport_agent", "itinerary_agent")
    builder.add_edge("hotel_agent", "itinerary_agent")
    builder.add_edge("transport_agent", "tour_agent")
    builder.add_edge("hotel_agent", "tour_agent")

    # ── Converge: [itinerary, tour] → budget ──
    builder.add_edge("itinerary_agent", "budget_agent")
    builder.add_edge("tour_agent", "budget_agent")

    # ── Conditional: budget check ──
    builder.add_conditional_edges(
        "budget_agent",
        should_retry_budget,
        {
            "done": END,
            "retry_hotel": "increment_retry",
        },
    )

    # ── Retry loop: increment → hotel → itinerary/tour → budget ──
    builder.add_edge("increment_retry", "hotel_agent")

    return builder.compile()


# ── Convenience: run the graph ──

def plan_trip(user_input: dict) -> dict:
    """Run the full planning pipeline with user input.

    Args:
        user_input: Dict with keys matching TravelPlanState input fields:
            gp_name, gp_city, gp_date, origin, budget, currency,
            stand_pref, extra_days, stops, special_requests

    Returns:
        Final TravelPlanState with all agent outputs populated.
    """
    graph = build_graph()

    initial_state: TravelPlanState = {
        # User input
        "gp_name": user_input.get("gp_name", "Italian GP"),
        "gp_city": user_input.get("gp_city", "Monza"),
        "gp_date": user_input.get("gp_date", "Sep 6"),
        "origin": user_input.get("origin", "New York"),
        "budget": float(user_input.get("budget", 2500)),
        "currency": user_input.get("currency", "EUR"),
        "stand_pref": user_input.get("stand_pref", "any"),
        "extra_days": int(user_input.get("extra_days", 2)),
        "stops": user_input.get("stops", ""),
        "special_requests": user_input.get("special_requests", ""),
        # Agent outputs (empty, will be filled)
        "tickets": [],
        "transport": [],
        "hotel": [],
        "itinerary": [],
        "tour": [],
        "budget_summary": None,
        # Control
        "budget_ok": False,
        "retry_count": 0,
        "messages": [],
    }

    logger.info(
        "plan_trip start gp=%s city=%s origin=%s budget=%s %s extra_days=%s",
        initial_state["gp_name"],
        initial_state["gp_city"],
        initial_state["origin"],
        initial_state["budget"],
        initial_state["currency"],
        initial_state["extra_days"],
    )
    result = graph.invoke(initial_state)
    bs = result.get("budget_summary") or {}
    logger.info(
        "plan_trip done total=%s budget=%s within=%s retries=%s",
        bs.get("total"),
        bs.get("budget"),
        bs.get("within_budget"),
        result.get("retry_count", 0),
    )
    return result


# ── CLI test ──

if __name__ == "__main__":
    import json

    _configure_console_output()
    setup_logging()

    result = plan_trip({
        "gp_name": "Italian GP",
        "gp_city": "Monza",
        "gp_date": "Sep 6",
        "origin": "New York",
        "budget": 2500,
        "currency": "EUR",
        "stand_pref": "mid",
        "extra_days": 2,
        "stops": "Milan 2 days → Lake Como → Monza",
        "special_requests": "Wheelchair accessible hotel, vegetarian restaurants",
    })

    print("\n=== MESSAGES (execution trace) ===")
    for msg in result["messages"]:
        print(f"  [{msg['agent']}] {msg['text']}")

    print("\n=== TICKETS ===")
    for t in result["tickets"]:
        print(f"  {t['tag']:6s} {t['name']:25s} €{t['price']}")

    print("\n=== TRANSPORT ===")
    for t in result["transport"]:
        print(f"  {t['tag']:6s} {t['summary']:25s} €{t['price']}")

    print("\n=== HOTEL ===")
    for h in result["hotel"]:
        print(f"  {h['tag']:6s} {h['name']:25s} €{h['total_price']} ({h['nights']}n)")

    print("\n=== ITINERARY ===")
    for line in result["itinerary"]:
        print(f"  {line}")

    print("\n=== TOUR ===")
    for line in result["tour"]:
        print(f"  {line}")

    print("\n=== BUDGET ===")
    bs = result["budget_summary"]
    if bs:
        for item in bs["items"]:
            print(f"  {item['name']:20s} €{item['amount']}")
        print(f"  {'─'*30}")
        print(f"  {'Total':20s} €{bs['total']:.0f} / €{bs['budget']:.0f}")
        print(f"  Status: {'✓ Within budget' if bs['within_budget'] else '✗ Over budget'}")
        if bs["savings_tip"]:
            print(f"  Tip: {bs['savings_tip']}")
