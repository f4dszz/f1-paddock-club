"""Agent node functions for the F1 travel planning graph.

Each function receives the full TravelPlanState and returns a partial
dict with only the keys it wants to update. LangGraph merges the
updates using the reducers defined on each key.

Phase 1: All agents return mock data.
Phase 2+: Replace mock with real LLM calls and tool invocations.
"""

from __future__ import annotations
import logging

from state import TravelPlanState
from llm import get_llm, provider_label

logger = logging.getLogger(__name__)


def _msg(agent: str, text: str) -> dict:
    """Helper to create a streaming status message.

    Also logs the message so every agent status line lands in the
    file-based audit trail, not just in state['messages'].
    """
    logger.info("[%s] %s", agent, text)
    return {"agent": agent, "text": text, "type": "status"}


def _trip_days(state: TravelPlanState) -> int:
    """Standard race weekend (Fri/Sat/Sun) plus any extra days."""
    return 3 + int(state.get("extra_days", 0) or 0)


# ── parse_input ──────────────────────────────────────────────────────
def parse_input(state: TravelPlanState) -> dict:
    """Validate and normalize user input. First node in the graph."""
    return {
        "messages": [_msg("concierge", f"Planning your {state['gp_name']} trip from {state['origin']}...")],
        "budget_ok": False,
        "retry_count": 0,
    }


# ── ticket_agent ─────────────────────────────────────────────────────
def _ticket_mock(state: TravelPlanState) -> list[dict]:
    return [
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


def ticket_agent(state: TravelPlanState) -> dict:
    """Search for ticket options. Runs before transport/hotel.

    Phase 3: tries tools.search_tickets first, falls back to mock.
    """
    try:
        from tools.search_tickets import search_tickets
        tickets = search_tickets(gp_name=state["gp_name"])
        source = "tools"
    except Exception:
        logger.exception("ticket_agent: tool failed, using mock")
        tickets = _ticket_mock(state)
        source = "mock"

    return {
        "tickets": tickets,
        "messages": [_msg("ticket", f"Found {len(tickets)} ticket options for {state['gp_name']} ({source})")],
    }


# ── transport_agent ──────────────────────────────────────────────────
def _transport_mock(state: TravelPlanState) -> list[dict]:
    origin = state.get("origin", "NYC")
    city = state.get("gp_city", "Milan")
    return [
        {"tag": "OUT", "summary": f"{origin} -> {city} MXP",
         "detail": "Direct - 8h20m - Sep 4", "price": 485, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "RET", "summary": f"{city} MXP -> {origin}",
         "detail": "Direct - 9h45m - Sep 10", "price": 520, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "LOCAL", "summary": f"{city} <-> Circuit",
         "detail": "Trenord S7 - 12min", "price": 5, "currency": "EUR",
         "link": ""},
    ]


def transport_agent(state: TravelPlanState) -> dict:
    """Search for flights and local transport. Parallel with hotel_agent.

    Phase 3: tries tools.search_flights first, falls back to mock.
    """
    origin = state.get("origin", "NYC")
    city = state.get("gp_city", "Milan")
    stops = state.get("stops", "")

    try:
        from tools.search_flights import search_flights
        transport = search_flights(
            origin=origin, dest=city, date=state.get("gp_date", ""),
        )
        source = "tools"
    except Exception:
        logger.exception("transport_agent: tool failed, using mock")
        transport = _transport_mock(state)
        source = "mock"

    msgs = [_msg("transport", f"Found flights {origin} <-> {city} ({source})")]
    if stops:
        msgs.append(_msg("transport", f"Multi-stop route noted: {stops}"))

    return {"transport": transport, "messages": msgs}


# ── hotel_agent ──────────────────────────────────────────────────────
def _hotel_mock(state: TravelPlanState, budget_retry: bool = False) -> list[dict]:
    city = state.get("gp_city", "Monza")
    days = 3 + state.get("extra_days", 2)
    if budget_retry:
        return [
            {"name": f"Budget Hostel {city}", "price_per_night": 55,
             "total_price": 55 * days, "currency": "EUR", "nights": days,
             "distance": "20min bus", "rating": "7.2", "tag": "BUDGET",
             "link": "https://www.booking.com"},
            {"name": f"Airbnb {city} Outskirts", "price_per_night": 65,
             "total_price": 65 * days, "currency": "EUR", "nights": days,
             "distance": "25min train", "rating": "4.3", "tag": "SAVE",
             "link": "https://www.airbnb.com"},
        ]
    return [
        {"name": "Hotel de la Ville", "price_per_night": 135,
         "total_price": 135 * days, "currency": "EUR", "nights": days,
         "distance": "2km to circuit", "rating": "8.4", "tag": "NEAR",
         "link": "https://www.booking.com"},
        {"name": f"Airbnb {city} Central", "price_per_night": 95,
         "total_price": 95 * days, "currency": "EUR", "nights": days,
         "distance": "15min train", "rating": "4.6", "tag": "SAVE",
         "link": "https://www.airbnb.com"},
    ]


def hotel_agent(state: TravelPlanState) -> dict:
    """Search for hotels. Parallel with transport_agent.

    Phase 3: tries tools.search_hotels first, falls back to mock.
    On budget retry (retry_count > 0), passes a lower max_price hint
    to the tool so it returns cheaper options.
    """
    retry = state.get("retry_count", 0)
    city = state.get("gp_city", "Monza")
    days = _trip_days(state)

    try:
        from tools.search_hotels import search_hotels
        # On retry, hint the tool to find cheaper options
        max_price = None
        if retry > 0:
            budget_remaining = float(state.get("budget", 2500)) * 0.3  # ~30% for hotel
            max_price = budget_remaining / days if days > 0 else None
        hotel = search_hotels(
            city=city,
            checkin=state.get("gp_date", ""),
            checkout="",  # TODO: compute from gp_date + days
            max_price=max_price,
        )
        source = "tools"
    except Exception:
        logger.exception("hotel_agent: tool failed, using mock")
        hotel = _hotel_mock(state, budget_retry=(retry > 0))
        source = "mock"

    if retry > 0:
        return {
            "hotel": hotel,
            "messages": [_msg("hotel", f"Found cheaper options (retry #{retry}, {source})")],
        }

    return {
        "hotel": hotel,
        "messages": [_msg("hotel", f"Found {len(hotel)} stays in {city} ({days} nights, {source})")],
    }


# ── itinerary_agent ──────────────────────────────────────────────────
def _itinerary_mock(state: TravelPlanState) -> list[str]:
    return [
        "Day 1 (Fri): Arrive + settle in. Evening: explore old town.",
        "Day 2 (Sat): FP3 + Qualifying. Afternoon: Parco di Monza.",
        "Day 3 (Sun): Race Day! Arrive early. Post-race track walk.",
        "Day 4 (Mon): Milan city day — Duomo, Galleria, Last Supper.",
        "Day 5 (Tue): Lake Como day trip — Bellagio, boat tour.",
    ]


def itinerary_agent(state: TravelPlanState) -> dict:
    """Plan day-by-day schedule. Parallel with tour_agent.

    Phase 2: Real Claude call via langchain-anthropic, with mock fallback
    when ANTHROPIC_API_KEY is missing or the call fails.
    """
    llm = get_llm(temperature=0.7, max_tokens=900)
    days_count = _trip_days(state)
    used_llm = False

    if llm is not None:
        try:
            from pydantic import BaseModel, Field

            class Itinerary(BaseModel):
                days: list[str] = Field(
                    description=(
                        "One concise line per day starting with "
                        "'Day N (DayOfWeek): '. Max ~140 chars per line."
                    )
                )

            chosen_hotel = ""
            if state.get("hotel"):
                chosen_hotel = state["hotel"][0].get("name", "")

            stops = state.get("stops") or ""
            special = state.get("special_requests") or ""

            system = (
                "You are an expert travel planner curating a Formula 1 fan "
                "trip. You produce tight, practical day-by-day itineraries. "
                "Race weekends always run Friday (FP1/FP2), Saturday "
                "(FP3/Qualifying), Sunday (Race)."
            )
            user = (
                f"Plan a {days_count}-day itinerary for the {state['gp_name']} "
                f"in {state['gp_city']} (race date: {state['gp_date']}).\n"
                f"Origin: {state.get('origin', '')}\n"
                f"Hotel base: {chosen_hotel or 'TBD'}\n"
                f"Stops / multi-city plan: {stops or 'none'}\n"
                f"Special requests: {special or 'none'}\n\n"
                "Cover all three race-weekend sessions appropriately. "
                "Use the extra days for the city and nearby day trips. "
                "Each day = ONE line, starting 'Day N (DayOfWeek): '. "
                f"Return exactly {days_count} day lines."
            )

            logger.info("itinerary_agent calling LLM (provider=%s, days=%d)", provider_label(), days_count)
            structured = llm.with_structured_output(Itinerary)
            result = structured.invoke(
                [("system", system), ("user", user)]
            )
            days = [d.strip() for d in result.days if d and d.strip()]
            if not days:
                raise ValueError("LLM returned empty itinerary")
            used_llm = True
        except Exception as e:
            logger.exception("itinerary_agent LLM call failed, falling back to mock")
            days = _itinerary_mock(state)
            return {
                "itinerary": days,
                "messages": [_msg("plan", f"LLM failed ({e.__class__.__name__}), used mock itinerary")],
            }
    else:
        days = _itinerary_mock(state)

    label = provider_label() if used_llm else "mock"
    return {
        "itinerary": days,
        "messages": [_msg("plan", f"Created {len(days)}-day itinerary ({label})")],
    }


# ── tour_agent ───────────────────────────────────────────────────────
def _tour_mock(state: TravelPlanState) -> list[str]:
    recs = [
        "🏎 Monza Circuit Museum (€15) — inside the track, race history",
        "🏛 Duomo Rooftop (€14) — panoramic Milan views",
        "🍕 Luini Panzerotti (€3) — legendary street food",
        "🌊 Como Boat Tour (€12) — Villa Balbianello",
    ]
    special = state.get("special_requests", "")
    if special:
        recs.append(f"📝 Noted your request: {special}")
    return recs


def tour_agent(state: TravelPlanState) -> dict:
    """Recommend sights and restaurants. Parallel with itinerary_agent.

    Phase 2: Real Claude call via langchain-anthropic, with mock fallback.
    """
    llm = get_llm(temperature=0.8, max_tokens=900)
    days_count = _trip_days(state)
    used_llm = False

    if llm is not None:
        try:
            from pydantic import BaseModel, Field

            class TourRecs(BaseModel):
                recommendations: list[str] = Field(
                    description=(
                        "One line per recommendation. Format: "
                        "'<emoji> Name (€price) — short why-it-is-cool note'."
                    )
                )

            special = state.get("special_requests") or ""

            system = (
                "You are a savvy local tour curator who knows the area "
                "around F1 Grand Prix host cities. Recommend the best "
                "sights, experiences and food for a visiting fan. Be "
                "specific (real names, real venues), concise, and tasteful."
            )
            user = (
                f"Recommend 5-6 must-do items for someone attending the "
                f"{state['gp_name']} in {state['gp_city']}. "
                f"They have {days_count} days total including the race.\n"
                f"Special requests: {special or 'none'}\n\n"
                "Mix iconic sights, a hidden gem, a local food spot, and a "
                "motorsport-flavored pick. Each line must follow exactly: "
                "'<emoji> Name (€price) — short note'. Use € for prices "
                "(approximate is fine). If a request above is dietary or "
                "accessibility-related, honor it in your picks."
            )

            logger.info("tour_agent calling LLM (provider=%s, city=%s)", provider_label(), state.get("gp_city", ""))
            structured = llm.with_structured_output(TourRecs)
            result = structured.invoke(
                [("system", system), ("user", user)]
            )
            recs = [r.strip() for r in result.recommendations if r and r.strip()]
            if not recs:
                raise ValueError("LLM returned empty recommendations")
            used_llm = True
        except Exception as e:
            logger.exception("tour_agent LLM call failed, falling back to mock")
            recs = _tour_mock(state)
            return {
                "tour": recs,
                "messages": [_msg("tour", f"LLM failed ({e.__class__.__name__}), used mock recs")],
            }
    else:
        recs = _tour_mock(state)

    label = provider_label() if used_llm else "mock"
    return {
        "tour": recs,
        "messages": [_msg("tour", f"Curated {len(recs)} recommendations ({label})")],
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
