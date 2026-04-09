"""General-purpose web search via Tavily or DuckDuckGo.

Used by tour_agent for attraction lookups, and by the future
refinement agent for open-ended user questions.

TTL: 1 day — general info doesn't change by the hour.

Usage:
    from tools.search_web import search_web
    snippets = search_web("best vegetarian restaurants Monza")
"""

from __future__ import annotations
import logging
import os

from ._cache import cached

logger = logging.getLogger(__name__)

_TTL = 24 * 3600  # 1 day


@cached(ttl=_TTL)
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web and return concatenated result snippets.

    Tries Tavily first (higher quality, LLM-optimized snippets),
    falls back to DuckDuckGo (free, no key needed).

    Args:
        query: Natural language search query.
        max_results: Max number of results to return.

    Returns:
        A single string with one result per block:
          "- Title\\n  Snippet text\\n  (https://...)\\n\\n..."
        Suitable for injecting into an LLM prompt as context.

    Raises:
        RuntimeError: if all search providers fail.
    """
    # ── Strategy 1: Tavily (if configured) ───────────────────────
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        try:
            return _try_tavily(query, max_results, tavily_key)
        except Exception:
            logger.exception("search_web: Tavily failed, trying DuckDuckGo")

    # ── Strategy 2: DuckDuckGo (free, no key) ────────────────────
    try:
        return _try_duckduckgo(query, max_results)
    except Exception:
        logger.exception("search_web: DuckDuckGo also failed")

    raise RuntimeError(f"All search providers failed for query: {query}")


def _try_tavily(query: str, max_results: int, api_key: str) -> str:
    """TODO (Phase 3.2+): wire Tavily."""
    # from langchain_tavily import TavilySearch
    # tool = TavilySearch(max_results=max_results, api_key=api_key)
    # results = tool.invoke(query)
    # return _format_results(results)
    return ""


def _try_duckduckgo(query: str, max_results: int) -> str:
    """TODO (Phase 3.2+): wire DuckDuckGo."""
    # from langchain_community.tools import DuckDuckGoSearchRun
    # search = DuckDuckGoSearchRun()
    # return search.run(query)
    return ""


def _format_results(results: list[dict]) -> str:
    """Format Tavily-style results into a prompt-friendly string."""
    blocks = []
    for r in results:
        title = r.get("title", "")
        snippet = r.get("content", r.get("snippet", ""))
        url = r.get("url", "")
        blocks.append(f"- {title}\n  {snippet}\n  ({url})")
    return "\n\n".join(blocks)
