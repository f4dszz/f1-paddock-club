"""State-update helpers for the refinement supervisor."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import ToolMessage

from tools.recompute import recompute_budget as _raw_recompute_budget

logger = logging.getLogger(__name__)


TOOL_STATE_MAP: dict[str, str] = {
    "search_hotels_tool": "hotel",
    "search_flights_tool": "transport",
    "search_tickets_tool": "tickets",
    "update_itinerary_tool": "itinerary",
    "update_tour_tool": "tour",
}

TOOL_FAILURE_PREFIXES = (
    "Hotel search failed",
    "Flight search failed",
    "Ticket search failed",
    "Itinerary update failed",
    "Tour update failed",
    "Budget recomputation failed",
)


def count_tool_messages(messages: list) -> int:
    return sum(1 for m in messages if isinstance(m, ToolMessage))


def collect_failed_tool_details(messages: list) -> dict[str, str]:
    failed: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content or ""
        if content.startswith(TOOL_FAILURE_PREFIXES):
            name = getattr(msg, "name", "unknown_tool")
            failed.setdefault(name, content)
    return failed


def collect_failed_tools(messages: list) -> list[str]:
    return list(collect_failed_tool_details(messages).keys())


def apply_tool_updates(state: dict, messages: list) -> dict[str, bool]:
    """Apply the last successful result for each state-writing tool."""
    updated: dict[str, bool] = {}

    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue

        tool_name = getattr(msg, "name", None)
        if not tool_name or tool_name not in TOOL_STATE_MAP:
            continue

        field = TOOL_STATE_MAP[tool_name]
        if field in updated:
            continue

        content = msg.content
        if not content or content.startswith(TOOL_FAILURE_PREFIXES):
            continue

        try:
            data = json.loads(content)
            if isinstance(data, list) and len(data) > 0:
                state[field] = data
                updated[field] = True
                logger.info("state updated: %s <- %d items from %s", field, len(data), tool_name)
        except (json.JSONDecodeError, TypeError):
            continue

    if updated:
        try:
            state["budget_summary"] = _raw_recompute_budget(state)
            state["budget_ok"] = state["budget_summary"].get("within_budget", False)
            bs = state["budget_summary"]
            bs_cur = bs.get("currency", state.get("currency", "EUR"))
            logger.info(
                "budget recomputed after state update: %s %.0f / %s %.0f",
                bs_cur,
                bs["total"],
                bs_cur,
                bs["budget"],
            )
        except Exception:
            logger.exception("budget recomputation failed after state update")

    return updated
