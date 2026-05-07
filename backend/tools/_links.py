"""Project-specific booking-link normalization for f1-paddock-club.

This module wraps the abstract URL normalizer (`skills/url-normalizer/`)
with the F1 Paddock Club provider configuration. Three things live here:

1. PROVIDER_HOMEPAGES - the canonical homepage per provider key.
2. PROJECT_PROVIDERS_CONFIG - the per-provider classification rules
   (hosts, deeplink/search regexes, essential affiliate params).
3. TRACKING_PARAM_BLOCKLIST - the global drop list (UTM family, fbclid,
   gclid, etc.) used for every provider.

Public API:
    normalize_link(url, provider) -> dict with keys
        url, link_type, booking_confidence

`booking_confidence` (not `confidence`) matches the field name used by
TicketOption / TransportLeg / HotelOption in `backend/state.py`. This
module is the single point where state-shape-specific keys are produced.

Vendor strategy:
    The normalize() reference impl is vendored below (Option A). It is a
    direct copy of `skills/url-normalizer/scripts/normalize.py` and must
    be kept in sync with that file. We chose vendoring over path-import
    because:
      - No fragile sys.path tricks at import time.
      - Backend tests don't need to know skill folder layout.
      - The abstract impl is small (<200 lines) and changes rarely.
    If the abstract impl gains material complexity, switch to path-
    import or convert the skill into an installed package.

Vendored from skills/url-normalizer/scripts/normalize.py - keep in sync.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Literal, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


# ── Vendored abstract reference impl ───────────────────────────────

LinkType = Literal["deeplink", "search", "homepage"]
Confidence = Literal["high", "medium", "low"]


class _NormalizedLink(TypedDict):
    url: str
    link_type: LinkType
    confidence: Confidence


_DEFAULT_TRACKING_BLOCKLIST: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "mc_eid", "mc_cid",
    "_ga", "_gl",
    "ref", "ref_src", "ref_url",
    "share", "share_id",
})


def _provider_config(providers_config: dict, provider: str) -> dict | None:
    if not isinstance(providers_config, dict):
        return None
    cfg = providers_config.get(provider)
    if not isinstance(cfg, dict):
        return None
    return cfg


def _homepage_fallback(
    provider: str, providers_config: dict, original_url: str = ""
) -> _NormalizedLink:
    cfg = _provider_config(providers_config, provider) or {}
    homepage = cfg.get("homepage", "") or original_url or ""
    return {"url": homepage, "link_type": "homepage", "confidence": "low"}


def _matches_any(patterns: Iterable[str], path: str) -> bool:
    for pat in patterns or ():
        try:
            if re.search(pat, path):
                return True
        except re.error:
            continue
    return False


def _host_matches(host: str, allowed_hosts: Iterable[str]) -> bool:
    if not host:
        return False
    host = host.lower()
    for h in allowed_hosts or ():
        h = h.lower()
        if host == h or host.endswith("." + h):
            return True
    return False


def _classify(parsed_url, cfg: dict) -> LinkType:
    host = parsed_url.netloc.lower()
    path = parsed_url.path or "/"

    if not _host_matches(host, cfg.get("hosts", [])):
        return "homepage"
    if _matches_any(cfg.get("deeplink_patterns", []), path):
        return "deeplink"
    if _matches_any(cfg.get("search_patterns", []), path):
        return "search"
    if path in ("", "/"):
        return "homepage"
    return "search"


def _strip_params(
    parsed_url,
    essential_params: Iterable[str],
    tracking_blocklist: Iterable[str],
) -> str:
    if not parsed_url.query:
        return ""
    essential = {p.lower() for p in essential_params or ()}
    blocked = {p.lower() for p in tracking_blocklist or ()}
    kept: list[tuple[str, str]] = []
    for key, val in parse_qsl(parsed_url.query, keep_blank_values=True):
        k_lower = key.lower()
        if k_lower in essential:
            kept.append((key, val))
            continue
        if k_lower in blocked:
            continue
        kept.append((key, val))
    return urlencode(kept, doseq=True)


def _normalize_abstract(
    url: str,
    provider: str,
    providers_config: dict,
    tracking_blocklist: Iterable[str] | None = None,
) -> _NormalizedLink:
    """Vendored reference impl. See skills/url-normalizer/scripts/normalize.py."""
    if tracking_blocklist is None:
        tracking_blocklist = _DEFAULT_TRACKING_BLOCKLIST

    cfg = _provider_config(providers_config, provider)

    if not url or not isinstance(url, str):
        return _homepage_fallback(provider, providers_config)

    if cfg is None:
        return {"url": url, "link_type": "homepage", "confidence": "low"}

    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return _homepage_fallback(provider, providers_config, original_url=url)

    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        return _homepage_fallback(provider, providers_config, original_url=url)
    if not parsed.netloc:
        return _homepage_fallback(provider, providers_config, original_url=url)

    link_type = _classify(parsed, cfg)

    if link_type == "homepage" and not _host_matches(
        parsed.netloc, cfg.get("hosts", [])
    ):
        return _homepage_fallback(provider, providers_config, original_url=url)

    cleaned_query = _strip_params(
        parsed,
        essential_params=cfg.get("essential_params", []),
        tracking_blocklist=tracking_blocklist,
    )

    rebuilt = urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, cleaned_query, "",
    ))

    if link_type == "deeplink":
        confidence: Confidence = "high"
    elif link_type == "search":
        confidence = "medium"
    else:
        confidence = "low"

    return {"url": rebuilt, "link_type": link_type, "confidence": confidence}


# ── Project config ─────────────────────────────────────────────────

# Provider name -> homepage URL. Used by callers and as fallback target.
PROVIDER_HOMEPAGES: dict[str, str] = {
    "booking_com":   "https://www.booking.com/",
    "google_flights":"https://www.google.com/travel/flights",
    "google_hotels": "https://www.google.com/travel/hotels",
    "google_maps":   "https://www.google.com/maps",
    "google_search": "https://www.google.com/",
    "f1_official":   "https://tickets.formula1.com/en",
    "monzanet":      "https://www.monzanet.it/en/",
    "silverstone":   "https://www.silverstone.co.uk/",
    "singaporegp":   "https://www.singaporegp.sg/en",
}


# Global tracking blocklist. Affiliate / search-result IDs ARE NOT in
# this list — they go in each provider's `essential_params` so they
# survive cleaning even if the param name overlaps.
TRACKING_PARAM_BLOCKLIST: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "mc_eid", "mc_cid",
    "_ga", "_gl",
    # Note: 'ref' / 'share' commonly appear in tracking, but Booking.com
    # also uses 'aid' / 'label' as affiliate keys — those are explicitly
    # protected via essential_params below.
    "share_id",
})


# Per-provider classification rules. Keep `essential_params` tight —
# every entry is a promise the param is necessary for booking.
PROJECT_PROVIDERS_CONFIG: dict[str, dict] = {
    "booking_com": {
        "homepage": PROVIDER_HOMEPAGES["booking_com"],
        "hosts": ["booking.com"],
        "deeplink_patterns": [r"^/hotel/"],
        "search_patterns":   [r"^/searchresults"],
        "essential_params":  ["aid", "label", "checkin", "checkout",
                              "no_rooms", "group_adults", "sid"],
    },
    "google_flights": {
        "homepage": PROVIDER_HOMEPAGES["google_flights"],
        "hosts": ["google.com"],
        # Real flight booking deeplinks live under /travel/flights/booked.
        # Bare /travel/flights is a search results page — even with tfs
        # set, it's a search, not a confirmed itinerary.
        "deeplink_patterns": [r"^/travel/flights/booked"],
        "search_patterns":   [r"^/travel/flights"],
        # tfs encodes the search; hl/curr are display preferences.
        "essential_params":  ["tfs", "hl", "curr", "f", "t", "d"],
    },
    "google_hotels": {
        "homepage": PROVIDER_HOMEPAGES["google_hotels"],
        "hosts": ["google.com"],
        "deeplink_patterns": [r"^/travel/hotels/entity"],
        "search_patterns":   [r"^/travel/hotels"],
        "essential_params":  ["q", "checkin", "checkout", "rooms",
                              "hl", "curr"],
    },
    "google_maps": {
        "homepage": PROVIDER_HOMEPAGES["google_maps"],
        "hosts": ["google.com", "maps.google.com"],
        "deeplink_patterns": [r"^/maps/place/"],
        "search_patterns":   [r"^/maps/search", r"^/maps"],
        "essential_params":  ["q", "ll", "z"],
    },
    "google_search": {
        "homepage": PROVIDER_HOMEPAGES["google_search"],
        "hosts": ["google.com"],
        "deeplink_patterns": [],
        "search_patterns":   [r"^/search"],
        "essential_params":  ["q", "hl"],
    },
    "f1_official": {
        "homepage": PROVIDER_HOMEPAGES["f1_official"],
        "hosts": ["formula1.com", "tickets.formula1.com"],
        "deeplink_patterns": [r"^/en/racing/\d{4}/"],
        "search_patterns":   [r"^/en/tickets", r"^/en"],
        "essential_params":  [],
    },
    "monzanet": {
        "homepage": PROVIDER_HOMEPAGES["monzanet"],
        "hosts": ["monzanet.it"],
        "deeplink_patterns": [r"^/en/f1-grand-prix"],
        "search_patterns":   [],
        "essential_params":  [],
    },
    "silverstone": {
        "homepage": PROVIDER_HOMEPAGES["silverstone"],
        "hosts": ["silverstone.co.uk"],
        "deeplink_patterns": [r"^/events/formula-1"],
        "search_patterns":   [r"^/events"],
        "essential_params":  [],
    },
    "singaporegp": {
        "homepage": PROVIDER_HOMEPAGES["singaporegp"],
        "hosts": ["singaporegp.sg"],
        "deeplink_patterns": [r"^/en/tickets"],
        "search_patterns":   [r"^/en"],
        "essential_params":  [],
    },
}


# ── Public API ─────────────────────────────────────────────────────

def normalize_link(url: str, provider: str) -> dict:
    """Normalize a booking URL for one of the F1 Paddock Club providers.

    Returns a dict with the project-canonical field names:
        {
          "url": str,
          "link_type": "deeplink" | "search" | "homepage",
          "booking_confidence": "high" | "medium" | "low",
        }

    Never raises. Unknown provider names log a debug message and return
    the URL untouched with low confidence.
    """
    if provider not in PROJECT_PROVIDERS_CONFIG:
        logger.debug("normalize_link: unknown provider %r", provider)

    raw = _normalize_abstract(
        url=url,
        provider=provider,
        providers_config=PROJECT_PROVIDERS_CONFIG,
        tracking_blocklist=TRACKING_PARAM_BLOCKLIST,
    )
    return {
        "url": raw["url"],
        "link_type": raw["link_type"],
        "booking_confidence": raw["confidence"],
    }


def fallback_for(provider: str) -> str:
    """Return the configured homepage URL for `provider`, or empty string."""
    return PROVIDER_HOMEPAGES.get(provider, "")


__all__ = [
    "PROVIDER_HOMEPAGES",
    "TRACKING_PARAM_BLOCKLIST",
    "PROJECT_PROVIDERS_CONFIG",
    "normalize_link",
    "fallback_for",
]
