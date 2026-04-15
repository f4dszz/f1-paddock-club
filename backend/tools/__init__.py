"""External data tools for the F1 Paddock Club agents.

Each module wraps an external service (SerpAPI, Firecrawl, Tavily, etc.)
behind a simple function that returns data in the shape our state expects.
All tool functions are @cached with appropriate TTLs.

Lane 1 (initial planning) and Lane 2 (refinement agent) both call
these same functions — tools are the shared data layer.
"""

from .search_flights import search_flights
from .search_hotels import search_hotels
from .search_tickets import search_tickets
from .search_web import search_web
from .recompute import recompute_budget
from ._cache import clear_cache
from ._parallel import query_parallel, DegradationReport
from ._trip_dates import compute_trip_dates
from ._currency import to_eur, convert
from ._race_calendar import (
    get_race, race_date, is_past, days_until,
    upcoming_races, next_upcoming, all_races, gp_names,
)

__all__ = [
    "search_flights",
    "search_hotels",
    "search_tickets",
    "search_web",
    "recompute_budget",
    "clear_cache",
    "query_parallel",
    "DegradationReport",
    "compute_trip_dates",
    "to_eur",
    "convert",
    "get_race",
    "race_date",
    "is_past",
    "days_until",
    "upcoming_races",
    "next_upcoming",
    "all_races",
    "gp_names",
]
