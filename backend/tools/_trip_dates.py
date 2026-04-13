"""Pure-function trip date computation.

Given a GP race date and extra_days, computes all date boundaries
needed by flight search, hotel search, and budget calculation.

F1 race weekends run: Friday (FP1/FP2), Saturday (FP3/Qual), Sunday (Race).
The race date (gp_date) is always the Sunday.

Design: a single pure function returns a dict with all dates. Both
Lane 1 agents and Lane 2 supervisor consume the same output, ensuring
consistency. No external dependencies.
"""

from __future__ import annotations
from datetime import date, timedelta

from ._date_util import normalize_date


def compute_trip_dates(gp_date: str, extra_days: int = 0) -> dict:
    """Compute all trip date boundaries from GP race date + extra days.

    Args:
        gp_date: Race day (Sunday) in any parseable format.
        extra_days: Number of days to stay after the race.

    Returns:
        Dict with:
            race_date:      ISO str — the race Sunday
            outbound_date:  ISO str — arrival day (Friday of race week)
            return_date:    ISO str — departure day (day after last extra day)
            hotel_checkin:  ISO str — same as outbound_date
            hotel_checkout: ISO str — same as return_date
            trip_nights:    int — total nights (outbound to return)

    Example:
        >>> compute_trip_dates("Sep 6", extra_days=2)
        {
            'race_date': '2026-09-06',
            'outbound_date': '2026-09-04',   # Friday
            'return_date': '2026-09-09',     # Wednesday
            'hotel_checkin': '2026-09-04',
            'hotel_checkout': '2026-09-09',
            'trip_nights': 5,
        }
    """
    iso = normalize_date(gp_date)
    try:
        race = date.fromisoformat(iso)
    except (ValueError, TypeError):
        # Can't parse — return safe defaults so callers don't crash
        return {
            "race_date": iso,
            "outbound_date": iso,
            "return_date": iso,
            "hotel_checkin": iso,
            "hotel_checkout": iso,
            "trip_nights": 3 + max(extra_days, 0),
        }

    extra = max(int(extra_days or 0), 0)

    # Friday of race weekend = race Sunday - 2
    outbound = race - timedelta(days=2)
    # Depart the day after the last extra day
    # race (Sun) + extra_days + 1
    return_day = race + timedelta(days=extra + 1)

    nights = (return_day - outbound).days

    return {
        "race_date": race.isoformat(),
        "outbound_date": outbound.isoformat(),
        "return_date": return_day.isoformat(),
        "hotel_checkin": outbound.isoformat(),
        "hotel_checkout": return_day.isoformat(),
        "trip_nights": nights,
    }
