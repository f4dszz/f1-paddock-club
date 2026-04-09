"""Search for F1 ticket options via Firecrawl → DuckDuckGo cascade.

Unlike flights/hotels (which have SerpAPI), F1 tickets have NO clean
public API. Our strategy:

1. Try Firecrawl to scrape the GP's official ticket page → LLM extracts
   structured TicketOption[] from the markdown.
2. If Firecrawl fails or is unconfigured, fall back to DuckDuckGo web
   search → LLM extracts from search snippets.
3. If everything fails, raise so the agent falls back to mock.

TTL is dynamic: varies by how close the race is (see _ticket_ttl).

Usage:
    from tools.search_tickets import search_tickets
    options = search_tickets("Italian GP", 2026, pref="mid")
"""

from __future__ import annotations
import logging
import os
from datetime import datetime, date

from ._cache import cached

logger = logging.getLogger(__name__)

# ── Known GP race dates for 2026 (ISO format) ───────────────────
# Source: FIA / formula1.com provisional calendar.
# Used by _ticket_ttl to compute distance-to-race.
# If a GP isn't here, we use a default TTL.
#
# This is NOT a ground-truth data file — it's a lookup table that
# helps the CACHE decide how long to keep results. It doesn't
# contain ticket prices or any user-facing data.
_RACE_DATES_2026: dict[str, str] = {
    "Bahrain GP": "2026-03-08",
    "Saudi Arabian GP": "2026-03-22",
    "Australian GP": "2026-04-12",
    "Chinese GP": "2026-04-26",
    "Japanese GP": "2026-05-10",
    "Miami GP": "2026-05-24",
    "Emilia Romagna GP": "2026-05-31",
    "Monaco GP": "2026-06-07",
    "Spanish GP": "2026-06-21",
    "Canadian GP": "2026-07-05",
    "Austrian GP": "2026-07-19",
    "British GP": "2026-08-02",
    "Belgian GP": "2026-08-16",
    "Hungarian GP": "2026-08-23",
    "Dutch GP": "2026-08-30",
    "Italian GP": "2026-09-06",
    "Azerbaijan GP": "2026-09-20",
    "Singapore GP": "2026-10-04",
    "United States GP": "2026-10-25",
    "Mexico City GP": "2026-11-01",
    "Brazilian GP": "2026-11-15",
    "Las Vegas GP": "2026-11-22",
    "Qatar GP": "2026-11-29",
    "Abu Dhabi GP": "2026-12-06",
}


def _ticket_ttl(gp_name: str, year: int = 2026, **kwargs) -> int:
    """Dynamic TTL based on distance to race day.

    Closer to race = more volatile inventory = shorter cache.

       > 180 days away → 1 day   (far future, stable)
      60–180 days away → 1 day   (mid-season, still stable)
      14–60 days away  → 3 hours (approaching, prices moving)
       < 14 days away  → 3 hours (race week, very volatile)

    The callable signature matches search_tickets's parameters so it
    can be passed directly to @cached(ttl=_ticket_ttl).
    """
    date_str = _RACE_DATES_2026.get(gp_name)
    if not date_str:
        # Unknown GP — use a conservative middle-ground TTL.
        return 12 * 3600  # 12 hours

    try:
        race_date = date.fromisoformat(date_str)
    except ValueError:
        return 12 * 3600

    days_until = (race_date - date.today()).days

    if days_until < 0:
        return 24 * 3600      # race already happened, cache 1 day
    if days_until < 14:
        return 3 * 3600       # race week — 3 hours
    if days_until < 60:
        return 3 * 3600       # approaching — 3 hours
    if days_until < 180:
        return 24 * 3600      # mid-range — 1 day
    return 24 * 3600          # far future — 1 day


@cached(ttl=_ticket_ttl)
def search_tickets(
    gp_name: str,
    year: int = 2026,
    pref: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """Search for F1 ticket options for a given Grand Prix.

    Args:
        gp_name: e.g. "Italian GP", "Monaco GP"
        year: Season year
        pref: Stand preference hint ("ga" | "mid" | "vip" | None)
        max_price: Maximum per-ticket price in EUR. None = no limit.

    Returns:
        List of dicts matching the TicketOption shape:
        [{"name": str, "price": float, "currency": str,
          "section": str, "tag": str, "link": str}]

    Raises:
        Exception on failure — caller should fall back to mock.
    """
    # ── Strategy 1: Firecrawl (scrape official ticket page) ──────
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")
    if firecrawl_key:
        try:
            result = _try_firecrawl(gp_name, year, firecrawl_key)
            if result:
                logger.info("search_tickets: Firecrawl returned %d options", len(result))
                return result
        except Exception:
            logger.exception("search_tickets: Firecrawl failed, trying DuckDuckGo")

    # ── Strategy 2: DuckDuckGo search snippets ───────────────────
    try:
        result = _try_duckduckgo(gp_name, year)
        if result:
            logger.info("search_tickets: DuckDuckGo returned %d options", len(result))
            return result
    except Exception:
        logger.exception("search_tickets: DuckDuckGo also failed")

    # ── All strategies exhausted ─────────────────────────────────
    raise RuntimeError(
        f"No ticket data source available for {gp_name} {year}"
    )


def _try_firecrawl(gp_name: str, year: int, api_key: str) -> list[dict]:
    """Scrape the GP's official ticket page via Firecrawl and extract
    structured data with the LLM.

    TODO (Phase 3.3): implement once Firecrawl key is ready.
    """
    # from firecrawl import FirecrawlApp
    # app = FirecrawlApp(api_key=api_key)
    # url = _official_ticket_url(gp_name)  # map GP name → official URL
    # page = app.scrape_url(url, params={"formats": ["markdown"]})
    # markdown = page.get("markdown", "")
    #
    # Then call LLM with:
    #   "Extract ticket options from this page: {markdown}"
    #   with_structured_output(list[TicketOption])
    return []  # empty → triggers DuckDuckGo fallback


def _try_duckduckgo(gp_name: str, year: int) -> list[dict]:
    """Search DuckDuckGo for ticket info and let LLM extract from snippets.

    TODO (Phase 3.3): implement with langchain-community DuckDuckGoSearchRun.
    """
    # from langchain_community.tools import DuckDuckGoSearchRun
    # search = DuckDuckGoSearchRun()
    # snippets = search.run(f"{gp_name} {year} official tickets grandstand prices")
    #
    # Then call LLM with:
    #   "Based on these search results, extract 3 ticket options: {snippets}"
    #   with_structured_output(list[TicketOption])
    return []  # empty → triggers raise in search_tickets
