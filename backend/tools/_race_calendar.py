"""Unified F1 race calendar — single source of truth for all date logic.

This module is the ONLY place GP names, cities, and race dates are defined.
All other modules (search_tickets, _trip_dates, agents, frontend) should
import from here instead of maintaining their own date constants.

Data source: Official F1 2026 calendar (formula1.com/en/racing/2026),
cross-referenced with ESPN, Sky Sports. Last verified: 2026-04-15.

Design principles (per supervisor Round 010):
- Static data only: gp_name, city, country, race_date, round
- Runtime state (is_past, days_until) computed by helpers, never stored
- calendar_note: optional, only for officially confirmed status changes
"""

from __future__ import annotations
from datetime import date
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# Canonical 2026 race calendar
#
# Primary source: formula1.com/en/racing/2026 (official calendar page)
# Update source: formula1.com/en/latest/article (official calendar articles)
# Conflict rule: calendar page > article > per-race page
# Last checked: 2026-04-15
#
# 22 scheduled races.
# Notable: Barcelona-Catalunya GP AND Spanish GP (Madrid) are separate rounds.
# 3 entries marked not_scheduled:
#   - Bahrain GP: not on current 2026 calendar (Middle East situation)
#   - Saudi Arabian GP: not on current 2026 calendar (Middle East situation)
#   - Emilia Romagna GP: discontinued (Imola not renewed)
# ═══════════════════════════════════════════════════════════════════════

_CALENDAR_2026: list[dict] = [
    {"round": 1,  "gp_name": "Australian GP",      "city": "Melbourne",    "country": "Australia",     "race_date": "2026-03-08"},
    {"round": 2,  "gp_name": "Chinese GP",          "city": "Shanghai",     "country": "China",         "race_date": "2026-03-15", "sprint": True},
    {"round": 3,  "gp_name": "Japanese GP",         "city": "Suzuka",       "country": "Japan",         "race_date": "2026-03-29"},
    {"round": 4,  "gp_name": "Miami GP",            "city": "Miami",        "country": "USA",           "race_date": "2026-05-03", "sprint": True},
    {"round": 5,  "gp_name": "Canadian GP",         "city": "Montreal",     "country": "Canada",        "race_date": "2026-05-24", "sprint": True},
    {"round": 6,  "gp_name": "Monaco GP",                "city": "Monte Carlo",        "country": "Monaco",        "race_date": "2026-06-07"},
    {"round": 7,  "gp_name": "Barcelona-Catalunya GP",  "city": "Barcelona",          "country": "Spain",         "race_date": "2026-06-14"},
    {"round": 8,  "gp_name": "Austrian GP",              "city": "Spielberg",          "country": "Austria",       "race_date": "2026-06-28"},
    {"round": 9,  "gp_name": "British GP",               "city": "Silverstone",        "country": "UK",            "race_date": "2026-07-05", "sprint": True},
    {"round": 10, "gp_name": "Belgian GP",               "city": "Spa",                "country": "Belgium",       "race_date": "2026-07-19"},
    {"round": 11, "gp_name": "Hungarian GP",             "city": "Budapest",           "country": "Hungary",       "race_date": "2026-07-26"},
    {"round": 12, "gp_name": "Dutch GP",                 "city": "Zandvoort",          "country": "Netherlands",   "race_date": "2026-08-23", "sprint": True},
    {"round": 13, "gp_name": "Italian GP",               "city": "Monza",              "country": "Italy",         "race_date": "2026-09-06"},
    {"round": 14, "gp_name": "Spanish GP",               "city": "Madrid",             "country": "Spain",         "race_date": "2026-09-13"},
    {"round": 15, "gp_name": "Azerbaijan GP",            "city": "Baku",               "country": "Azerbaijan",    "race_date": "2026-09-26"},
    {"round": 16, "gp_name": "Singapore GP",           "city": "Singapore",          "country": "Singapore",     "race_date": "2026-10-11", "sprint": True},
    {"round": 17, "gp_name": "United States GP",     "city": "Austin",             "country": "USA",           "race_date": "2026-10-25"},
    {"round": 18, "gp_name": "Mexico City GP",       "city": "Mexico City",        "country": "Mexico",        "race_date": "2026-11-01"},
    {"round": 19, "gp_name": "Brazilian GP",         "city": "Sao Paulo",          "country": "Brazil",        "race_date": "2026-11-08"},
    {"round": 20, "gp_name": "Las Vegas GP",         "city": "Las Vegas",          "country": "USA",           "race_date": "2026-11-22"},
    {"round": 21, "gp_name": "Qatar GP",             "city": "Lusail",             "country": "Qatar",         "race_date": "2026-11-29"},
    {"round": 22, "gp_name": "Abu Dhabi GP",         "city": "Abu Dhabi",          "country": "UAE",           "race_date": "2026-12-06"},
    # ── Not scheduled for 2026 (kept so lookups don't return None) ──
    {"round": None, "gp_name": "Bahrain GP",          "city": "Sakhir",       "country": "Bahrain",       "race_date": None, "not_scheduled": True, "calendar_note": "Not on current 2026 calendar"},
    {"round": None, "gp_name": "Saudi Arabian GP",    "city": "Jeddah",       "country": "Saudi Arabia",  "race_date": None, "not_scheduled": True, "calendar_note": "Not on current 2026 calendar"},
    {"round": None, "gp_name": "Emilia Romagna GP",   "city": "Imola",        "country": "Italy",         "race_date": None, "not_scheduled": True, "calendar_note": "Discontinued for 2026"},
]

# Quick-lookup indices (built once at import time)
_BY_NAME: dict[str, dict] = {r["gp_name"]: r for r in _CALENDAR_2026}
_BY_CITY: dict[str, dict] = {r["city"].lower(): r for r in _CALENDAR_2026}


# ═══════════════════════════════════════════════════════════════════════
# Public helpers — runtime computation, never stored
# ═══════════════════════════════════════════════════════════════════════

def _is_scheduled(r: dict) -> bool:
    """Check if a race entry is scheduled (has a date and not marked not_scheduled)."""
    return r.get("race_date") is not None and not r.get("not_scheduled")


def get_race(gp_name: str) -> Optional[dict]:
    """Look up a GP by official name. Returns None if unknown GP.
    Note: returns entries even for not_scheduled races (Bahrain, etc.)
    so callers can check .get('not_scheduled') and show appropriate UI."""
    return _BY_NAME.get(gp_name)


def get_race_by_city(city: str) -> Optional[dict]:
    """Look up a GP by city name (case-insensitive)."""
    return _BY_CITY.get(city.lower())


def is_not_scheduled(gp_name: str) -> bool:
    """Check if a GP is known but not on the current 2026 calendar."""
    r = _BY_NAME.get(gp_name)
    return bool(r and r.get("not_scheduled"))


def race_date(gp_name: str) -> Optional[str]:
    """Return race date as ISO string, or None if not found/not scheduled."""
    r = _BY_NAME.get(gp_name)
    if not r:
        return None
    return r.get("race_date")


def is_past(gp_name: str, today: Optional[date] = None) -> bool:
    """Check if a GP's race date has already passed. False for not_scheduled."""
    r = _BY_NAME.get(gp_name)
    if not r or not r.get("race_date"):
        return False
    today = today or date.today()
    return date.fromisoformat(r["race_date"]) < today


def days_until(gp_name: str, today: Optional[date] = None) -> Optional[int]:
    """Days from today to the race. Negative if past. None if not scheduled."""
    r = _BY_NAME.get(gp_name)
    if not r or not r.get("race_date"):
        return None
    today = today or date.today()
    return (date.fromisoformat(r["race_date"]) - today).days


def upcoming_races(today: Optional[date] = None) -> list[dict]:
    """Return all scheduled GPs with race_date >= today, sorted by date."""
    today = today or date.today()
    return [
        r for r in _CALENDAR_2026
        if _is_scheduled(r) and date.fromisoformat(r["race_date"]) >= today
    ]


def past_races(today: Optional[date] = None) -> list[dict]:
    """Return all scheduled GPs with race_date < today, sorted by date."""
    today = today or date.today()
    return [
        r for r in _CALENDAR_2026
        if _is_scheduled(r) and date.fromisoformat(r["race_date"]) < today
    ]


def next_upcoming(today: Optional[date] = None) -> Optional[dict]:
    """Return the next upcoming GP, or None if season is over."""
    races = upcoming_races(today)
    return races[0] if races else None


def all_races(include_not_scheduled: bool = False) -> list[dict]:
    """Return the 2026 calendar. By default excludes not_scheduled entries."""
    if include_not_scheduled:
        return list(_CALENDAR_2026)
    return [r for r in _CALENDAR_2026 if _is_scheduled(r)]


def scheduled_races() -> list[dict]:
    """Return only scheduled (has date, not cancelled) races."""
    return [r for r in _CALENDAR_2026 if _is_scheduled(r)]


def gp_names(include_not_scheduled: bool = False) -> list[str]:
    """Return GP names in calendar order."""
    return [r["gp_name"] for r in all_races(include_not_scheduled)]


def race_dates_map() -> dict[str, str]:
    """Return {gp_name: race_date} dict for scheduled races only."""
    return {r["gp_name"]: r["race_date"] for r in _CALENDAR_2026 if r.get("race_date")}
