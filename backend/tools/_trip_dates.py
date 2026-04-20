"""Pure-function trip date computation and validation.

Computes arrival / departure / hotel check-in / check-out / nights
from the GP race date plus either an `extra_days` slider or explicit
user-supplied `depart_date` / `return_date`.

F1 race weekends run Friday (FP1/FP2), Saturday (FP3/Qual), Sunday (Race).
The race date (gp_date) is always the Sunday.

Two input modes — both shape the same output dict, so downstream
callers (Lane 1 agents, Lane 2 supervisor, budget recomputation)
don't care which mode the user picked:

1. Legacy: `gp_date` + `extra_days` → arrival is the Friday of the race
   weekend, departure is `extra_days + 1` days after the race.
2. Explicit: `gp_date` + `depart_date` + `return_date` → arrival and
   departure taken directly from the user. This is what the editable
   date picker sends.

`validate_trip_dates` is the hard gate used at the API boundary so
invalid explicit dates never reach the graph — they get rejected
with a clean 400 / WS error instead of silently falling back.

`trip_nights` is the single-source helper every caller should use
when they need "how many nights is this trip" — avoids the old
`3 + extra_days` formula scattered across agents and recompute.
"""

from __future__ import annotations
from datetime import date, timedelta

from ._date_util import normalize_date

_MAX_REASONABLE_NIGHTS = 30  # sanity limit; soft UI warning kicks in earlier


def validate_trip_dates(
    gp_date: str,
    depart_date: str = "",
    return_date: str = "",
) -> tuple[bool, str]:
    """Hard validation for user-supplied travel dates.

    Contract:
    - Both empty → OK (caller falls back to `extra_days` mode).
    - Exactly one empty → invalid (partial input is an error).
    - Both set → format must parse as YYYY-MM-DD AND depart <= return.

    Soft warnings (arriving after race, staying >14 days) are a UI
    concern, not an API concern; they don't surface here.

    Returns:
        (True, "")         — input is acceptable, proceed
        (False, reason)    — input is explicitly invalid, abort
    """
    d = (depart_date or "").strip()
    r = (return_date or "").strip()

    if not d and not r:
        return True, ""

    if not d or not r:
        return False, "depart_date and return_date must both be set (or both empty)"

    try:
        d_dt = date.fromisoformat(d)
        r_dt = date.fromisoformat(r)
    except ValueError:
        return False, "dates must be in YYYY-MM-DD format"

    # Reject same-day return (0 nights). A 0-night "trip" breaks
    # downstream semantics: the hotel agent would need to produce a
    # non-stay option, the budget line for hotels would be zero while
    # items still carry a per-night price, and the booking links
    # wouldn't work. Until we have a first-class day-trip mode, require
    # at least one night on-site.
    if d_dt >= r_dt:
        return False, "depart_date must be strictly before return_date (day-trips not yet supported)"

    if (r_dt - d_dt).days > _MAX_REASONABLE_NIGHTS:
        return False, f"trip cannot exceed {_MAX_REASONABLE_NIGHTS} nights"

    return True, ""


def compute_trip_dates(
    gp_date: str,
    extra_days: int = 0,
    depart_date: str = "",
    return_date: str = "",
) -> dict:
    """Compute trip date boundaries.

    Priority:
    1. If both `depart_date` and `return_date` are provided and parse
       cleanly, use them directly. Validation should already have run
       at the API boundary; this function trusts its inputs but still
       fails open (returns the legacy shape) on parse errors so display
       paths never crash.
    2. Otherwise compute the legacy "Friday → race Sunday + extra_days"
       shape from `gp_date` + `extra_days`.

    Returns:
        Dict with race_date, outbound_date, return_date, hotel_checkin,
        hotel_checkout, trip_nights. All ISO strings except trip_nights
        (int).
    """
    iso_race = normalize_date(gp_date)
    try:
        race = date.fromisoformat(iso_race)
    except (ValueError, TypeError):
        # gp_date itself is unparseable — return a safe skeleton
        return _legacy_shape(iso_race, iso_race, iso_race, 3 + max(int(extra_days or 0), 0))

    # Explicit-date mode
    if depart_date and return_date:
        try:
            outbound = date.fromisoformat(depart_date)
            return_day = date.fromisoformat(return_date)
            nights = (return_day - outbound).days
            return _legacy_shape(race.isoformat(), outbound.isoformat(),
                                  return_day.isoformat(), max(nights, 0))
        except ValueError:
            # Shouldn't happen if validate_trip_dates ran, but fail open
            pass

    # Legacy mode
    extra = max(int(extra_days or 0), 0)
    outbound = race - timedelta(days=2)
    return_day = race + timedelta(days=extra + 1)
    nights = (return_day - outbound).days

    return _legacy_shape(race.isoformat(), outbound.isoformat(),
                          return_day.isoformat(), nights)


def _legacy_shape(race: str, outbound: str, return_day: str, nights: int) -> dict:
    return {
        "race_date": race,
        "outbound_date": outbound,
        "return_date": return_day,
        "hotel_checkin": outbound,
        "hotel_checkout": return_day,
        "trip_nights": nights,
    }


def trip_nights(state: dict) -> int:
    """Single source of truth for "how many nights is this trip".

    Replaces the `3 + extra_days` formula that used to live in several
    places (agents/__init__.py, recompute.py). Respects explicit
    depart/return dates when present.
    """
    dates = compute_trip_dates(
        state.get("gp_date", ""),
        state.get("extra_days", 0),
        state.get("depart_date", "") or "",
        state.get("return_date", "") or "",
    )
    nights = dates.get("trip_nights")
    if isinstance(nights, int) and nights > 0:
        return nights
    # Defensive floor — agents that pre-compute items-per-night
    # shouldn't crash on zero even if the input was degenerate.
    return 1
