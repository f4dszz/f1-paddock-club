"""Unified F1 race calendar — single source of truth for all date logic.

This module is the ONLY place GP names, cities, and race dates are defined.
All other modules (search_tickets, _trip_dates, agents, frontend) should
import from here instead of maintaining their own date constants.

Data source: Official F1 2026 calendar (formula1.com/en/racing/2026),
cross-referenced with ESPN, Sky Sports. Last verified: 2026-04-15.

Design principles:
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

# ─── F1 domain fields (added in roadmap §1) ─────────────────────────
# circuit_name        — official venue name (used by search_tickets disambiguation)
# is_night_race       — true for races with race-start under floodlights
# stay_zones          — 2-4 canonical neighbourhoods/cities used for hotel search
# commute_notes       — one-line tip about the trickiest commute step
# session_schedule    — Friday/Saturday/Sunday derived from race_date.
#                       Exact clock times are unknown until F1 publishes the
#                       weekend timetable, so values are date-only strings
#                       (TODO: enrich with local clock times once known).
_CALENDAR_2026: list[dict] = [
    {"round": 1,  "gp_name": "Australian GP",         "city": "Melbourne",    "country": "Australia",     "race_date": "2026-03-08",
     "circuit_name": "Albert Park Circuit", "is_night_race": False,
     "stay_zones": ["Melbourne CBD", "St Kilda", "Albert Park"],
     "commute_notes": "Tram lines 96/12 run from CBD to the Albert Park gates; allow 25 minutes on race morning."},
    {"round": 2,  "gp_name": "Chinese GP",            "city": "Shanghai",     "country": "China",         "race_date": "2026-03-15", "sprint": True,
     "circuit_name": "Shanghai International Circuit", "is_night_race": False,
     "stay_zones": ["Jiading", "Anting", "Shanghai Hongqiao"],
     "commute_notes": "Metro Line 11 from central Shanghai to Anting then circuit shuttle; budget 90 minutes door-to-door."},
    {"round": 3,  "gp_name": "Japanese GP",           "city": "Suzuka",       "country": "Japan",         "race_date": "2026-03-29",
     "circuit_name": "Suzuka International Racing Course", "is_night_race": False,
     "stay_zones": ["Suzuka", "Nagoya", "Yokkaichi"],
     "commute_notes": "Kintetsu Suzuka-Sakanoshita is the closest station; Nagoya stays trade comfort for a longer commute."},
    {"round": 4,  "gp_name": "Miami GP",              "city": "Miami",        "country": "USA",           "race_date": "2026-05-03", "sprint": True,
     "circuit_name": "Miami International Autodrome", "is_night_race": False,
     "stay_zones": ["Miami Gardens", "Aventura", "Hollywood FL", "Miami Beach"],
     "commute_notes": "Hard Rock Stadium parking is constrained; rideshare drop-off zones are the saner option."},
    {"round": 5,  "gp_name": "Canadian GP",           "city": "Montreal",     "country": "Canada",        "race_date": "2026-05-24", "sprint": True,
     "circuit_name": "Circuit Gilles Villeneuve", "is_night_race": False,
     "stay_zones": ["Old Montreal", "Downtown Montreal", "Plateau-Mont-Royal"],
     "commute_notes": "Take the Yellow metro line one stop to Jean-Drapeau; the circuit is on the same island."},
    {"round": 6,  "gp_name": "Monaco GP",             "city": "Monte Carlo",  "country": "Monaco",        "race_date": "2026-06-07",
     "circuit_name": "Circuit de Monaco", "is_night_race": False,
     "stay_zones": ["Monte Carlo", "La Condamine", "Beausoleil", "Nice"],
     "commute_notes": "Most of the principality closes to cars; trains from Nice-Ville stay reliable when roads do not."},
    {"round": 7,  "gp_name": "Barcelona-Catalunya GP","city": "Barcelona",    "country": "Spain",         "race_date": "2026-06-14",
     "circuit_name": "Circuit de Barcelona-Catalunya", "is_night_race": False,
     "stay_zones": ["Barcelona Eixample", "Montmelo", "Granollers"],
     "commute_notes": "RENFE R2 Nord from Passeig de Gracia to Montmelo runs every ~30 minutes on race weekend."},
    {"round": 8,  "gp_name": "Austrian GP",           "city": "Spielberg",    "country": "Austria",       "race_date": "2026-06-28",
     "circuit_name": "Red Bull Ring", "is_night_race": False,
     "stay_zones": ["Spielberg", "Knittelfeld", "Zeltweg", "Graz"],
     "commute_notes": "Rural Styria has thin public transport; a rental car or organised shuttle is effectively required."},
    {"round": 9,  "gp_name": "British GP",            "city": "Silverstone",  "country": "UK",            "race_date": "2026-07-05", "sprint": True,
     "circuit_name": "Silverstone Circuit", "is_night_race": False,
     "stay_zones": ["Silverstone", "Towcester", "Northampton", "Milton Keynes"],
     "commute_notes": "Silverstone has no rail station; park-and-ride from Northampton or Milton Keynes is the standard route."},
    {"round": 10, "gp_name": "Belgian GP",            "city": "Spa",          "country": "Belgium",       "race_date": "2026-07-19",
     "circuit_name": "Circuit de Spa-Francorchamps", "is_night_race": False,
     "stay_zones": ["Spa", "Stavelot", "Francorchamps", "Liege"],
     "commute_notes": "Ardennes hills mean rural roads jam early; leaving from Liege requires a 90-minute buffer."},
    {"round": 11, "gp_name": "Hungarian GP",          "city": "Budapest",     "country": "Hungary",       "race_date": "2026-07-26",
     "circuit_name": "Hungaroring", "is_night_race": False,
     "stay_zones": ["Budapest Pest side", "Budapest Buda side", "Mogyorod"],
     "commute_notes": "Suburban HEV trains and dedicated race-day buses run from Ors vezer tere; allow ~75 minutes."},
    {"round": 12, "gp_name": "Dutch GP",              "city": "Zandvoort",    "country": "Netherlands",   "race_date": "2026-08-23", "sprint": True,
     "circuit_name": "Circuit Zandvoort", "is_night_race": False,
     "stay_zones": ["Zandvoort", "Haarlem", "Amsterdam"],
     "commute_notes": "NS trains add race-only services to Zandvoort aan Zee; private cars are essentially banned at the circuit."},
    {"round": 13, "gp_name": "Italian GP",            "city": "Monza",        "country": "Italy",         "race_date": "2026-09-06",
     "circuit_name": "Autodromo Nazionale Monza", "is_night_race": False,
     "stay_zones": ["Monza", "Milan central", "Como", "Lecco"],
     "commute_notes": "Trenord regional trains from Milano Centrale to Monza run every 10-15 minutes on race weekend."},
    {"round": 14, "gp_name": "Spanish GP",            "city": "Madrid",       "country": "Spain",         "race_date": "2026-09-13",
     "circuit_name": "Madring (IFEMA Madrid)", "is_night_race": False,
     "stay_zones": ["Madrid centro", "Chamartin", "Hortaleza", "Barajas"],
     "commute_notes": "Metro line 8 to Feria de Madrid drops you next to the IFEMA paddock entrance."},
    {"round": 15, "gp_name": "Azerbaijan GP",         "city": "Baku",         "country": "Azerbaijan",    "race_date": "2026-09-26",
     "circuit_name": "Baku City Circuit", "is_night_race": False,
     "stay_zones": ["Baku old city", "Baku seaside", "Sabail"],
     "commute_notes": "The track is in central Baku; many hotels are inside the circuit perimeter and need accreditation to access."},
    {"round": 16, "gp_name": "Singapore GP",          "city": "Singapore",    "country": "Singapore",     "race_date": "2026-10-11", "sprint": True,
     "circuit_name": "Marina Bay Street Circuit", "is_night_race": True,
     "stay_zones": ["Marina Bay", "City Hall", "Bugis", "Orchard"],
     "commute_notes": "MRT to Promenade or Esplanade beats taxis once roads close; the race runs at night so plan dinner first."},
    {"round": 17, "gp_name": "United States GP",      "city": "Austin",       "country": "USA",           "race_date": "2026-10-25",
     "circuit_name": "Circuit of the Americas", "is_night_race": False,
     "stay_zones": ["Austin downtown", "South Congress", "Del Valle"],
     "commute_notes": "Rideshare surge is brutal post-race; the official park-and-ride from downtown is faster on Sunday night."},
    {"round": 18, "gp_name": "Mexico City GP",        "city": "Mexico City",  "country": "Mexico",        "race_date": "2026-11-01",
     "circuit_name": "Autodromo Hermanos Rodriguez", "is_night_race": False,
     "stay_zones": ["Roma Norte", "Condesa", "Polanco", "Centro Historico"],
     "commute_notes": "Metro line 9 to Ciudad Deportiva is the fastest race-day route; altitude makes long walks tiring."},
    {"round": 19, "gp_name": "Brazilian GP",          "city": "Sao Paulo",    "country": "Brazil",        "race_date": "2026-11-08",
     "circuit_name": "Autodromo Jose Carlos Pace (Interlagos)", "is_night_race": False,
     "stay_zones": ["Sao Paulo Jardins", "Vila Olimpia", "Interlagos"],
     "commute_notes": "CPTM line 9 to Autodromo station; private cars hit gridlock on Avenida Interlagos during exits."},
    {"round": 20, "gp_name": "Las Vegas GP",          "city": "Las Vegas",    "country": "USA",           "race_date": "2026-11-22",
     "circuit_name": "Las Vegas Strip Circuit", "is_night_race": True,
     "stay_zones": ["Las Vegas Strip", "Paradise", "Downtown Las Vegas"],
     "commute_notes": "The Strip closes for the night race; staying inside the circuit footprint avoids long late-night walks."},
    {"round": 21, "gp_name": "Qatar GP",              "city": "Lusail",       "country": "Qatar",         "race_date": "2026-11-29",
     "circuit_name": "Lusail International Circuit", "is_night_race": True,
     "stay_zones": ["Lusail", "West Bay Doha", "The Pearl"],
     "commute_notes": "Doha Metro Red Line to Lusail then a short shuttle; the race runs after sunset under floodlights."},
    {"round": 22, "gp_name": "Abu Dhabi GP",          "city": "Abu Dhabi",    "country": "UAE",           "race_date": "2026-12-06",
     "circuit_name": "Yas Marina Circuit", "is_night_race": True,
     "stay_zones": ["Yas Island", "Saadiyat Island", "Abu Dhabi Corniche"],
     "commute_notes": "Yas Island hotels are walking distance to the gates; race start is twilight, expect floodlights for the finish."},
    # ── Not scheduled for 2026 (kept so lookups don't return None) ──
    {"round": None, "gp_name": "Bahrain GP",          "city": "Sakhir",       "country": "Bahrain",       "race_date": None, "not_scheduled": True, "calendar_note": "Not on current 2026 calendar",
     "circuit_name": "Bahrain International Circuit", "is_night_race": True,
     "stay_zones": ["Manama", "Juffair", "Sakhir"],
     "commute_notes": "Race normally runs after sunset; rental car or pre-booked shuttle from Manama is standard."},
    {"round": None, "gp_name": "Saudi Arabian GP",    "city": "Jeddah",       "country": "Saudi Arabia",  "race_date": None, "not_scheduled": True, "calendar_note": "Not on current 2026 calendar",
     "circuit_name": "Jeddah Corniche Circuit", "is_night_race": True,
     "stay_zones": ["Jeddah Corniche", "Al Hamra", "Jeddah city centre"],
     "commute_notes": "Street circuit on the Corniche; many waterfront hotels are walking distance to gates."},
    {"round": None, "gp_name": "Emilia Romagna GP",   "city": "Imola",        "country": "Italy",         "race_date": None, "not_scheduled": True, "calendar_note": "Discontinued for 2026",
     "circuit_name": "Autodromo Enzo e Dino Ferrari", "is_night_race": False,
     "stay_zones": ["Imola", "Bologna", "Faenza"],
     "commute_notes": "Trenitalia regionals from Bologna to Imola run every 30 minutes; the circuit is a 15-minute walk from the station."},
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
