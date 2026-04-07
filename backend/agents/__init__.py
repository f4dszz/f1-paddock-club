"""Agent node functions for the F1 travel planning graph.

Each function receives the full TravelPlanState and returns a partial
dict with only the keys it wants to update. LangGraph merges the
updates using the reducers defined on each key.

Phase 1: All agents return mock data.
Phase 2+: Replace mock with real LLM calls and tool invocations.
"""

from __future__ import annotations
from state import TravelPlanState


def _msg(agent: str, text: str) -> dict:
    """Helper to create a streaming status message."""
    return {"agent": agent, "text": text, "type": "status"}


# ── parse_input ──────────────────────────────────────────────────────
def parse_input(state: TravelPlanState) -> dict:
    """Validate and normalize user input. First node in the graph."""
    return {
        "messages": [_msg("concierge", f"Planning your {state['gp_name']} trip from {state['origin']}...")],
        "budget_ok": False,
        "retry_count": 0,
    }


# ── ticket_agent ─────────────────────────────────────────────────────
def ticket_agent(state: TravelPlanState) -> dict:
    """Search for ticket options. Runs before transport/hotel."""
    # TODO: Replace with real tool call — search_tickets(gp_name, year)
    tickets = [
        {"name": "General Admission", "price": 195, "currency": "EUR",
         "section": "Free roaming", "tag": "VALUE",
         "link": "https://tickets.formula1.com"},
        {"name": "Tribuna 25", "price": 380, "currency": "EUR",
         "section": "T2 braking zone", "tag": "PICK",
         "link": "https://tickets.formula1.com"},
        {"name": "Main Grandstand", "price": 620, "currency": "EUR",
         "section": "Pit lane + podium", "tag": "VIP",
         "link": "https://tickets.formula1.com"},
    ]
    return {
        "tickets": tickets,
        "messages": [_msg("ticket", f"Found {len(tickets)} ticket options for {state['gp_name']}")],
    }


# ── transport_agent ──────────────────────────────────────────────────
def transport_agent(state: TravelPlanState) -> dict:
    """Search for flights and local transport. Parallel with hotel_agent."""
    # TODO: Replace with search_flights tool
    origin = state.get("origin", "NYC")
    city = state.get("gp_city", "Milan")
    stops = state.get("stops", "")

    transport = [
        {"tag": "OUT", "summary": f"{origin} → {city} MXP",
         "detail": "Direct · 8h20m · Sep 4", "price": 485, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "RET", "summary": f"{city} MXP → {origin}",
         "detail": "Direct · 9h45m · Sep 10", "price": 520, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "LOCAL", "summary": f"{city} ↔ Circuit",
         "detail": "Trenord S7 · 12min", "price": 5, "currency": "EUR",
         "link": ""},
    ]

    msgs = [_msg("transport", f"Found flights {origin} ↔ {city}")]
    if stops:
        msgs.append(_msg("transport", f"Multi-stop route noted: {stops}"))

    return {"transport": transport, "messages": msgs}


# ── hotel_agent ──────────────────────────────────────────────────────
def hotel_agent(state: TravelPlanState) -> dict:
    """Search for hotels. Parallel with transport_agent."""
    # TODO: Replace with search_hotels tool
    retry = state.get("retry_count", 0)
    city = state.get("gp_city", "Monza")
    days = 3 + state.get("extra_days", 2)

    if retry > 0:
        # Budget retry — return cheaper options
        hotel = [
            {"name": f"Budget Hostel {city}", "price_per_night": 55,
             "total_price": 55 * days, "currency": "EUR", "nights": days,
             "distance": "20min bus", "rating": "7.2★", "tag": "BUDGET",
             "link": "https://www.booking.com"},
            {"name": f"Airbnb {city} Outskirts", "price_per_night": 65,
             "total_price": 65 * days, "currency": "EUR", "nights": days,
             "distance": "25min train", "rating": "4.3★", "tag": "SAVE",
             "link": "https://www.airbnb.com"},
        ]
        return {
            "hotel": hotel,
            "messages": [_msg("hotel", f"Found cheaper options (retry #{retry})")],
        }

    hotel = [
        {"name": "Hotel de la Ville", "price_per_night": 135,
         "total_price": 135 * days, "currency": "EUR", "nights": days,
         "distance": "2km to circuit", "rating": "8.4★", "tag": "NEAR",
         "link": "https://www.booking.com"},
        {"name": f"Airbnb {city} Central", "price_per_night": 95,
         "total_price": 95 * days, "currency": "EUR", "nights": days,
         "distance": "15min train", "rating": "4.6★", "tag": "SAVE",
         "link": "https://www.airbnb.com"},
    ]
    return {
        "hotel": hotel,
        "messages": [_msg("hotel", f"Found {len(hotel)} stays in {city} ({days} nights)")],
    }


# ── itinerary_agent ──────────────────────────────────────────────────
def itinerary_agent(state: TravelPlanState) -> dict:
    """Plan day-by-day schedule. Parallel with tour_agent."""
    # TODO: Replace with real LLM call
    days = [
        "Day 1 (Fri): Arrive + settle in. Evening: explore old town.",
        "Day 2 (Sat): FP3 + Qualifying. Afternoon: Parco di Monza.",
        "Day 3 (Sun): Race Day! Arrive early. Post-race track walk.",
        "Day 4 (Mon): Milan city day — Duomo, Galleria, Last Supper.",
        "Day 5 (Tue): Lake Como day trip — Bellagio, boat tour.",
    ]
    return {
        "itinerary": days,
        "messages": [_msg("plan", f"Created {len(days)}-day itinerary")],
    }


# ── tour_agent ───────────────────────────────────────────────────────
def tour_agent(state: TravelPlanState) -> dict:
    """Recommend sights and restaurants. Parallel with itinerary_agent."""
    # TODO: Replace with real LLM call
    recs = [
        "🏎 Monza Circuit Museum (€15) — inside the track, race history",
        "🏛 Duomo Rooftop (€14) — panoramic Milan views",
        "🍕 Luini Panzerotti (€3) — legendary street food",
        "🌊 Como Boat Tour (€12) — Villa Balbianello",
    ]
    special = state.get("special_requests", "")
    if special:
        recs.append(f"📝 Noted your request: {special}")

    return {
        "tour": recs,
        "messages": [_msg("tour", f"Curated {len(recs)} recommendations")],
    }


# ── budget_agent ─────────────────────────────────────────────────────
def budget_agent(state: TravelPlanState) -> dict:
    """Aggregate costs and check against budget."""
    # Pick the recommended ticket (index 1 = "PICK")
    ticket_cost = state["tickets"][1]["price"] if len(state["tickets"]) > 1 else 0
    transport_cost = sum(t["price"] for t in state.get("transport", []))
    hotel_cost = min(h["total_price"] for h in state.get("hotel", [])) if state.get("hotel") else 0
    tour_cost = 44   # estimated from tour items
    food_cost = 240  # estimated
    local_cost = 40  # estimated

    total = ticket_cost + transport_cost + hotel_cost + tour_cost + food_cost + local_cost
    budget = state.get("budget", 2500)
    within = total <= budget

    items = [
        {"name": "Tickets", "amount": ticket_cost},
        {"name": "Flights", "amount": transport_cost},
        {"name": "Hotel", "amount": hotel_cost},
        {"name": "Activities", "amount": tour_cost},
        {"name": "Food (est.)", "amount": food_cost},
        {"name": "Local transport", "amount": local_cost},
    ]

    summary = {
        "items": items,
        "total": total,
        "budget": budget,
        "currency": "EUR",
        "within_budget": within,
        "savings_tip": "" if within else "Consider a cheaper hotel or GA tickets to save money.",
    }

    return {
        "budget_summary": summary,
        "budget_ok": within,
        "messages": [_msg("budget", f"Total €{total:.0f} / €{budget:.0f} — {'within budget ✓' if within else 'OVER BUDGET'}")],
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
    """Increment retry count before re-running hotel search."""
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "hotel": [],  # clear old hotel results
        "messages": [_msg("concierge", "Over budget — asking hotel agent for cheaper options...")],
    }
