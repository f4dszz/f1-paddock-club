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

__all__ = [
    "search_flights",
    "search_hotels",
    "search_tickets",
    "search_web",
    "recompute_budget",
    "clear_cache",
    "query_parallel",
    "DegradationReport",
]
