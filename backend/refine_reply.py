"""Deterministic reply helpers for the refinement supervisor."""

from __future__ import annotations

from tools._trip_dates import compute_trip_dates


FIELD_LABELS: dict[str, str] = {
    "hotel": "hotels",
    "transport": "flights",
    "tickets": "tickets",
    "itinerary": "itinerary",
    "tour": "tour",
}


def detect_date_override(messages: list, state: dict) -> bool:
    """Return true when a tool call used dates outside the saved trip dates."""
    try:
        default = compute_trip_dates(
            state.get("gp_date", ""),
            state.get("extra_days", 0),
            state.get("depart_date", "") or "",
            state.get("return_date", "") or "",
        )
    except Exception:
        return False

    default_values = {
        default.get("hotel_checkin"),
        default.get("hotel_checkout"),
        default.get("outbound_date"),
        default.get("return_date"),
    }
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tool_call in tool_calls:
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            for key in ("checkin", "checkout", "date", "return_date"):
                val = args.get(key)
                if val and val not in default_values:
                    return True
    return False


def build_deterministic_summary(
    state: dict,
    updated_fields: dict[str, bool],
    failed_tools: list[str],
    date_override: bool,
    failed_tool_details: dict[str, str] | None = None,
) -> str:
    cur = str(state.get("currency") or "EUR").upper()
    parts: list[str] = []

    if updated_fields:
        bits = []
        for field in ("tickets", "transport", "hotel", "itinerary", "tour"):
            if updated_fields.get(field):
                count = len(state.get(field, []) or [])
                label = FIELD_LABELS.get(field, field)
                bits.append(f"{label} ({count} options)")
        if bits:
            parts.append("Updated " + ", ".join(bits) + ".")

    if failed_tools:
        details = failed_tool_details or {}
        entries = []
        for tool_name in failed_tools:
            nice = tool_name.replace("_tool", "").replace("search_", "")
            detail = details.get(tool_name, "")
            if detail:
                entries.append(f"{nice} ({detail.split('. Try ', 1)[0]})")
            else:
                entries.append(nice)
        parts.append(f"Tool call failed and did not update plan: {', '.join(entries)}.")

    if (state.get("budget_summary") or {}).get("retry_exhausted"):
        parts.append("No feasible plan under the requested budget was found after retries.")

    bs = state.get("budget_summary") or {}
    if bs:
        total = bs.get("total")
        budget = bs.get("budget")
        within = "within budget" if bs.get("within_budget") else "OVER budget"
        try:
            parts.append(f"New total: {cur} {float(total):.0f} / {cur} {float(budget):.0f} - {within}.")
        except (TypeError, ValueError):
            pass

    if date_override:
        parts.append(
            "Note: those were preview searches against alternate dates - "
            "your saved trip dates didn't change. To change the trip dates "
            "themselves, re-plan with the new dates selected on the form."
        )

    if not parts:
        parts.append("Plan unchanged.")

    return " ".join(parts)
