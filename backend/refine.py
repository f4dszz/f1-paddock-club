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
from typing import Any

from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import create_react_agent

from llm import get_llm

from tools.search_hotels import search_hotels as _raw_search_hotels
from tools.search_flights import search_flights as _raw_search_flights
from tools.search_tickets import search_tickets as _raw_search_tickets
from tools.recompute import recompute_budget as _raw_recompute_budget
from tools._trip_dates import compute_trip_dates

logger = logging.getLogger(__name__)


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
3. Present the changes clearly: what was before, what's new, budget impact.

CRITICAL RULES for refinement:
- All trip parameters (city, dates, origin, budget) are ALREADY KNOWN.
  They are listed in the "Tool parameters" section below.
- The tools will AUTOMATICALLY use these parameters if you don't override them.
  You do NOT need to pass city/date/origin unless the user wants to CHANGE them.
- NEVER ask the user for GP name, city, date, origin, or budget —
  these are already in the plan. Asking for known information is a bug.
- ONLY ask clarifying questions about the user's NEW request
  (e.g., "Do you want 4-star or 5-star Marriott?" is OK).
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

def _build_tools(state: dict) -> list:
    """Create state-aware tool instances for this invocation.

    Each tool auto-fills missing parameters from state, so the
    supervisor never needs to re-specify known trip info.
    """
    # Pre-compute dates once for all tools
    dates = compute_trip_dates(
        state.get("gp_date", ""),
        state.get("extra_days", 0),
    )

    # State defaults — what the tools fall back to
    _city = state.get("gp_city", "")
    _origin = state.get("origin", "")
    _gp_name = state.get("gp_name", "")
    _checkin = dates["hotel_checkin"]
    _checkout = dates["hotel_checkout"]
    _outbound = dates["outbound_date"]
    _return = dates["return_date"]

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
            if stops >= 0:
                kwargs["stops"] = stops
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
    def recompute_budget_tool(state_json: str) -> str:
        """Recompute the total budget after any change to hotels, flights, or tickets.
        ALWAYS call this after making changes to verify the plan is within budget.
        Pass the FULL current state as a JSON string."""
        try:
            s = json.loads(state_json)
            summary = _raw_recompute_budget(s)
            return json.dumps(summary, ensure_ascii=False)
        except Exception as e:
            logger.exception("recompute_budget_tool failed")
            return f"Budget recomputation failed: {e}"

    return [search_hotels_tool, search_flights_tool, search_tickets_tool, recompute_budget_tool]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: State Mutation — Post-Loop Update Application
#
# Applies tool results to state AFTER the ReAct loop finishes, so only
# the FINAL successful result for each tool is kept (not intermediate
# retries). The mapping is declarative — adding a new tool = one line.
# ═══════════════════════════════════════════════════════════════════════

_TOOL_STATE_MAP: dict[str, str] = {
    "search_hotels_tool": "hotel",
    "search_flights_tool": "transport",
    "search_tickets_tool": "tickets",
}


def _apply_tool_updates(state: dict, messages: list) -> dict[str, bool]:
    """Scan the message history and apply tool results to state.

    Iterates messages in REVERSE order so we find the LAST successful
    call for each tool (in case the supervisor retried with different params).
    """
    updated: dict[str, bool] = {}

    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue

        tool_name = getattr(msg, "name", None)
        if not tool_name or tool_name not in _TOOL_STATE_MAP:
            continue

        field = _TOOL_STATE_MAP[tool_name]
        if field in updated:
            continue

        content = msg.content
        if not content or content.startswith(("Hotel search failed",
                                               "Flight search failed",
                                               "Ticket search failed")):
            continue

        try:
            data = json.loads(content)
            if isinstance(data, list) and len(data) > 0:
                state[field] = data
                updated[field] = True
                logger.info("state updated: %s ← %d items from %s", field, len(data), tool_name)
        except (json.JSONDecodeError, TypeError):
            continue

    if updated:
        try:
            state["budget_summary"] = _raw_recompute_budget(state)
            state["budget_ok"] = state["budget_summary"].get("within_budget", False)
            logger.info("budget recomputed after state update: EUR %.0f / EUR %.0f",
                        state["budget_summary"]["total"], state["budget_summary"]["budget"])
        except Exception:
            logger.exception("budget recomputation failed after state update")

    return updated


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: State Formatter
# ═══════════════════════════════════════════════════════════════════════

def _format_state(state: dict) -> str:
    """Compact human-readable summary of the current plan for the prompt."""
    has_data = any(state.get(f) for f in ("tickets", "transport", "hotel"))

    if not has_data:
        lines = ["No plan exists yet."]
        if state.get("gp_name"):
            lines.append(f"GP: {state['gp_name']} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
        if state.get("origin"):
            lines.append(f"Origin: {state['origin']}")
        if state.get("budget"):
            lines.append(f"Budget: EUR {state['budget']}")
        return "\n".join(lines)

    # Pre-compute trip dates for display
    dates = compute_trip_dates(state.get("gp_date", ""), state.get("extra_days", 0))

    lines = []
    lines.append(f"GP: {state.get('gp_name', '?')} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
    lines.append(f"Origin: {state.get('origin', '?')}")
    lines.append(f"Budget: EUR {state.get('budget', '?')}")
    lines.append(f"Extra days: {state.get('extra_days', 0)}")
    lines.append(f"Trip: {dates['outbound_date']} to {dates['return_date']} ({dates['trip_nights']} nights)")
    if state.get("special_requests"):
        lines.append(f"Special requests: {state['special_requests']}")

    if state.get("tickets"):
        lines.append("\nTickets:")
        for t in state["tickets"]:
            if t.get("tag") == "INFO":
                continue
            cur = t.get("currency", "EUR")
            lines.append(f"  - [{t.get('tag', '')}] {t.get('name', '')} {cur} {t.get('price', '?')}")

    if state.get("transport"):
        lines.append("\nFlights:")
        for t in state["transport"]:
            if t.get("tag") == "INFO":
                continue
            cur = t.get("currency", "USD")
            lines.append(f"  - [{t.get('tag', '')}] {t.get('summary', '')} {cur} {t.get('price', '?')}")

    if state.get("hotel"):
        lines.append("\nHotels:")
        for h in state["hotel"]:
            if h.get("tag") == "INFO":
                continue
            cur = h.get("currency", "USD")
            lines.append(f"  - [{h.get('tag', '')}] {h.get('name', '')} {cur} {h.get('price_per_night', '?')}/night")

    bs = state.get("budget_summary") or {}
    if bs:
        lines.append(f"\nBudget: EUR {bs.get('total', '?')} / EUR {bs.get('budget', '?')} "
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
    lines.append(f"budget: {state.get('budget', '?')}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def refine_plan(state: dict, user_message: str) -> tuple[dict, str]:
    """Universal entry point for chat-based interaction.

    Handles both initial planning (empty state) and refinement (existing plan).

    Args:
        state: Current TravelPlanState dict. Can be empty ({}) for initial planning,
               or populated (from plan_trip or previous refine_plan) for refinement.
        user_message: Natural language input in any language.

    Returns:
        (updated_state, reply_text)
    """
    llm = get_llm(temperature=0.3, max_tokens=2048)
    if llm is None:
        return state, "LLM not configured — cannot process requests."

    # ── Detect mode ──────────────────────────────────────────────
    has_plan = bool(state.get("tickets") or state.get("transport") or state.get("hotel"))
    mode = "refinement" if has_plan else "initial_planning"
    mode_instructions = MODE_REFINE if has_plan else MODE_INITIAL

    # ── Build prompt ─────────────────────────────────────────────
    state_summary = _format_state(state)
    prompt = SUPERVISOR_PROMPT.format(
        mode_instructions=mode_instructions,
        state_summary=state_summary,
    )

    # ── Create state-aware tools ─────────────────────────────────
    # Tools auto-fill parameters from state — the key P0-3 guardrail.
    tools = _build_tools(state)

    # ── Create and invoke supervisor ─────────────────────────────
    supervisor = create_react_agent(
        model=llm,
        tools=tools,
        prompt=prompt,
    )

    logger.info("refine_plan [%s mode]: %s", mode, user_message[:100])

    result = supervisor.invoke({
        "messages": [("user", user_message)],
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

    if updated_fields:
        logger.info("refine_plan: state fields updated: %s", list(updated_fields.keys()))
    else:
        logger.info("refine_plan: no state changes (supervisor answered without calling tools)")

    return state, reply
