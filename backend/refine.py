"""Supervisor agent — universal entry point for chat-based interaction.

This module handles BOTH scenarios:
  1. Initial planning: user types "Plan my trip to Italian GP from Shanghai"
     → supervisor extracts parameters → calls all tools → returns full plan
  2. Refinement: user has a plan and says "change hotels to Marriott"
     → supervisor identifies what to change → calls only needed tools → updates state

The distinction is automatic: if state has existing data (tickets, transport,
hotel), we're in refinement mode. If state is empty, we're in planning mode.

ARCHITECTURE LESSON — Why one supervisor, not two separate agents:
Both modes use the SAME tools, SAME state, SAME reasoning. The only
difference is the prompt instruction ("plan from scratch" vs "make
targeted changes"). Splitting into two agents would mean maintaining
two copies of tool bindings, error handling, and test coverage for
zero benefit. The mode switch is a prompt-level concern, not a code-level one.

Phase 3.6 addition — State-aware tool factory:
Tools are now created per-invocation as closures that capture the current
state. When the supervisor omits a parameter (city, date, origin), the
tool auto-fills from state instead of searching with empty values or
asking the user. This is a CODE-LEVEL guardrail against the known issue
where the supervisor ignores the prompt and asks for already-known info.

Usage:
    # Mode 1: Chat-first (no form, user types freely)
    state, reply = refine_plan({}, "Plan my trip to Monza from Shanghai, $3000, 5 days")

    # Mode 2: Post-form refinement
    state = plan_trip({...})  # Lane 1
    state, reply = refine_plan(state, "hotels should be Marriott, near the circuit")
    state, reply = refine_plan(state, "直飞, no stops")
"""

from __future__ import annotations
import json
import logging
import os
import re
from typing import Any

from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import create_react_agent

from llm import get_llm
from refine_constraints import _apply_constraint_filters
from refine_editing import apply_line_update, replacement_name, replacement_target_name
from refine_reply import (
    build_deterministic_summary as _build_deterministic_summary,
    detect_date_override as _detect_date_override,
)
from refine_state import (
    apply_tool_updates as _apply_tool_updates,
    collect_failed_tool_details as _collect_failed_tool_details,
    collect_failed_tools as _collect_failed_tools,
    count_tool_messages as _count_tool_messages,
)

from tools.search_hotels import search_hotels as _raw_search_hotels
from tools.search_flights import search_flights as _raw_search_flights
from tools.search_tickets import search_tickets as _raw_search_tickets
from tools.recompute import recompute_budget as _raw_recompute_budget
from tools._constraints import merge_constraints, normalize_constraints
from tools._trip_dates import compute_trip_dates
from tools._currency import to_eur

logger = logging.getLogger(__name__)


_MODIFICATION_INTENT_RE = re.compile(
    r"\b(update|change|move|switch|replace|swap|rearrange|rework|edit|modify|adjust|reschedule|shift)\b"
    r"|改|更改|修改|换|替换|移动|挪|调整|重新安排|安排到|提前|延后",
    re.IGNORECASE,
)

_UNPERSISTED_TARGET_RE = re.compile(
    r"\b(itinerary|schedule|day|dinner|lunch|restaurant|meal|tour|explore|activity|activities|visit|sightseeing)\b"
    r"|行程|日程|安排|晚餐|午餐|餐厅|饭|餐|景点|游览|活动|参观",
    re.IGNORECASE,
)

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
    "ritz",
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


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _requests_unpersisted_change(user_message: str) -> bool:
    """Detect edit requests for fields Lane 2 cannot persist yet.

    Hotels/flights/tickets have tools and state mappings. Itinerary/tour
    edits currently do not, so a no-tool LLM answer must not claim the
    cards changed.
    """
    text = user_message or ""
    return bool(_MODIFICATION_INTENT_RE.search(text) and _UNPERSISTED_TARGET_RE.search(text))


def _unapplied_change_reply(user_message: str) -> str:
    if _has_cjk(user_message):
        return (
            "我理解这个修改请求，但当前版本没有把这类行程/探索文本改动写回结果卡片；"
            "所以本次没有应用到当前计划。请重新规划，或改酒店、航班、票务这类当前可持久化的项目。"
        )
    return (
        "I understood the requested itinerary/tour change, but this version "
        "cannot persist that kind of edit to the result cards yet. No plan "
        "cards were changed; please re-plan with the new requirement or edit "
        "hotels, flights, or tickets instead."
    )


def _intent_max_stops(user_message: str) -> int | None:
    return 0 if _DIRECT_ONLY_RE.search(user_message or "") else None


def _intent_allowed_brands(user_message: str) -> list[str]:
    text = (user_message or "").lower()
    return [brand for brand in _KNOWN_HOTEL_BRANDS if brand in text]


def _intent_strict_brand(user_message: str) -> bool:
    text = user_message or ""
    # In refinement, explicit vendor names are treated as a hard constraint:
    # users expect "Marriott or Hilton" to change the actual hotel list, not
    # merely bias a broad provider search.
    return bool(_intent_allowed_brands(text))


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: Supervisor Prompt
# ═══════════════════════════════════════════════════════════════════════

SUPERVISOR_PROMPT = """\
You are the F1 Paddock Club travel supervisor — a concierge AI that
helps users plan and refine their Formula 1 Grand Prix trip.

Current focus: Formula 1 Grand Prix events (2026 season).

{mode_instructions}

General rules (apply in ALL modes):
1. Respond in the SAME LANGUAGE the user writes in.
2. After ANY change to hotels, flights, or tickets, ALWAYS call
   recompute_budget_tool to verify the plan is within budget.
3. If a tool returns an error, explain honestly and suggest alternatives.
4. Keep responses concise — the user wants answers, not essays.
5. When presenting results, highlight the key changes and the budget impact.
6. If the user asks to change schedule, itinerary, day plans, restaurants,
   tours, sights, or activities, call update_itinerary_tool or
   update_tour_tool so the result cards actually change.

Current plan:
{state_summary}
"""

MODE_INITIAL = """\
PLANNING MODE — No plan exists yet.
The user wants to create a new F1 travel plan. Your job:
1. Extract trip parameters from the user's message:
   - Which Grand Prix? (map to official name, e.g. "Monza" → "Italian GP")
   - Origin city?
   - Budget?
   - How many extra days beyond the race weekend?
   - Any special requirements? (hotel brand, dietary, accessibility, etc.)
2. Call the tools IN THIS ORDER:
   a. search_tickets_tool — find 3 grandstand options for that GP
   b. search_flights_tool — find flights from origin to the GP city
   c. search_hotels_tool — find hotels near the circuit
   d. recompute_budget_tool — check total against budget
3. Present a summary of the complete plan to the user.

If the user's message is missing critical info (which GP? origin city?),
ASK them before calling tools — don't guess.
"""

MODE_REFINE = """\
REFINEMENT MODE — The user has an existing plan (shown below).
They want to make changes. Your job:
1. Understand EXACTLY what the user wants to change.
2. Call ONLY the tools needed for that specific change.
   If the user only wants to change hotels, do NOT touch flights or tickets.
3. Present the changes clearly.

RESPONSE FORMAT — Your reply MUST be short (2-3 sentences max). Structure:
- Line 1: What you changed (e.g., "Switched hotel to Burg Rooms at {currency} 100/night.")
- Line 2: Budget impact (e.g., "New total: {currency} 1,850 / {currency} 2,000 — within budget." or "No budget change.")
- Do NOT repeat raw tool output, price lists, or detailed comparisons.
- Do NOT use markdown headers, bullet lists, or long explanations.
- The updated result cards will show the details — your reply is just a summary.

CRITICAL RULES for refinement:
- All trip parameters (city, dates, origin, budget) are ALREADY KNOWN.
  They are listed in the "Tool parameters" section below.
- The tools will AUTOMATICALLY use these parameters if you don't override them.
  You do NOT need to pass city/date/origin unless the user wants to CHANGE them.
- NEVER ask the user for GP name, city, date, origin, or budget —
  these are already in the plan. Asking for known information is a bug.
- ONLY ask clarifying questions about the user's NEW request
  (e.g., "Do you want 4-star or 5-star Marriott?" is OK).
- All prices in your reply MUST use {currency}. Convert if the tool returned other currencies.
"""


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: State-Aware Tool Factory
#
# WHY create tools per-invocation instead of at module level?
#
# Problem: the supervisor sometimes ignores the prompt and calls
# search_hotels_tool(city="") or search_flights_tool(origin="", dest="").
# With module-level tools, empty params → bad search → bad results.
#
# Solution: tools created inside refine_plan() capture the current state
# via closure. Any empty parameter is auto-filled from state. The
# supervisor CAN override (user says "search hotels in Rome instead")
# but DEFAULTS are always correct.
#
# This is a CODE-LEVEL guardrail — it works even when the LLM ignores
# the prompt instruction. Belt AND suspenders.
# ═══════════════════════════════════════════════════════════════════════

def _build_tools(state: dict, user_message: str = "") -> list:
    """Create state-aware tool instances for this invocation.

    Each tool auto-fills missing parameters from state, so the
    supervisor never needs to re-specify known trip info.
    """
    # Pre-compute dates once for all tools. Honor explicit user-set
    # depart/return when present; otherwise fall back to extra_days.
    dates = compute_trip_dates(
        state.get("gp_date", ""),
        state.get("extra_days", 0),
        state.get("depart_date", "") or "",
        state.get("return_date", "") or "",
    )

    # State defaults — what the tools fall back to
    _city = state.get("gp_city", "")
    _origin = state.get("origin", "")
    _gp_name = state.get("gp_name", "")
    _currency = str(state.get("currency") or "EUR").upper()
    _checkin = dates["hotel_checkin"]
    _checkout = dates["hotel_checkout"]
    _outbound = dates["outbound_date"]
    _return = dates["return_date"]
    _constraints = merge_constraints(state.get("active_constraints"), user_message)
    _intent_stops = 0 if _constraints.get("direct_only") else _intent_max_stops(user_message)
    _intent_brands = _constraints.get("allowed_hotel_brands") or _intent_allowed_brands(user_message)
    _strict_brand = bool(_intent_brands) or _intent_strict_brand(user_message)

    @tool
    def search_hotels_tool(
        city: str = "",
        checkin: str = "",
        checkout: str = "",
        brand: str = "",
        stars: int = 0,
        max_price: float = 0,
        near: str = "",
    ) -> str:
        """Search for hotel options near an F1 circuit or city.
        Use this when: user wants different hotels, specific brand (Marriott/Hilton),
        price range, star rating, or location preference.
        Parameters auto-fill from the current plan — only pass values you want to CHANGE.
        Returns JSON array of hotel options with name, price, rating, distance."""
        try:
            kwargs: dict[str, Any] = {
                "city": city or _city,
                "checkin": checkin or _checkin,
                "checkout": checkout or _checkout,
            }
            if brand:
                kwargs["brand"] = brand
            elif _intent_brands:
                kwargs["brand"] = " or ".join(_intent_brands)
            if _strict_brand:
                kwargs["strict_brand"] = True
            if stars > 0:
                kwargs["stars"] = stars
            if max_price > 0:
                kwargs["max_price"] = max_price
            if near:
                kwargs["near"] = near
            logger.info("search_hotels_tool called: %s", {k: v for k, v in kwargs.items() if v})
            results, _summary = _raw_search_hotels(**kwargs)
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            logger.exception("search_hotels_tool failed")
            return f"Hotel search failed: {e}. Try adjusting criteria or suggest the user check booking.com directly."

    @tool
    def search_flights_tool(
        origin: str = "",
        dest: str = "",
        date: str = "",
        return_date: str = "",
        stops: int = -1,
        cabin: str = "",
    ) -> str:
        """Search for flight options between two cities.
        Use this when: user wants different flights, direct only, different dates, cabin class.
        Parameters auto-fill from the current plan — only pass values you want to CHANGE.
        Returns JSON array of flight options with airline, price, duration, stops."""
        try:
            kwargs: dict[str, Any] = {
                "origin": origin or _origin,
                "dest": dest or _city,
                "date": date or _outbound,
            }
            effective_return = return_date or _return
            if effective_return:
                kwargs["return_date"] = effective_return
            effective_stops = stops if stops >= 0 else _intent_stops
            if effective_stops is not None:
                kwargs["stops"] = effective_stops
            if cabin:
                kwargs["cabin"] = cabin
            logger.info("search_flights_tool called: %s", {k: v for k, v in kwargs.items() if v})
            results, _summary = _raw_search_flights(**kwargs)
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            logger.exception("search_flights_tool failed")
            return f"Flight search failed: {e}. Try adjusting criteria."

    @tool
    def search_tickets_tool(
        gp_name: str = "",
        year: int = 2026,
        pref: str = "",
        max_price: float = 0,
    ) -> str:
        """Search for F1 ticket/grandstand options for a specific Grand Prix.
        Use this when: user wants to see ticket options, change grandstand, adjust ticket budget.
        Parameters auto-fill from the current plan — only pass values you want to CHANGE.
        Returns JSON array with grandstand name, price, section, booking link."""
        try:
            kwargs: dict[str, Any] = {"gp_name": gp_name or _gp_name, "year": year}
            if pref:
                kwargs["pref"] = pref
            if max_price > 0:
                kwargs["max_price"] = max_price
            logger.info("search_tickets_tool called: %s", kwargs)
            results, _summary = _raw_search_tickets(**kwargs)
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            logger.exception("search_tickets_tool failed")
            return f"Ticket search failed: {e}. Try checking tickets.formula1.com directly."

    @tool
    def recompute_budget_tool(state_json: Any = "") -> str:
        """Recompute the total budget after any change to hotels, flights, or tickets.
        ALWAYS call this after making changes to verify the plan is within budget.
        Prefer no argument. If passing state, only currency override is honored."""
        try:
            def _budget_state_from_arg(raw: Any) -> dict:
                s = dict(state)
                parsed: dict[str, Any] = {}
                if isinstance(raw, dict):
                    parsed = raw
                elif isinstance(raw, str) and raw.strip():
                    loaded = json.loads(raw)
                    if not isinstance(loaded, dict):
                        raise ValueError("state_json must be a JSON object")
                    parsed = loaded
                elif raw:
                    raise ValueError("state_json must be empty, a JSON string, or an object")

                if "currency" in parsed:
                    s["currency"] = parsed["currency"]
                return s

            s = _budget_state_from_arg(state_json)
            # Inherit session currency if supervisor passed partial state
            # without it. Prevents silent fallback to EUR when the
            # actual plan was USD / CNY.
            if not s.get("currency"):
                s["currency"] = _currency
            summary = _raw_recompute_budget(s)
            return json.dumps(summary, ensure_ascii=False)
        except Exception as e:
            logger.exception("recompute_budget_tool failed")
            return f"Budget recomputation failed: {e}"

    @tool
    def update_itinerary_tool(request: str = "") -> str:
        """Persist a schedule/itinerary/day-plan/restaurant change.
        Use this when the user asks to move, replace, add, or adjust a day,
        meal, restaurant, timing, or race-weekend schedule item. Returns the
        full updated itinerary JSON array."""
        try:
            current = state.get("itinerary") or []
            return json.dumps(
                apply_line_update(current, request, "Itinerary", user_message),
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("update_itinerary_tool failed")
            return f"Itinerary update failed: {e}"

    @tool
    def update_tour_tool(request: str = "") -> str:
        """Persist a tour/explore/activity/sightseeing recommendation change.
        Use this when the user asks to change attractions, tours, local
        experiences, restaurants as recommendations, or exploration cards.
        Returns the full updated tour JSON array."""
        try:
            current = state.get("tour") or []
            return json.dumps(
                apply_line_update(current, request, "Tour", user_message),
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("update_tour_tool failed")
            return f"Tour update failed: {e}"

    return [
        search_hotels_tool,
        search_flights_tool,
        search_tickets_tool,
        recompute_budget_tool,
        update_itinerary_tool,
        update_tour_tool,
    ]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: State Mutation — Post-Loop Update Application
#
# Applies tool results to state AFTER the ReAct loop finishes, so only
# the FINAL successful result for each tool is kept (not intermediate
# retries). The mapping is declarative — adding a new tool = one line.
# ═══════════════════════════════════════════════════════════════════════

# State-update and deterministic-reply helpers live in refine_state.py and
# refine_reply.py. The private aliases imported above keep existing tests and
# callers stable while shrinking this orchestration module.


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: State Formatter
# ═══════════════════════════════════════════════════════════════════════

def _format_state(state: dict) -> str:
    """Compact human-readable summary of the current plan for the prompt.

    Display-layer code — must NEVER crash. If the state has unexpected
    shape, degrade to a best-effort summary rather than raise, since
    this output is fed into the supervisor prompt on every chat turn.
    """
    try:
        return _format_state_impl(state)
    except Exception as e:
        logger.warning("_format_state degraded: %s", e)
        gp = state.get("gp_name", "?")
        cur = str(state.get("currency") or "EUR").upper()
        budget = state.get("budget", "?")
        return f"GP: {gp}\nBudget: {cur} {budget}\n(plan summary unavailable, working with raw state)"


def _format_state_impl(state: dict) -> str:
    cur = str(state.get("currency") or "EUR").upper()
    has_data = any(state.get(f) for f in ("tickets", "transport", "hotel"))

    if not has_data:
        lines = ["No plan exists yet."]
        if state.get("gp_name"):
            lines.append(f"GP: {state['gp_name']} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
        if state.get("origin"):
            lines.append(f"Origin: {state['origin']}")
        if state.get("budget"):
            lines.append(f"Budget: {cur} {state['budget']}")
        return "\n".join(lines)

    # Pre-compute trip dates for display — degrade on parse failure
    explicit_dates = bool(state.get("depart_date") and state.get("return_date"))
    try:
        dates = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
    except Exception:
        dates = {"outbound_date": "?", "return_date": "?",
                 "hotel_checkin": "?", "hotel_checkout": "?", "trip_nights": "?"}

    lines = []
    lines.append(f"GP: {state.get('gp_name', '?')} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
    lines.append(f"Origin: {state.get('origin', '?')}")
    lines.append(f"Budget: {cur} {state.get('budget', '?')}")
    # Show the date driver explicitly so the supervisor knows what it can
    # safely change. In explicit mode, extra_days is irrelevant noise.
    if explicit_dates:
        lines.append(f"Travel dates: user-set (depart {state['depart_date']}, return {state['return_date']})")
    else:
        lines.append(f"Extra days after race: {state.get('extra_days', 0)} (legacy; travel dates derived)")
    lines.append(f"Trip: {dates['outbound_date']} → {dates['return_date']} ({dates['trip_nights']} nights)")
    if state.get("special_requests"):
        lines.append(f"Special requests: {state['special_requests']}")
    constraints = normalize_constraints(state.get("active_constraints"))
    active_bits = []
    if constraints.get("direct_only"):
        active_bits.append("direct flights only")
    if constraints.get("allowed_hotel_brands"):
        active_bits.append("hotel brands: " + ", ".join(constraints["allowed_hotel_brands"]))
    if constraints.get("dietary"):
        active_bits.append(f"dietary: {constraints['dietary']}")
    if constraints.get("accessibility"):
        active_bits.append("accessibility required")
    if constraints.get("avoid_luxury"):
        active_bits.append("avoid luxury / prioritize budget")
    if active_bits:
        lines.append("Active constraints: " + "; ".join(active_bits))

    # All item prices displayed in the user's selected currency. The raw
    # item.currency may differ (e.g. SerpAPI returns USD for most flights);
    # we convert via EUR pivot so the supervisor sees one consistent unit.
    def _fmt(amount, source_currency: str) -> str:
        try:
            eur = to_eur(float(amount), source_currency or "EUR")
            target_amount = eur if cur == "EUR" else _convert_eur_to(eur, cur)
            return f"{cur} {round(target_amount)}"
        except (TypeError, ValueError):
            return f"{cur} {amount}"

    if state.get("tickets"):
        lines.append("\nTickets:")
        for t in state["tickets"]:
            if t.get("tag") == "INFO":
                continue
            lines.append(f"  - [{t.get('tag', '')}] {t.get('name', '')} {_fmt(t.get('price'), t.get('currency', 'EUR'))}")

    if state.get("transport"):
        lines.append("\nFlights:")
        for t in state["transport"]:
            if t.get("tag") == "INFO":
                continue
            lines.append(f"  - [{t.get('tag', '')}] {t.get('summary', '')} {_fmt(t.get('price'), t.get('currency', 'USD'))}")

    if state.get("hotel"):
        lines.append("\nHotels:")
        for h in state["hotel"]:
            if h.get("tag") == "INFO":
                continue
            lines.append(f"  - [{h.get('tag', '')}] {h.get('name', '')} {_fmt(h.get('price_per_night'), h.get('currency', 'USD'))}/night")

    if state.get("itinerary"):
        lines.append("\nItinerary:")
        for line in state["itinerary"]:
            lines.append(f"  - {line}")

    if state.get("tour"):
        lines.append("\nTour / Explore:")
        for line in state["tour"]:
            lines.append(f"  - {line}")

    bs = state.get("budget_summary") or {}
    if bs:
        bs_cur = bs.get("currency", cur)
        lines.append(f"\nBudget: {bs_cur} {bs.get('total', '?')} / {bs_cur} {bs.get('budget', '?')} "
                      f"({'within budget' if bs.get('within_budget') else 'OVER BUDGET'})")

    lines.append("\n--- Tool parameters (auto-filled, override only to change) ---")
    lines.append(f"gp_name: {state.get('gp_name', '?')}")
    lines.append(f"city: {state.get('gp_city', '?')}")
    lines.append(f"origin: {state.get('origin', '?')}")
    lines.append(f"outbound_date: {dates['outbound_date']}")
    lines.append(f"return_date: {dates['return_date']}")
    lines.append(f"hotel_checkin: {dates['hotel_checkin']}")
    lines.append(f"hotel_checkout: {dates['hotel_checkout']}")
    lines.append(f"trip_nights: {dates['trip_nights']}")
    lines.append(f"budget: {state.get('budget', '?')} ({cur})")

    return "\n".join(lines)


def _convert_eur_to(eur_amount: float, target_currency: str) -> float:
    """Helper: EUR → target via _currency.from_eur, non-crashing."""
    from tools._currency import from_eur
    try:
        return from_eur(eur_amount, target_currency)
    except Exception:
        return eur_amount


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def _refine_plan_stub(state: dict, user_message: str) -> tuple[dict, str, dict]:
    """Deterministic test-only stub for refine_plan.

    Gated upstream by APP_ENV=test + LLM_STUB_MODE=1. Bypasses the LangChain
    supervisor entirely and directly invokes the server-side mutation helpers
    used by the production path (`normalize_constraints` +
    `_apply_constraint_filters` for direct-flights-only, `apply_line_update`
    for tour replacement). This is the smallest test-stub path that exercises
    the same persisted state transitions the production refinement uses, so
    frontend/e2e/refine.spec.js can assert real before/after card mutation
    without burning real LLM credit.

    Not a fake chat model, not a production fallback. Production with empty
    keys still hits the honest "LLM not configured" early return below.

    Unhandled prompts return state unchanged with an honest reply.
    """
    trace: dict = {"failed_tools": [], "updated_fields": [], "tool_call_count": 0}
    lower = user_message.lower()

    # Pattern 1: direct-flights-only intent → constraint + reconciler.
    if "direct" in lower and ("flight" in lower or "flights" in lower):
        active = normalize_constraints(state.get("active_constraints"))
        active["direct_only"] = True
        state["active_constraints"] = active
        updated = _apply_constraint_filters(state, force=True)
        trace["updated_fields"] = list(updated.keys())
        trace["tool_call_count"] = 1
        kept = sum(
            1
            for t in state.get("transport", [])
            if isinstance(t, dict) and t.get("tag") in {"ROUNDTRIP", "OUT", "RET"}
        )
        reply = (
            f"Applied direct-flights-only constraint. Kept {kept} direct "
            f"flight option(s) on the transport card."
        )
        logger.info(
            "refine_plan stub: direct_only applied; updated=%s kept=%d",
            updated,
            kept,
        )
        return state, reply, trace

    # Pattern 2: "Replace X with Y" → tour line update.
    target = replacement_target_name(user_message)
    replacement = replacement_name(user_message)
    if target and replacement and state.get("tour"):
        state["tour"] = apply_line_update(state["tour"], user_message, "Tour")
        trace["updated_fields"] = ["tour"]
        trace["tool_call_count"] = 1
        reply = (
            f"Updated tour recommendations: replaced '{target}' with "
            f"'{replacement}'."
        )
        logger.info(
            "refine_plan stub: tour replace applied (%s -> %s)",
            target,
            replacement,
        )
        return state, reply, trace

    logger.info("refine_plan stub: prompt pattern not recognized")
    return (
        state,
        (
            "Test-stub refinement: prompt pattern not in the deterministic test "
            "set. Supported: 'direct flights only', 'Replace X with Y'."
        ),
        trace,
    )


def refine_plan(
    state: dict,
    user_message: str,
    conversation_history: list[tuple[str, str]] | None = None,
) -> tuple[dict, str, dict]:
    """Universal entry point for chat-based interaction.

    Handles both initial planning (empty state) and refinement (existing plan).

    Args:
        state: Current TravelPlanState dict.
        user_message: Natural language input in any language.
        conversation_history: Optional list of (role, content) tuples from
            previous turns. Enables the supervisor to resolve references
            like "not that one" or "the cheaper option you showed."

    Returns:
        Always a 3-tuple: (updated_state, reply_text, trace_ctx).
        `trace_ctx` is a small dict the transport layer uses to emit
        debug-trace events — `{failed_tools, updated_fields, tool_call_count}`.
        Every early-return branch MUST also return a trace_ctx so the
        caller can unpack without branching.
    """
    _empty_trace: dict = {"failed_tools": [], "updated_fields": [], "tool_call_count": 0}

    # Test-only deterministic stub. Gated by APP_ENV=test + LLM_STUB_MODE=1.
    # Bypasses the LangChain supervisor and directly invokes server-side
    # mutation helpers for the small set of refine prompts exercised by
    # frontend/e2e/refine.spec.js. Not a production fallback path — with
    # APP_ENV unset or LLM_STUB_MODE unset, the honest "LLM not configured"
    # early return below still fires when keys are absent.
    if (
        os.environ.get("APP_ENV") == "test"
        and os.environ.get("LLM_STUB_MODE") == "1"
    ):
        return _refine_plan_stub(state, user_message)

    llm = get_llm(temperature=0.3, max_tokens=2048)
    if llm is None:
        return state, "LLM not configured — cannot process requests.", _empty_trace

    # Durable structured memory: keep hard constraints outside the
    # short rolling conversation history so they survive long chats.
    previous_constraints = normalize_constraints(state.get("active_constraints"))
    state["active_constraints"] = merge_constraints(state.get("active_constraints"), user_message)
    constraints_changed = normalize_constraints(state.get("active_constraints")) != previous_constraints

    # ── Detect mode ──────────────────────────────────────────────
    has_plan = bool(state.get("tickets") or state.get("transport") or state.get("hotel"))
    mode = "refinement" if has_plan else "initial_planning"
    currency = str(state.get("currency") or "EUR").upper()
    mode_template = MODE_REFINE if has_plan else MODE_INITIAL
    # MODE_REFINE has {currency} placeholders — resolve them before final format
    mode_instructions = mode_template.replace("{currency}", currency)

    # ── Build prompt ─────────────────────────────────────────────
    state_summary = _format_state(state)
    prompt = SUPERVISOR_PROMPT.format(
        mode_instructions=mode_instructions,
        state_summary=state_summary,
    )

    # ── Create state-aware tools ─────────────────────────────────
    tools = _build_tools(state, user_message)

    # ── Create and invoke supervisor ─────────────────────────────
    supervisor = create_react_agent(
        model=llm,
        tools=tools,
        prompt=prompt,
    )

    logger.info("refine_plan [%s mode, %d history turns]: %s",
                mode, len(conversation_history or []) // 2, user_message[:100])

    # Build message list: conversation history + current user message
    messages = []
    for role, content in (conversation_history or []):
        messages.append((role, content))
    messages.append(("user", user_message))

    result = supervisor.invoke({
        "messages": messages,
    })

    # ── Extract reply ────────────────────────────────────────────
    messages = result.get("messages", [])
    reply = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and not isinstance(msg, ToolMessage):
            if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                reply = msg.content
                break
            elif hasattr(msg, "content") and not hasattr(msg, "tool_call_id") and msg.content:
                reply = msg.content
                break

    if not reply:
        reply = "I processed your request but couldn't generate a response. Please try rephrasing."

    # ── Apply state mutations from tool results ──────────────────
    updated_fields = _apply_tool_updates(state, messages)
    constraint_filtered = _apply_constraint_filters(
        state,
        updated_fields,
        force=constraints_changed,
    )
    updated_fields.update(constraint_filtered)

    if updated_fields:
        logger.info("refine_plan: state fields updated: %s", list(updated_fields.keys()))
    else:
        logger.info("refine_plan: no state changes (supervisor answered without calling tools)")

    # ── Groundedness: if any tool was invoked, replace the LLM reply
    #    with a deterministic summary built from final state + final
    #    budget_summary. This prevents the LLM from claiming changes that
    #    didn't land (e.g. flight search timeout) or inventing budget
    #    numbers. Pure conversational turns (no tool calls) keep the
    #    natural LLM reply.
    tool_call_count = _count_tool_messages(messages)
    failed_tools: list[str] = []
    if tool_call_count > 0:
        failed_tool_details = _collect_failed_tool_details(messages)
        failed_tools = list(failed_tool_details.keys())
        date_override = _detect_date_override(messages, state)
        reply = _build_deterministic_summary(
            state,
            updated_fields,
            failed_tools,
            date_override,
            failed_tool_details,
        )
        logger.info("refine_plan: deterministic reply used (tool_calls=%d, failed=%d, date_override=%s)",
                    tool_call_count, len(failed_tools), date_override)
    elif not updated_fields and _requests_unpersisted_change(user_message):
        reply = _unapplied_change_reply(user_message)
        logger.info("refine_plan: unapplied change guard used for no-tool reply")

    # Return a small trace dict alongside (state, reply) so transport
    # layer can surface debug traces without re-scanning messages.
    trace = {
        "failed_tools": failed_tools,
        "updated_fields": list(updated_fields.keys()),
        "tool_call_count": tool_call_count,
    }
    return state, reply, trace
