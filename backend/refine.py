"""Lane 2 — Supervisor agent for interactive plan refinement.

After Lane 1 (the LangGraph DAG) generates the initial travel plan,
this supervisor handles all subsequent user messages:

    "酒店不要市中心的"     → calls search_hotels(near='circuit')
    "直飞, no stops"      → calls search_flights(stops=0)
    "budget 太高了"        → calls recompute_budget, then suggests tradeoffs

The supervisor is a ReAct agent: it thinks about what the user wants,
decides which tool(s) to call, interprets results, and responds. It
does NOT re-run the entire pipeline — it makes targeted updates.

Usage (CLI):
    from graph import plan_trip
    from refine import refine_plan

    state = plan_trip({...})                      # Lane 1
    state, reply = refine_plan(state, "只要 Marriott")  # Lane 2
    state, reply = refine_plan(state, "直飞")          # Lane 2 again

The supervisor is designed so it COULD eventually replace Lane 1 for
initial planning too (supervisor-only mode). For now it's Lane 2 only.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from llm import get_llm

logger = logging.getLogger(__name__)


# ── Supervisor system prompt ─────────────────────────────────────────

SUPERVISOR_PROMPT = """\
You are the F1 Paddock Club travel supervisor — a concierge AI that
helps users plan and refine their Formula 1 Grand Prix trip.

Current focus: Formula 1 Grand Prix events (2026 season).

The user already has a travel plan (summarized below). They are now
asking for changes or have follow-up questions.

Your rules:
1. Understand EXACTLY what the user wants to change.
2. Call ONLY the tools needed for that change — do NOT re-plan everything.
   If the user only wants to change hotels, do NOT touch flights or tickets.
3. After any hotel/flight/ticket change, ALWAYS call recompute_budget to
   check if the plan is still within budget.
4. If a tool returns an error or empty result, explain honestly and
   suggest alternatives (cheaper hotel? different dates? fewer days?).
5. Respond in the SAME LANGUAGE the user writes in. If they write Chinese,
   respond in Chinese. If English, respond in English.
6. Keep responses concise — the user wants answers, not essays.

Current plan:
{state_summary}
"""


# ── Tool wrappers for the supervisor ─────────────────────────────────
#
# These wrap our raw tool functions (from backend/tools/) into LangChain
# @tool objects that the ReAct agent can call. The wrappers catch
# exceptions and return a descriptive error string instead of crashing
# the agent loop — this lets the supervisor reason about failures.


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
    """Search for hotel options. Use this when the user wants to change
    their hotel — different brand, location, price range, or star rating.
    Returns a JSON list of hotel options."""
    try:
        from tools.search_hotels import search_hotels
        kwargs: dict[str, Any] = {"city": city, "checkin": checkin, "checkout": checkout}
        if brand:
            kwargs["brand"] = brand
        if stars > 0:
            kwargs["stars"] = stars
        if max_price > 0:
            kwargs["max_price"] = max_price
        if near:
            kwargs["near"] = near
        results = search_hotels(**kwargs)
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
    """Search for flight options. Use this when the user wants to change
    their flights — different route, direct only, different dates, or cabin.
    Returns a JSON list of flight options."""
    try:
        from tools.search_flights import search_flights
        kwargs: dict[str, Any] = {"origin": origin, "dest": dest, "date": date}
        if return_date:
            kwargs["return_date"] = return_date
        if stops >= 0:
            kwargs["stops"] = stops
        if cabin:
            kwargs["cabin"] = cabin
        results = search_flights(**kwargs)
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
    """Search for F1 ticket / grandstand options. Use this when the user
    wants different ticket types, price ranges, or grandstand locations.
    Returns a JSON list of ticket options."""
    try:
        from tools.search_tickets import search_tickets
        kwargs: dict[str, Any] = {"gp_name": gp_name, "year": year}
        if pref:
            kwargs["pref"] = pref
        if max_price > 0:
            kwargs["max_price"] = max_price
        results = search_tickets(**kwargs)
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.exception("search_tickets_tool failed")
        return f"Ticket search failed: {e}. Try checking tickets.formula1.com directly."


@tool
def recompute_budget_tool(state_json: str) -> str:
    """Recompute the budget after any change to hotels, flights, or tickets.
    ALWAYS call this after making changes. Pass the current state as JSON.
    Returns updated budget summary."""
    try:
        from tools.recompute import recompute_budget
        state = json.loads(state_json)
        summary = recompute_budget(state)
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        logger.exception("recompute_budget_tool failed")
        return f"Budget recomputation failed: {e}"


# ── All tools available to the supervisor ────────────────────────────

SUPERVISOR_TOOLS = [
    search_hotels_tool,
    search_flights_tool,
    search_tickets_tool,
    recompute_budget_tool,
]


# ── Build and invoke the supervisor ──────────────────────────────────

def _format_state(state: dict) -> str:
    """Compact human-readable summary of the current plan for the prompt."""
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
            lines.append(f"  - {t.get('tag', '')} {t.get('name', '')} EUR {t.get('price', '?')}")

    if state.get("transport"):
        lines.append("\nFlights:")
        for t in state["transport"]:
            lines.append(f"  - {t.get('tag', '')} {t.get('summary', '')} EUR {t.get('price', '?')}")

    if state.get("hotel"):
        lines.append("\nHotels:")
        for h in state["hotel"]:
            lines.append(f"  - {h.get('tag', '')} {h.get('name', '')} EUR {h.get('total_price', '?')} ({h.get('nights', '?')}n)")

    bs = state.get("budget_summary") or {}
    if bs:
        lines.append(f"\nBudget total: EUR {bs.get('total', '?')} / EUR {bs.get('budget', '?')}")
        lines.append(f"Within budget: {bs.get('within_budget', '?')}")

    return "\n".join(lines)


def refine_plan(state: dict, user_message: str) -> tuple[dict, str]:
    """Run the supervisor agent on a user's refinement message.

    Args:
        state: Current TravelPlanState dict (output of plan_trip or previous refine_plan).
        user_message: The user's natural language request (any language).

    Returns:
        (updated_state, reply_text): The state with any modifications applied,
        and the supervisor's reply to the user.
    """
    llm = get_llm(temperature=0.3, max_tokens=2048)
    if llm is None:
        return state, "LLM not configured — cannot process refinement requests."

    # Build the supervisor with the current state baked into the prompt
    state_summary = _format_state(state)
    prompt = SUPERVISOR_PROMPT.format(state_summary=state_summary)

    supervisor = create_react_agent(
        model=llm,
        tools=SUPERVISOR_TOOLS,
        prompt=prompt,
    )

    logger.info("refine_plan: invoking supervisor with message: %s", user_message[:100])

    # Invoke the supervisor
    result = supervisor.invoke({
        "messages": [("user", user_message)],
    })

    # Extract the final AI reply from the message history
    messages = result.get("messages", [])
    reply = ""
    for msg in reversed(messages):
        # Find the last AI message (not a tool message)
        if hasattr(msg, "content") and not hasattr(msg, "tool_call_id"):
            if msg.content:
                reply = msg.content
                break

    if not reply:
        reply = "I processed your request but couldn't generate a response. Please try rephrasing."

    # TODO (Phase 3.5+): parse tool call results and apply state updates.
    # For now the supervisor reasons about changes but doesn't directly
    # mutate the state dict. State mutation will be wired when specialists
    # return structured ToolUpdate objects.
    logger.info("refine_plan: supervisor replied (%d chars)", len(reply))

    return state, reply
