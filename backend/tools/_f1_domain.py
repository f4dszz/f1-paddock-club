"""F1 race-weekend domain knowledge — single facade over the calendar.

WHY this module exists:
The base race calendar (`_race_calendar.py`) holds canonical row data.
This module exposes the *enriched* view — circuit name, weekend session
schedule (Friday/Saturday/Sunday derived from the race date), night-race
flag, recommended stay zones, and one-line commute notes. Agents and
tools call into this layer instead of growing their own ad-hoc dicts.

Design notes:
- All public functions handle unknown gp_name by logging a warning and
  returning None / empty containers — never raising — so callers do not
  need defensive try/except.
- The session schedule uses date-only ISO strings. Exact local clock
  times are unknown until F1 publishes the timetable; populating them
  here would be hallucination. Callers that need clock times should
  treat None values as "TODO".
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from ._race_calendar import all_races, get_race

logger = logging.getLogger(__name__)


# ── Core enrichment ─────────────────────────────────────────────────

def _session_schedule_from_race_date(race_date_iso: Optional[str]) -> dict:
    """Build a Friday/Saturday/Sunday session date map from the race date.

    F1 race weekends always run Fri (FP1/FP2 or FP1/Sprint Quali on Sprint
    weekends), Sat (FP3/Quali or Sprint/Quali), Sun (Race). Clock times
    are unknown — we return ISO date strings so the caller can format
    them. Returns {} when race_date is missing.
    """
    if not race_date_iso:
        return {}
    try:
        sunday = date.fromisoformat(race_date_iso)
    except ValueError:
        logger.warning("_f1_domain: malformed race_date %r", race_date_iso)
        return {}
    friday = sunday - timedelta(days=2)
    saturday = sunday - timedelta(days=1)
    return {
        "friday": friday.isoformat(),
        "saturday": saturday.isoformat(),
        "sunday": sunday.isoformat(),
    }


def enrich(gp_name: str) -> Optional[dict]:
    """Return the full race row plus derived session_schedule.

    Returns None (and logs a warning) when the GP name is unknown.
    Returned dict is a shallow copy — callers may mutate freely.
    """
    race = get_race(gp_name)
    if not race:
        logger.warning("_f1_domain.enrich: unknown gp_name=%r", gp_name)
        return None
    enriched = dict(race)
    # session_schedule is computed on-demand so calendar data stays static.
    if "session_schedule" not in enriched:
        enriched["session_schedule"] = _session_schedule_from_race_date(
            enriched.get("race_date")
        )
    return enriched


# ── Convenience accessors used by tools / agents ────────────────────

def circuit_name_for(gp_name: str) -> Optional[str]:
    """Return the official circuit name for a GP, or None if unknown."""
    race = get_race(gp_name)
    if not race:
        logger.warning("_f1_domain.circuit_name_for: unknown gp_name=%r", gp_name)
        return None
    return race.get("circuit_name")


def night_race_set() -> set[str]:
    """Return the set of GP names that race under floodlights / at night."""
    return {
        r["gp_name"]
        for r in all_races(include_not_scheduled=True)
        if r.get("is_night_race")
    }


def stay_zones_for(gp_name: str) -> list[str]:
    """Return canonical hotel-search neighbourhoods for a GP. Empty if unknown."""
    race = get_race(gp_name)
    if not race:
        logger.warning("_f1_domain.stay_zones_for: unknown gp_name=%r", gp_name)
        return []
    return list(race.get("stay_zones") or [])


def commute_notes_for(gp_name: str) -> Optional[str]:
    """Return the one-line commute tip for a GP, or None if unknown/missing."""
    race = get_race(gp_name)
    if not race:
        logger.warning("_f1_domain.commute_notes_for: unknown gp_name=%r", gp_name)
        return None
    return race.get("commute_notes")
