"""Agent node functions for the F1 travel planning graph.

Each function receives the full TravelPlanState and returns a partial
dict with only the keys it wants to update. LangGraph merges the
updates using the reducers defined on each key.

Phase 1: All agents return mock data.
Phase 2+: Replace mock with real LLM calls and tool invocations.
"""

from __future__ import annotations
import logging
import re

from state import TravelPlanState
from llm import get_llm, provider_label

logger = logging.getLogger(__name__)


_DIRECT_ONLY_RE = re.compile(
    r"\b(only\s+direct|direct\s+only|non[-\s]?stop|no\s+stops?|without\s+stops?)\b"
    r"|直飞|直航|直达|直達|不转机|不要转机|无转机|不中转|不中轉",
    re.IGNORECASE,
)

_KNOWN_HOTEL_BRANDS = (
    "marriott",
    "hilton",
    "hyatt",
    "sheraton",
    "westin",
    "courtyard",
    "holiday inn",
    "intercontinental",
    "万豪",
    "萬豪",
    "希尔顿",
    "希爾頓",
    "凯悦",
    "凱悅",
    "洲际",
    "洲際",
)


def _direct_only_requested(text: str) -> bool:
    return bool(_DIRECT_ONLY_RE.search(text or ""))


def _requested_hotel_brands(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [brand for brand in _KNOWN_HOTEL_BRANDS if brand in lowered]


def _msg(agent: str, text: str) -> dict:
    """Helper to create a streaming status message.

    Also logs the message so every agent status line lands in the
    file-based audit trail, not just in state['messages'].
    """
    logger.info("[%s] %s", agent, text)
    return {"agent": agent, "text": text, "type": "status"}


from tools._trip_dates import trip_nights as _trip_days  # noqa: E402
# `trip_nights(state)` is the single source of truth for how many
# nights a trip spans. It respects explicit depart_date/return_date
# when the user set them, and falls back to the legacy
# "3 weekend days + extra_days" formula otherwise. Keeping the local
# alias `_trip_days` so the agents read naturally.


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

    return {
        "tickets": tickets,
        "messages": [_msg("ticket", f"Found {len(tickets)} ticket options for {state['gp_name']} ({source_summary})")],
    }


# ── transport_agent ──────────────────────────────────────────────────
def _transport_mock(state: TravelPlanState) -> list[dict]:
    """Fallback transport options — shown when every external tool fails.

    Must reflect the user's actual trip (city, dates) instead of
    hardcoded Milan/Monza defaults. Fallback is product behavior:
    when SerpAPI / LLM estimation both error, the user sees these
    strings, so they have to be truthful.
    """
    from tools._trip_dates import compute_trip_dates
    origin = state.get("origin", "") or "your origin"
    city = state.get("gp_city", "") or "destination"
    dates = compute_trip_dates(
        state.get("gp_date", ""),
        state.get("extra_days", 0),
        state.get("depart_date", "") or "",
        state.get("return_date", "") or "",
    )
    out_date = dates.get("outbound_date", "?")
    ret_date = dates.get("return_date", "?")
    return [
        {"tag": "OUT", "summary": f"{origin} → {city}",
         "detail": f"Estimated direct route · {out_date}",
         "price": 485, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "RET", "summary": f"{city} → {origin}",
         "detail": f"Estimated direct route · {ret_date}",
         "price": 520, "currency": "EUR",
         "link": "https://www.google.com/travel/flights"},
        {"tag": "LOCAL", "summary": f"{city} ↔ Circuit",
         "detail": "Local transit (varies by circuit)",
         "price": 5, "currency": "EUR",
         "link": ""},
    ]


def transport_agent(state: TravelPlanState) -> dict:
    """Search for flights and local transport. Parallel with hotel_agent.

    Phase 3: tries tools.search_flights first, falls back to mock.
    """
    origin = state.get("origin", "NYC")
    city = state.get("gp_city", "Milan")
    stops = state.get("stops", "")
    request_text = f"{stops} {state.get('special_requests', '')}"
    max_stops = 0 if _direct_only_requested(request_text) else None

    try:
        from tools.search_flights import search_flights
        from tools._trip_dates import compute_trip_dates
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
        transport, source_summary = search_flights(
            origin=origin, dest=city,
            date=dates["outbound_date"],
            return_date=dates["return_date"],
            stops=max_stops,
        )
    except Exception:
        logger.exception("transport_agent: all tools failed, using mock")
        transport = _transport_mock(state)
        source_summary = "source: mock (all data sources failed)"

    msgs = [_msg("transport", f"Found flights {origin} <-> {city} ({source_summary})")]
    if stops:
        msgs.append(_msg("transport", f"Multi-stop route noted: {stops}"))
    if max_stops == 0:
        msgs.append(_msg("transport", "Applied hard constraint: direct flights only"))

    return {"transport": transport, "messages": msgs}


# ── hotel_agent ──────────────────────────────────────────────────────
def _hotel_mock(state: TravelPlanState, budget_retry: bool = False) -> list[dict]:
    city = state.get("gp_city", "Monza")
    days = _trip_days(state)
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
    requested_brands = _requested_hotel_brands(state.get("special_requests", ""))
    strict_brand = bool(requested_brands)
    brand = " or ".join(requested_brands)

    try:
        from tools.search_hotels import search_hotels
        from tools._trip_dates import compute_trip_dates
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
        max_price = None
        if retry > 0:
            budget_remaining = float(state.get("budget", 2500)) * 0.3
            max_price = budget_remaining / days if days > 0 else None
        hotel, source_summary = search_hotels(
            city=city,
            checkin=dates["hotel_checkin"],
            checkout=dates["hotel_checkout"],
            max_price=max_price,
            brand=brand or None,
            strict_brand=strict_brand,
        )
    except Exception:
        logger.exception("hotel_agent: all tools failed, using mock")
        if strict_brand:
            hotel = []
            source_summary = f"no hotel options matched required brand(s): {brand}"
        else:
            hotel = _hotel_mock(state, budget_retry=(retry > 0))
            source_summary = "source: mock (all data sources failed)"

    if retry > 0:
        return {
            "hotel": hotel,
            "messages": [_msg("hotel", f"Found cheaper options (retry #{retry}, {source_summary})")],
        }

    return {
        "hotel": hotel,
        "messages": [_msg("hotel", f"Found {len(hotel)} stays in {city} ({days} nights, {source_summary})")],
    }


# ── itinerary_agent ──────────────────────────────────────────────────
def _itinerary_mock(state: TravelPlanState) -> list[str]:
    """Fallback itinerary when the LLM is unavailable or fails.

    Respects the user's actual trip length (not fixed at 5 days) and
    stays generic about the destination (not Milan/Como specific) so
    a Baku or Las Vegas trip doesn't get Monza tourism advice.

    The caller labels this output as "generic fallback" in the status
    message so the user knows they're seeing a placeholder rather
    than a curated itinerary.
    """
    city = state.get("gp_city", "") or "the destination"
    nights = _trip_days(state)
    # itinerary slots = nights + 1 (the day you arrive counts)
    days_count = max(nights + 1, 1)

    # Anchor the race day relative to the trip. Convention: the race
    # Sunday lands in the middle/later part — we take "the Sunday day"
    # as the one aligned with gp_date when we can compute it, else
    # put it at day min(3, days_count-1).
    from tools._trip_dates import compute_trip_dates
    try:
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
        from datetime import date as _d
        outbound = _d.fromisoformat(dates["outbound_date"])
        race = _d.fromisoformat(dates["race_date"])
        race_day_index = max((race - outbound).days, 0)
    except Exception:
        race_day_index = min(2, days_count - 1)

    lines: list[str] = []
    for i in range(days_count):
        if i == 0:
            lines.append(f"Day 1: Arrive in {city}. Settle in and get your bearings near the hotel.")
        elif i == race_day_index - 1:
            lines.append(f"Day {i+1}: FP3 + Qualifying at the circuit. Evening in {city}.")
        elif i == race_day_index:
            lines.append(f"Day {i+1}: Race Day. Arrive early, stay for podium, then dinner in {city}.")
        elif i == days_count - 1:
            lines.append(f"Day {i+1}: Check-out, last bites and souvenirs in {city}, depart.")
        else:
            lines.append(f"Day {i+1}: Explore {city} — a sight, a meal, and some downtime.")
    return lines


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
                "messages": [_msg("plan", f"LLM failed ({e.__class__.__name__}), using generic mock itinerary")],
            }
    else:
        days = _itinerary_mock(state)

    label = provider_label() if used_llm else "generic mock"
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

            currency = str(state.get("currency") or "EUR").upper()
            _SYM = {"EUR": "€", "USD": "$", "CNY": "¥"}
            sym = _SYM.get(currency, currency + " ")

            class TourRecs(BaseModel):
                recommendations: list[str] = Field(
                    description=(
                        "One line per recommendation. Format: "
                        f"'<emoji> Name ({sym}price) — short why-it-is-cool note'."
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
                f"'<emoji> Name ({sym}price) — short note'. Use {sym} "
                f"({currency}) for prices (approximate is fine). If a "
                "request above is dietary or accessibility-related, honor "
                "it in your picks."
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
