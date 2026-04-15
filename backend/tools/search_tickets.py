"""Search for F1 ticket options via Firecrawl + SerpAPI + LLM estimation.

Data flow:
    1. Parallel: Firecrawl (scrape official page) + SerpAPI Google Search
    2. If results → LLM extracts structured TicketOption[] from combined text
    3. If parallel fails → LLM estimation from training data
    4. If LLM fails → raise (agent falls back to mock)

WHY is tickets different from flights/hotels?
Flights and hotels have structured SerpAPI engines (google_flights,
google_hotels) that return machine-readable data. Tickets DON'T —
there's no "google_tickets" engine. So our strategy is:
    - Firecrawl: scrape the official ticket page → get raw markdown
    - SerpAPI Google Search: search for ticket info → get snippets
    - Feed BOTH into the LLM as context → extract structured data

This is a "retrieve then extract" pattern (light RAG without a vector DB).

TTL: Dynamic based on distance-to-race (see _ticket_ttl).
"""

from __future__ import annotations
import logging
import os
from datetime import date
from pydantic import BaseModel, Field

from ._cache import cached
from ._parallel import query_parallel

logger = logging.getLogger(__name__)


# ── Race date lookup (for dynamic TTL, NOT user-facing data) ─────────

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

# ── Known official ticket URLs per GP ────────────────────────────────

_TICKET_URLS: dict[str, str] = {
    "Italian GP": "https://www.monzanet.it/en/f1-grand-prix/",
    "British GP": "https://www.silverstone.co.uk/events/formula-1-british-grand-prix",
    "Monaco GP": "https://www.formula1.com/en/racing/2026/monaco/tickets",
    "Singapore GP": "https://www.singaporegp.sg/en/tickets",
    "United States GP": "https://www.formula1.com/en/racing/2026/united-states/tickets",
    "Las Vegas GP": "https://www.formula1.com/en/racing/2026/las-vegas/tickets",
}
# Default fallback URL for GPs not in the map
_DEFAULT_TICKET_URL = "https://tickets.formula1.com/en"


def _ticket_ttl(gp_name: str, year: int = 2026, **kwargs) -> int:
    """Dynamic TTL: closer to race = shorter cache."""
    date_str = _RACE_DATES_2026.get(gp_name)
    if not date_str:
        return 12 * 3600
    try:
        race_date = date.fromisoformat(date_str)
    except ValueError:
        return 12 * 3600

    days_until = (race_date - date.today()).days
    if days_until < 0:    return 24 * 3600
    if days_until < 14:   return 3 * 3600
    if days_until < 60:   return 3 * 3600
    if days_until < 180:  return 24 * 3600
    return 24 * 3600


# ── Pydantic schema for LLM extraction ──────────────────────────────

class TicketOptionList(BaseModel):
    """WHY a schema for extraction, not just asking for JSON?
    with_structured_output guarantees the LLM returns exactly this
    shape — no missing fields, no wrong types. Without it, the LLM
    might return {"tickets": [...]} one time and [{"name": ...}] the
    next. The schema is the contract.
    """
    options: list[dict] = Field(
        description=(
            "List of 3 ticket options. Each dict: "
            "name (grandstand name), price (float in EUR), currency ('EUR'), "
            "section (where in circuit), tag (VALUE/PICK/VIP), "
            "link (official booking URL)."
        )
    )


# ── Firecrawl source: scrape official ticket page ────────────────────

def _try_firecrawl(gp_name: str, year: int, api_key: str) -> list[str]:
    """Scrape the official ticket page and return raw markdown text.

    WHY return raw text instead of structured data?
    Because the HTML structure is different for every GP's website.
    Rather than writing 24 different parsers, we let the LLM handle
    extraction from markdown. Firecrawl does the hard part (JS render,
    anti-bot) and gives us clean text.

    Returns list of markdown strings (one per page scraped).
    """
    from firecrawl import FirecrawlApp

    app = FirecrawlApp(api_key=api_key)
    url = _TICKET_URLS.get(gp_name, _DEFAULT_TICKET_URL)

    logger.info("Firecrawl: scraping %s for %s", url, gp_name)
    # Firecrawl v2 SDK returns a Document Pydantic model, not a dict.
    # Access .markdown attribute, not .get("markdown").
    result = app.scrape(url, formats=["markdown"])

    markdown = result.markdown if hasattr(result, "markdown") else ""
    if not markdown:
        return []

    return [markdown[:8000]]  # Cap length to fit in LLM context


# ── SerpAPI Google Search: ticket pricing snippets ───────────────────

def _try_serpapi_google_tickets(gp_name: str, year: int, api_key: str) -> list[str]:
    """Google Search via SerpAPI for F1 ticket pricing snippets.
    Returns richer snippets than other engines for F1 ticket queries:
    price ranges, grandstand names, official links.
    """
    from serpapi import GoogleSearch

    # WHY "formula 1" prefix + "tribune" + "EUR"?
    # - "formula 1" disambiguates from other events at same venue
    # - "tribune" / "grandstand" are the terms ticket sites actually use
    # - "EUR" biases toward European pricing pages (where most GPs are)
    # - Avoids generic words like "Italian" that trigger cultural content
    params = {
        "engine": "google",
        "q": f"formula 1 {gp_name} {year} tickets tribune grandstand price EUR official buy",
        "api_key": api_key,
    }
    raw = GoogleSearch(params).get_dict()

    snippets = []
    for r in (raw.get("organic_results") or [])[:5]:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        if snippet:
            snippets.append(f"{title}: {snippet} ({link})")

    return snippets


# ── LLM extraction: turn raw text into structured TicketOption[] ─────

def _extract_with_llm(
    gp_name: str, year: int, raw_texts: list[str],
    pref: str | None, max_price: float | None,
    source_label: str,
) -> list[dict]:
    """WHY a separate extraction function?
    Both Firecrawl (markdown) and Google Search (snippets) produce raw text.
    The LLM's job is the same in both cases: read text → output
    structured TicketOption[]. Centralizing this avoids duplicating
    the prompt and schema logic.
    """
    try:
        from llm import get_llm
        llm = get_llm(temperature=0.2, max_tokens=800)
        if llm is None:
            return []
    except Exception:
        return []

    context = "\n\n---\n\n".join(raw_texts)

    prompt = (
        f"Based on the following information about {gp_name} {year} tickets:\n\n"
        f"{context}\n\n"
        f"Extract exactly 3 grandstand/ticket options: one VALUE (cheapest), "
        f"one PICK (recommended mid-range), one VIP (premium). "
        f"Use real grandstand names from the text if available. "
        f"Prices in EUR. Include the official booking URL from the text."
        f"{f' Preference: {pref}.' if pref else ''}"
        f"{f' Max price: EUR {max_price}.' if max_price else ''}"
    )

    # WHY two extraction strategies?
    # with_structured_output uses OpenAI's function calling / JSON mode,
    # which requires the API to return a 'parsed' field. Some proxies
    # (like duckcoding) don't relay this. Fallback: ask LLM for raw JSON
    # text and parse it ourselves. Less reliable but works with any provider.
    try:
        structured = llm.with_structured_output(TicketOptionList)
        result = structured.invoke([
            ("system", "You are an F1 ticket data extraction expert. Extract structured ticket info from the provided text."),
            ("user", prompt),
        ])
        options = result.options if result.options else []
    except Exception:
        logger.warning("structured_output failed, trying raw JSON fallback")
        try:
            raw_response = llm.invoke([
                ("system", "You are an F1 ticket data extraction expert. Return ONLY valid JSON, no other text."),
                ("user", prompt + "\n\nReturn JSON: {\"options\": [{\"name\": str, \"price\": float, \"currency\": \"EUR\", \"section\": str, \"tag\": \"VALUE\"|\"PICK\"|\"VIP\", \"link\": str}]}"),
            ])
            import json as _json
            text = raw_response.content.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = _json.loads(text)
            options = parsed.get("options", parsed) if isinstance(parsed, dict) else parsed
            if isinstance(options, list):
                pass  # good
            else:
                options = []
        except Exception:
            logger.exception("LLM ticket extraction failed (both methods)")
            return []

    for opt in options:
        if isinstance(opt, dict):
            opt["_source"] = source_label
            opt["_degraded"] = False  # Real data, just LLM-extracted
    return [o for o in options if isinstance(o, dict)]


# ── LLM estimation (no real data, pure training knowledge) ───────────

def _try_llm_estimate(
    gp_name: str, year: int,
    pref: str | None, max_price: float | None,
) -> list[dict]:
    try:
        from llm import get_llm
        llm = get_llm(temperature=0.3, max_tokens=800)
        if llm is None:
            return []
    except Exception:
        return []

    prompt = (
        f"Estimate 3 realistic ticket options for the {gp_name} {year}. "
        f"Use real grandstand names for that circuit. Prices in EUR. "
        f"One VALUE (cheapest/GA), one PICK (mid-range), one VIP (premium). "
        f"Include the most likely official booking URL."
        f"{f' Preference: {pref}.' if pref else ''}"
        f"{f' Max price: EUR {max_price}.' if max_price else ''}"
    )

    try:
        structured = llm.with_structured_output(TicketOptionList)
        result = structured.invoke([
            ("system", "You are an F1 ticket pricing expert. Return realistic estimates."),
            ("user", prompt),
        ])
        options = result.options if result.options else []
    except Exception:
        logger.warning("structured_output failed for ticket estimate, trying raw JSON")
        try:
            raw_response = llm.invoke([
                ("system", "You are an F1 ticket pricing expert. Return ONLY valid JSON, no other text."),
                ("user", prompt + "\n\nReturn JSON: {\"options\": [{\"name\": str, \"price\": float, \"currency\": \"EUR\", \"section\": str, \"tag\": \"VALUE\"|\"PICK\"|\"VIP\", \"link\": str}]}"),
            ])
            import json as _json
            text = raw_response.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = _json.loads(text)
            options = parsed.get("options", parsed) if isinstance(parsed, dict) else parsed
            if not isinstance(options, list):
                options = []
        except Exception:
            logger.exception("LLM ticket estimation failed (both methods)")
            return []

    for opt in options:
        if isinstance(opt, dict):
            opt["_source"] = "llm_estimate"
            opt["_degraded"] = True
    return [o for o in options if isinstance(o, dict)]


# ── Main entry point ─────────────────────────────────────────────────

@cached(ttl=_ticket_ttl)
def search_tickets(
    gp_name: str,
    year: int = 2026,
    pref: str | None = None,
    max_price: float | None = None,
) -> tuple[list[dict], str]:
    """Search for F1 ticket options. Returns (results, degradation_summary).

    WHY is the flow different from flights/hotels?
    Flights/hotels have structured API engines that return machine data.
    Tickets require a TWO-STEP process:
      Step 1: Gather raw text (Firecrawl scrape + Google Search, parallel)
      Step 2: LLM extracts structured TicketOption[] from that text
    This is essentially "light RAG" — retrieve text, then generate
    structured output from it — without needing a vector database.
    """
    api_key = os.environ.get("SERPAPI_API_KEY")
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")

    # ── Layer 1: Parallel text gathering ─────────────────────────
    # WHY gather text first, then extract?
    # Because Firecrawl returns markdown and Google Search returns snippets.
    # Both are raw text. We merge them into one context and let
    # ONE LLM call extract from the combined picture — this gives
    # better results than extracting from each source separately.

    raw_texts: list[str] = []
    sources_used: list[str] = []
    sources_failed: list[str] = []

    if firecrawl_key or api_key:
        text_sources = {}
        if firecrawl_key:
            text_sources["firecrawl"] = lambda: _try_firecrawl(gp_name, year, firecrawl_key)
        if api_key:
            text_sources["google_search"] = lambda: _try_serpapi_google_tickets(gp_name, year, api_key)

        text_results, report = query_parallel(text_sources, timeout=25)

        # text_results is list[str] (markdown chunks and snippet strings)
        for item in text_results:
            if isinstance(item, str):
                raw_texts.append(item)
            elif isinstance(item, dict):
                # Shouldn't happen but handle gracefully
                raw_texts.append(str(item))

        sources_used = report.succeeded
        sources_failed = report.failed

    # ── Layer 1b: LLM extraction from gathered text ──────────────
    if raw_texts:
        source_label = "+".join(sources_used)
        extracted = _extract_with_llm(gp_name, year, raw_texts, pref, max_price, source_label)
        if extracted:
            degradation_msg = ""
            if sources_failed:
                degradation_msg = f" (partial: {', '.join(sources_failed)} failed)"
            return extracted, f"sources: {source_label}{degradation_msg}"

        logger.warning("search_tickets: LLM extraction from real data returned nothing")

    # ── Layer 2: LLM estimation (training data only) ─────────────
    logger.info("search_tickets: trying LLM estimation fallback")
    estimated = _try_llm_estimate(gp_name, year, pref, max_price)
    if estimated:
        return estimated, "source: llm_estimate (real ticket data unavailable)"

    # ── Layer 3: Everything failed ───────────────────────────────
    raise RuntimeError(f"All ticket data sources exhausted for {gp_name} {year}")
