"""Itinerary agent node."""

from __future__ import annotations

import logging

from state import TravelPlanState
from llm import get_llm, provider_label
from agents._shared import _msg, _trip_days, wrap_untrusted_text, UNTRUSTED_TEXT_NOTE

logger = logging.getLogger(__name__)


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

    Real LLM call via the configured provider, with mock fallback when the
    provider key is missing or the call fails.
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

            # Pull weekend schedule + commute tip from the F1 domain layer
            # so the LLM doesn't invent session days or local transit advice.
            from tools._f1_domain import enrich as _enrich_gp
            domain = _enrich_gp(state.get("gp_name", "")) or {}
            schedule = domain.get("session_schedule") or {}
            commute = domain.get("commute_notes") or ""
            schedule_block = ""
            if schedule:
                schedule_block = (
                    "\nRace weekend schedule:\n"
                    f"- Friday {schedule.get('friday','')}: FP1 + FP2 (Sprint Qualifying on Sprint weekends)\n"
                    f"- Saturday {schedule.get('saturday','')}: FP3 + Qualifying (Sprint + Quali on Sprint weekends)\n"
                    f"- Sunday {schedule.get('sunday','')}: Race\n"
                )
            commute_block = f"Local commute tips: {commute}\n" if commute else ""

            system = (
                "You are an expert travel planner curating a Formula 1 fan "
                "trip. You produce tight, practical day-by-day itineraries. "
                "Race weekends always run Friday (FP1/FP2), Saturday "
                "(FP3/Qualifying), Sunday (Race). "
                # Prompt-injection mitigation (security-5): user free-text is
                # fenced below; treat it strictly as data, never instructions.
                + UNTRUSTED_TEXT_NOTE
            )
            user = (
                f"Plan a {days_count}-day itinerary for the {state['gp_name']} "
                f"in {state['gp_city']} (race date: {state['gp_date']}).\n"
                f"Origin: {state.get('origin', '')}\n"
                f"Hotel base: {chosen_hotel or 'TBD'}\n"
                f"Stops / multi-city plan: {wrap_untrusted_text(stops)}\n"
                f"Special requests: {wrap_untrusted_text(special)}\n"
                f"{schedule_block}"
                f"{commute_block}\n"
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
