"""URL normalizer — abstract reference implementation.

Pure-stdlib, provider-agnostic. Vendored or imported by project modules
that supply their own `providers_config` dict (see references/providers-schema.md).

Public API:
    normalize(url, provider, providers_config) -> NormalizedLink

Where NormalizedLink is a 3-key dict:
    {"url": str, "link_type": "deeplink"|"search"|"homepage",
     "confidence": "high"|"medium"|"low"}

Design constraints:
- No project-specific imports.
- No hardcoded provider names, hosts, or patterns.
- No network I/O. Pure URL parsing.
- Never raises on malformed input — returns a homepage fallback instead.
"""

from __future__ import annotations

import re
from typing import Iterable, Literal, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


LinkType = Literal["deeplink", "search", "homepage"]
Confidence = Literal["high", "medium", "low"]


class NormalizedLink(TypedDict):
    url: str
    link_type: LinkType
    confidence: Confidence


# Default global tracking-param blocklist used when the caller does not
# supply one. Conservative — only obvious analytics noise.
DEFAULT_TRACKING_BLOCKLIST: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "mc_eid", "mc_cid",
    "_ga", "_gl",
    "ref", "ref_src", "ref_url",
    "share", "share_id",
})


def _provider_config(
    providers_config: dict, provider: str
) -> dict | None:
    """Return the config dict for `provider`, or None if unknown."""
    if not isinstance(providers_config, dict):
        return None
    cfg = providers_config.get(provider)
    if not isinstance(cfg, dict):
        return None
    return cfg


def _homepage_fallback(
    provider: str, providers_config: dict, original_url: str = ""
) -> NormalizedLink:
    """Return a NormalizedLink that points at the provider homepage."""
    cfg = _provider_config(providers_config, provider) or {}
    homepage = cfg.get("homepage", "") or original_url or ""
    return {
        "url": homepage,
        "link_type": "homepage",
        "confidence": "low",
    }


def _matches_any(patterns: Iterable[str], path: str) -> bool:
    """Return True if any compiled regex in `patterns` matches `path`."""
    for pat in patterns or ():
        try:
            if re.search(pat, path):
                return True
        except re.error:
            # Bad pattern in caller config — skip rather than raise.
            continue
    return False


def _host_matches(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Return True if `host` (lowercased) equals or is a subdomain of any
    entry in `allowed_hosts`."""
    if not host:
        return False
    host = host.lower()
    for h in allowed_hosts or ():
        h = h.lower()
        if host == h or host.endswith("." + h):
            return True
    return False


def _classify(
    parsed_url, cfg: dict
) -> LinkType:
    """Decide deeplink / search / homepage from a parsed URL + provider cfg.

    Order: deeplink patterns first (most specific), then search, otherwise
    homepage.
    """
    host = parsed_url.netloc.lower()
    path = parsed_url.path or "/"

    if not _host_matches(host, cfg.get("hosts", [])):
        # Wrong host for this provider — caller passed a mismatched URL.
        # Fall through to homepage.
        return "homepage"

    if _matches_any(cfg.get("deeplink_patterns", []), path):
        return "deeplink"
    if _matches_any(cfg.get("search_patterns", []), path):
        return "search"

    # Bare host or root path with no specific pattern match -> homepage.
    if path in ("", "/"):
        return "homepage"

    # Has a path but no pattern matched. Be conservative: call it search
    # (it's *something*, but we can't promise it books).
    return "search"


def _strip_params(
    parsed_url,
    essential_params: Iterable[str],
    tracking_blocklist: Iterable[str],
) -> str:
    """Return a query string with tracking params removed.

    Rule: a param is dropped iff it is in `tracking_blocklist` AND not in
    `essential_params`. Unknown params are preserved (conservative).
    """
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


def normalize(
    url: str,
    provider: str,
    providers_config: dict,
    tracking_blocklist: Iterable[str] | None = None,
) -> NormalizedLink:
    """Normalize a URL to a 3-key NormalizedLink record.

    Arguments:
        url: The URL to normalize. May be empty or malformed.
        provider: The provider key into `providers_config`.
        providers_config: Caller-supplied provider config dict. See
            references/providers-schema.md for the shape.
        tracking_blocklist: Optional iterable of param names to strip
            globally. Defaults to DEFAULT_TRACKING_BLOCKLIST.

    Returns:
        NormalizedLink dict. Never raises.
    """
    if tracking_blocklist is None:
        tracking_blocklist = DEFAULT_TRACKING_BLOCKLIST

    cfg = _provider_config(providers_config, provider)

    # Empty / non-string input -> homepage fallback.
    if not url or not isinstance(url, str):
        return _homepage_fallback(provider, providers_config)

    # Unknown provider -> always low confidence, link_type homepage.
    if cfg is None:
        return {
            "url": url,
            "link_type": "homepage",
            "confidence": "low",
        }

    # Parse. urlparse never raises on str input but may produce empty pieces.
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return _homepage_fallback(provider, providers_config, original_url=url)

    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        return _homepage_fallback(provider, providers_config, original_url=url)

    if not parsed.netloc:
        return _homepage_fallback(provider, providers_config, original_url=url)

    link_type = _classify(parsed, cfg)

    # If host didn't match the provider, fall back to homepage. Keep the
    # original URL only if there is no provider homepage configured.
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
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        cleaned_query,
        "",  # drop fragment — not useful for booking
    ))

    confidence: Confidence
    if link_type == "deeplink":
        confidence = "high"
    elif link_type == "search":
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "url": rebuilt,
        "link_type": link_type,
        "confidence": confidence,
    }


__all__ = [
    "normalize",
    "NormalizedLink",
    "DEFAULT_TRACKING_BLOCKLIST",
]
