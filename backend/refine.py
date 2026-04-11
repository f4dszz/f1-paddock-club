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

# LESSON — Eager imports for refine.py, not lazy.
# In agents/__init__.py we use lazy imports (inside try blocks) because
# agents must work even if tools aren't installed (fallback to mock).
# Here the supervisor CAN'T work without tools — no tools = no supervisor.
# So we import eagerly at module level, avoiding the deadlock that happens
# when lazy imports run inside ThreadPoolExecutor threads (Python's
# _ModuleLock doesn't handle concurrent first-imports gracefully).
from tools.search_hotels import search_hotels as _raw_search_hotels
from tools.search_flights import search_flights as _raw_search_flights
from tools.search_tickets import search_tickets as _raw_search_tickets
from tools.recompute import recompute_budget as _raw_recompute_budget

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: Supervisor Prompt
#
# LESSON — Dual-mode prompt design:
# Instead of if/else in Python code, we put the mode switch IN the prompt.
# The LLM reads the "Current plan" section and sees either real data
# (refinement mode) or "No plan yet" (planning mode). It adjusts its
# behavior accordingly. This is called "context-driven behavior" — the
# same agent, same tools, different behavior based on context.
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
3. Use the "Tool parameters" section below for city, dates, origin etc.
   Do NOT ask the user to repeat information that's already in the plan.
4. Present the changes clearly: what was before, what's new, budget impact.

IMPORTANT: You have ALL the context you need in the Current plan section.
Use the city, date, origin, and budget from the existing plan when
calling tools. The user should never need to re-state basic trip info.
"""


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: Tool Wrappers
#
# LESSON — Why wrappers around the raw tool functions?
# 1. LangChain's @tool decorator needs specific signatures (no **kwargs,
#    no complex types like list[str]|None). Wrappers simplify the interface.
# 2. Wrappers catch exceptions and return error STRINGS instead of raising.
#    This is critical: if a tool raises inside the ReAct loop, the loop
#    crashes. If it returns an error string, the supervisor can REASON
#    about the failure and suggest alternatives.
# 3. Raw tools return tuple[list[dict], str] (results, summary). Wrappers
#    serialize to JSON string for the LLM to read.
# ═══════════════════════════════════════════════════════════════════════

@tool
def search_hotels_tool(
    city: str,
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
    Returns JSON array of hotel options with name, price, rating, distance."""
    try:
        kwargs: dict[str, Any] = {"city": city, "checkin": checkin, "checkout": checkout}
        if brand:
            kwargs["brand"] = brand
        if stars > 0:
            kwargs["stars"] = stars
        if max_price > 0:
            kwargs["max_price"] = max_price
        if near:
            kwargs["near"] = near
        results, _summary = _raw_search_hotels(**kwargs)
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.exception("search_hotels_tool failed")
        return f"Hotel search failed: {e}. Try adjusting criteria or suggest the user check booking.com directly."


@tool
def search_flights_tool(
    origin: str,
    dest: str,
    date: str,
    return_date: str = "",
    stops: int = -1,
    cabin: str = "",
) -> str:
    """Search for flight options between two cities.
    Use this when: user wants different flights, direct only, different dates, cabin class.
    Returns JSON array of flight options with airline, price, duration, stops."""
    try:
        kwargs: dict[str, Any] = {"origin": origin, "dest": dest, "date": date}
        if return_date:
            kwargs["return_date"] = return_date
        if stops >= 0:
            kwargs["stops"] = stops
        if cabin:
            kwargs["cabin"] = cabin
        results, _summary = _raw_search_flights(**kwargs)
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.exception("search_flights_tool failed")
        return f"Flight search failed: {e}. Try adjusting criteria."


@tool
def search_tickets_tool(
    gp_name: str,
    year: int = 2026,
    pref: str = "",
    max_price: float = 0,
) -> str:
    """Search for F1 ticket/grandstand options for a specific Grand Prix.
    Use this when: user wants to see ticket options, change grandstand, adjust ticket budget.
    Returns JSON array with grandstand name, price, section, booking link."""
    try:
        kwargs: dict[str, Any] = {"gp_name": gp_name, "year": year}
        if pref:
            kwargs["pref"] = pref
        if max_price > 0:
            kwargs["max_price"] = max_price
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
        state = json.loads(state_json)
        summary = _raw_recompute_budget(state)
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        logger.exception("recompute_budget_tool failed")
        return f"Budget recomputation failed: {e}"


SUPERVISOR_TOOLS = [
    search_hotels_tool,
    search_flights_tool,
    search_tickets_tool,
    recompute_budget_tool,
]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: State Mutation — Post-Loop Update Application
#
# LESSON — Why apply updates AFTER the loop, not DURING?
#
# In a ReAct loop, the LLM might call a tool, see the result, decide
# "that's wrong, let me try again with different parameters", and call
# the same tool again. If we mutated state inside the tool, the first
# (wrong) result would already be in state. By waiting until the loop
# finishes, we only apply the FINAL successful result for each tool.
#
# The mapping is DECLARATIVE (a dict, not if/elif) so adding a new
# tool + state field = adding one line, not one code branch.
# ═══════════════════════════════════════════════════════════════════════

# Maps tool function names → state dict keys they should update
_TOOL_STATE_MAP: dict[str, str] = {
    "search_hotels_tool": "hotel",
    "search_flights_tool": "transport",
    "search_tickets_tool": "tickets",
}


def _apply_tool_updates(state: dict, messages: list) -> dict[str, bool]:
    """Scan the message history and apply tool results to state.

    Iterates messages in REVERSE order so we find the LAST successful
    call for each tool (in case the supervisor retried with different params).

    Returns a dict of {field_name: True} for fields that were updated,
    so the caller knows what changed.

    LESSON — Why reverse order?
    If the supervisor called search_hotels twice (first with wrong params,
    then with correct params), the messages look like:
      [... ToolMsg(hotels_wrong) ... ToolMsg(hotels_correct) ...]
    Iterating in reverse, we hit hotels_correct first, apply it, and
    skip hotels_wrong because the field is already marked as updated.
    """
    updated: dict[str, bool] = {}

    for msg in reversed(messages):
        # ToolMessage has .name (tool function name) and .content (result string)
        if not isinstance(msg, ToolMessage):
            continue

        tool_name = getattr(msg, "name", None)
        if not tool_name or tool_name not in _TOOL_STATE_MAP:
            continue

        field = _TOOL_STATE_MAP[tool_name]
        if field in updated:
            continue  # Already got a newer result for this field

        content = msg.content
        if not content or content.startswith(("Hotel search failed",
                                               "Flight search failed",
                                               "Ticket search failed")):
            continue  # Tool returned an error message, skip

        try:
            data = json.loads(content)
            if isinstance(data, list) and len(data) > 0:
                state[field] = data
                updated[field] = True
                logger.info("state updated: %s ← %d items from %s", field, len(data), tool_name)
        except (json.JSONDecodeError, TypeError):
            continue  # Not valid JSON, skip

    # If any data field changed, recompute budget
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
    """Compact human-readable summary of the current plan for the prompt.

    LESSON — Why a text summary, not raw JSON?
    1. Raw JSON of the full state is 2000+ tokens. Text summary is ~300.
       Smaller prompt = faster response + lower cost.
    2. The LLM doesn't need to see _source, _degraded, or other meta fields.
       It needs: what GP, what hotels, what price. Summary strips the noise.
    3. If state is empty, we explicitly say "No plan yet" so the supervisor
       switches to planning mode based on what it reads, not on a flag.
    """
    # Check if any plan data exists
    has_data = any(state.get(f) for f in ("tickets", "transport", "hotel"))

    if not has_data:
        lines = ["No plan exists yet."]
        # Include any known parameters
        if state.get("gp_name"):
            lines.append(f"GP: {state['gp_name']} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
        if state.get("origin"):
            lines.append(f"Origin: {state['origin']}")
        if state.get("budget"):
            lines.append(f"Budget: EUR {state['budget']}")
        return "\n".join(lines)

    lines = []
    lines.append(f"GP: {state.get('gp_name', '?')} in {state.get('gp_city', '?')} ({state.get('gp_date', '?')})")
    lines.append(f"Origin: {state.get('origin', '?')}")
    lines.append(f"Budget: EUR {state.get('budget', '?')}")
    lines.append(f"Extra days: {state.get('extra_days', 0)}")
    if state.get("special_requests"):
        lines.append(f"Special requests: {state['special_requests']}")

    if state.get("tickets"):
        lines.append("\nTickets:")
        for t in state["tickets"]:
            if t.get("tag") == "INFO":
                continue
            lines.append(f"  - [{t.get('tag', '')}] {t.get('name', '')} EUR {t.get('price', '?')}")

    if state.get("transport"):
        lines.append("\nFlights:")
        for t in state["transport"]:
            if t.get("tag") == "INFO":
                continue
            lines.append(f"  - [{t.get('tag', '')}] {t.get('summary', '')} EUR {t.get('price', '?')}")

    if state.get("hotel"):
        lines.append("\nHotels:")
        for h in state["hotel"]:
            if h.get("tag") == "INFO":
                continue
            lines.append(f"  - [{h.get('tag', '')}] {h.get('name', '')} EUR {h.get('price_per_night', '?')}/night")

    bs = state.get("budget_summary") or {}
    if bs:
        lines.append(f"\nBudget: EUR {bs.get('total', '?')} / EUR {bs.get('budget', '?')} "
                      f"({'within budget' if bs.get('within_budget') else 'OVER BUDGET'})")

    # LESSON — "Tool-ready parameters" section.
    # The LLM needs to know what values to pass when calling tools.
    # Showing "GP: Italian GP in Monza (Sep 6)" is human-readable but
    # the LLM might not realize it should pass city="Monza", checkin="Sep 6"
    # to search_hotels_tool. We spell it out explicitly.
    lines.append("\n--- Tool parameters (use these when calling tools) ---")
    lines.append(f"gp_name: {state.get('gp_name', '?')}")
    lines.append(f"city: {state.get('gp_city', '?')}")
    lines.append(f"date: {state.get('gp_date', '?')}")
    lines.append(f"origin: {state.get('origin', '?')}")
    lines.append(f"budget: {state.get('budget', '?')}")
    days = 3 + int(state.get("extra_days", 0) or 0)
    lines.append(f"trip_days: {days}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def refine_plan(state: dict, user_message: str) -> tuple[dict, str]:
    """Universal entry point for chat-based interaction.

    Handles both initial planning (empty state) and refinement (existing plan).

    LESSON — Why return (state, reply) instead of just mutating state in place?
    Because the caller might want to:
    1. Compare old state vs new state (for undo/redo)
    2. Decide whether to accept the changes
    3. Run tests with deterministic input/output
    Returning a new state (even though we mutate the dict) makes the
    data flow explicit. The reply string is for the user-facing UI.

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

    # ── Create and invoke supervisor ─────────────────────────────
    supervisor = create_react_agent(
        model=llm,
        tools=SUPERVISOR_TOOLS,
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
    # LESSON: This is where state actually changes. Everything above
    # was pure (read state, call LLM, get messages). Only HERE do we
    # write to state, and only based on what the supervisor decided.
    updated_fields = _apply_tool_updates(state, messages)

    if updated_fields:
        logger.info("refine_plan: state fields updated: %s", list(updated_fields.keys()))
    else:
        logger.info("refine_plan: no state changes (supervisor answered without calling tools)")

    return state, reply
