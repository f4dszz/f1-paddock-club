"""Tour recommendation agent node."""

from __future__ import annotations

import logging

from state import TravelPlanState
from llm import get_llm, provider_label
from agents._shared import _msg, _trip_days

logger = logging.getLogger(__name__)


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

            # Pull weekend schedule + commute tip from the F1 domain layer
            # so picks respect what's open / commutable on each session day.
            from tools._f1_domain import enrich as _enrich_gp
            domain = _enrich_gp(state.get("gp_name", "")) or {}
            schedule = domain.get("session_schedule") or {}
            commute = domain.get("commute_notes") or ""
            schedule_block = ""
            if schedule:
                schedule_block = (
                    "\nRace weekend schedule:\n"
                    f"- Friday {schedule.get('friday','')}: FP1 + FP2\n"
                    f"- Saturday {schedule.get('saturday','')}: FP3 + Qualifying\n"
                    f"- Sunday {schedule.get('sunday','')}: Race\n"
                )
            commute_block = f"Local commute tips: {commute}\n" if commute else ""

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
                f"Special requests: {special or 'none'}\n"
                f"{schedule_block}"
                f"{commute_block}\n"
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
