"""Hard constraint reconciliation for persisted refinement results.

The supervisor can ask tools for direct flights or specific hotel brands, but
provider results and fallbacks can still be noisy. This module is the final
server-side guardrail that removes cards contradicting durable constraints.
"""

from __future__ import annotations

import logging
import re

from tools._constraints import extract_hotel_brands, normalize_constraints
from tools.recompute import recompute_budget as _raw_recompute_budget

logger = logging.getLogger(__name__)

_CONNECTION_TEXT_RE = re.compile(
    r"\b[1-9]\d*\s*stops?\b|\bconnection\b|\blayover\b|\bvia\b|转机|中转|轉機|中轉",
    re.IGNORECASE,
)
_DIRECT_TEXT_RE = re.compile(r"\bdirect\b|\bnon[-\s]?stop\b|直飞|直航|直达|直達", re.IGNORECASE)


def _is_direct_flight_leg(leg: dict) -> bool:
    text = f"{leg.get('summary', '')} {leg.get('detail', '')}"
    if _CONNECTION_TEXT_RE.search(text):
        return False
    stops = leg.get("stops")
    if isinstance(stops, bool):
        return False
    if isinstance(stops, int):
        return stops == 0
    return bool(_DIRECT_TEXT_RE.search(text))


def _matches_allowed_hotel_brand(hotel: dict, allowed_brands: list[str]) -> bool:
    name = str(hotel.get("name", ""))
    detected = set(extract_hotel_brands(name))
    return any(brand in detected for brand in allowed_brands)


def _recompute_after_constraint_filter(state: dict) -> None:
    try:
        state["budget_summary"] = _raw_recompute_budget(state)
        state["budget_ok"] = state["budget_summary"].get("within_budget", False)
        bs = state["budget_summary"]
        bs_cur = bs.get("currency", state.get("currency", "EUR"))
        logger.info(
            "budget recomputed after constraint filter: %s %.0f / %s %.0f",
            bs_cur,
            bs["total"],
            bs_cur,
            bs["budget"],
        )
    except Exception:
        logger.exception("budget recomputation failed after constraint filter")


def _apply_constraint_filters(
    state: dict,
    updated_fields: dict[str, bool] | None = None,
    *,
    force: bool = True,
) -> dict[str, bool]:
    """Ensure persisted cards cannot contradict durable hard constraints."""
    touched = set((updated_fields or {}).keys())
    if not force and not (touched & {"transport", "hotel"}):
        return {}

    constraints = normalize_constraints(state.get("active_constraints"))
    updated: dict[str, bool] = {}

    if constraints.get("direct_only") and state.get("transport"):
        transport = [t for t in state.get("transport", []) if isinstance(t, dict)]
        kept: list[dict] = []
        for leg in transport:
            tag = leg.get("tag")
            if tag in {"LOCAL", "INFO"}:
                kept.append(leg)
            elif _is_direct_flight_leg(leg):
                kept.append(leg)
        if kept != transport:
            state["transport"] = kept
            updated["transport"] = True
            logger.info(
                "constraint filter applied: direct_only kept %d/%d transport items",
                len(kept),
                len(transport),
            )

    allowed_brands = constraints.get("allowed_hotel_brands") or []
    if allowed_brands and state.get("hotel"):
        hotels = [h for h in state.get("hotel", []) if isinstance(h, dict)]
        kept_hotels = [
            h for h in hotels
            if h.get("tag") == "INFO" or _matches_allowed_hotel_brand(h, allowed_brands)
        ]
        if kept_hotels != hotels:
            state["hotel"] = kept_hotels
            updated["hotel"] = True
            logger.info(
                "constraint filter applied: hotel brands %s kept %d/%d hotels",
                allowed_brands,
                len(kept_hotels),
                len(hotels),
            )

    if updated:
        _recompute_after_constraint_filter(state)
    return updated
