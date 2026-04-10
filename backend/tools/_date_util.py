"""Date normalization utility for tool functions.

WHY this module exists:
User input and state fields may contain dates in many formats:
    "Sep 7", "September 7, 2026", "2026-09-07", "9/7/2026"

SerpAPI's engines (google_flights, google_hotels) strictly require ISO
format: "2026-09-07". Rather than forcing every upstream caller to
normalize, we do it once here at the tool layer boundary.

Design principle: VALIDATE AT SYSTEM BOUNDARIES.
The tool layer is the boundary between our internal state (flexible)
and external APIs (strict). Normalization belongs here, not in graph.py
or in the agents.
"""

from __future__ import annotations
import logging
import re
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# Current year as default when the year is missing from the date string
_DEFAULT_YEAR = 2026

# Common date patterns to try (order matters — more specific first)
_FORMATS = [
    "%Y-%m-%d",         # 2026-09-07 (ISO, ideal)
    "%b %d, %Y",        # Sep 7, 2026
    "%B %d, %Y",        # September 7, 2026
    "%b %d %Y",         # Sep 7 2026
    "%B %d %Y",         # September 7 2026
    "%m/%d/%Y",         # 9/7/2026
    "%d/%m/%Y",         # 7/9/2026 (ambiguous, but we try)
    "%b %d",            # Sep 7 (no year)
    "%B %d",            # September 7 (no year)
]


def normalize_date(date_str: str, default_year: int = _DEFAULT_YEAR) -> str:
    """Convert a flexible date string to ISO format (YYYY-MM-DD).

    Args:
        date_str: Date in any reasonable format.
        default_year: Year to assume when the input has no year.

    Returns:
        ISO formatted date string, e.g. "2026-09-07".
        If parsing fails, returns the original string (let the API
        decide whether to accept it — fail there, not here).

    Examples:
        normalize_date("Sep 7")           → "2026-09-07"
        normalize_date("2026-09-07")      → "2026-09-07"
        normalize_date("September 7, 2026") → "2026-09-07"
    """
    if not date_str or not date_str.strip():
        return ""

    clean = date_str.strip()

    for fmt in _FORMATS:
        try:
            parsed = datetime.strptime(clean, fmt)
            # If the format didn't include year, datetime defaults to 1900
            if parsed.year < 2000:
                parsed = parsed.replace(year=default_year)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    logger.warning("normalize_date: could not parse '%s', passing through", date_str)
    return clean


def compute_checkout(checkin: str, nights: int) -> str:
    """Compute a checkout date from a checkin date + number of nights.

    Returns ISO format string. If checkin can't be parsed, returns "".
    """
    iso = normalize_date(checkin)
    try:
        d = date.fromisoformat(iso)
        return (d + timedelta(days=nights)).isoformat()
    except (ValueError, TypeError):
        return ""
