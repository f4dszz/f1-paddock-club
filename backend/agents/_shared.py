"""Shared internals for the planning-graph agent nodes.

Holds tiny helpers used by multiple agent modules (`_msg`, `_trip_days`,
constraint-intent helpers) plus the `parse_input` graph-entry node, which
is too small to deserve its own file and only ever runs as the first
node in `graph.py`.
"""
from __future__ import annotations

import logging
import re

from state import TravelPlanState
from tools._trip_dates import trip_nights as _trip_days  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)


# ── Constraint-intent regex / vocabulary ─────────────────────────────
# Used by Lane 1 agents (transport_agent, hotel_agent) to decide whether
# the form text already encodes a hard constraint before falling through
# to the centralized `tools._constraints` parser. Lives here because both
# `transport.py` and `hotel.py` need it; promoting it to `tools/`
# would create a Lane 1/Lane 2 cross-import that we want to avoid.
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
    """Create a streaming status message and mirror it to logs."""
    logger.info("[%s] %s", agent, text)
    return {"agent": agent, "text": text, "type": "status"}


# ── parse_input — graph-entry node ───────────────────────────────────
def parse_input(state: TravelPlanState) -> dict:
    """Validate and normalize user input. First node in the planning graph."""
    return {
        "messages": [_msg("concierge", f"Planning your {state['gp_name']} trip from {state['origin']}...")],
        "budget_ok": False,
        "retry_count": 0,
    }
