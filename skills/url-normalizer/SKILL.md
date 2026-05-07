---
name: url-normalizer
description: Normalize provider booking URLs and affiliate / search-page deep-links into a clean, classified link record. Make sure to use this skill whenever the user mentions normalizing booking URLs, cleaning tracking parameters (UTM / fbclid / gclid / mc_*), classifying provider deep-links vs. search pages vs. homepages, or sanitizing affiliate links in any travel, hotel, flight, ticket, or general affiliate-link context. Trigger on phrases like "normalize this booking link", "strip tracking from these URLs", "is this a real deeplink or just a search page", "fall back to the provider homepage", or any cleanup of third-party booking redirects.
---

# URL Normalizer Skill

Travel and affiliate workflows produce messy URLs: SerpAPI redirect wrappers,
Booking.com listing URLs with 30+ tracking params, Google Flights "search"
links that look like deeplinks but aren't, and outright empty strings from
LLM fallbacks. Downstream UIs (Book buttons, PDFs, ICS exports) need a
single shape they can render without lying to the user.

This skill is the abstract layer. It is provider-agnostic. Callers supply a
`providers_config` dict that pins the project's provider set; the skill does
the parsing, classification, and tracking-param removal.

## When to trigger

Use this skill when the task involves:

- Cleaning third-party booking, hotel, flight, ticket, or affiliate URLs.
- Deciding whether a URL is a real deep-link, a search page, or a homepage.
- Stripping tracking parameters (UTM family, fbclid, gclid, mc_eid, etc.)
  while preserving an explicit allow-list of essential params (affiliate
  IDs, session tokens, search-result anchors).
- Falling back to a provider homepage when a URL is missing or malformed.

It is the wrong tool when:

- You need HTTP HEAD validation / link liveness probing (this skill is
  pure URL parsing — no network).
- You need to *generate* deep-links from search parameters (this skill
  only classifies and cleans an input URL).

## Public API

```python
from normalize import normalize, NormalizedLink

result: NormalizedLink = normalize(
    url="https://www.booking.com/hotel/it/foo.html?utm_source=x&aid=12345",
    provider="booking_com",
    providers_config=PROVIDERS_CONFIG,
)
# {"url": "https://www.booking.com/hotel/it/foo.html?aid=12345",
#  "link_type": "deeplink",
#  "confidence": "high"}
```

`NormalizedLink` is a `TypedDict` with three keys:

| Key          | Type                                       | Meaning                              |
|--------------|--------------------------------------------|--------------------------------------|
| `url`        | `str`                                      | The cleaned URL (or homepage fallback). |
| `link_type`  | `Literal["deeplink", "search", "homepage"]` | What the URL actually points at.    |
| `confidence` | `Literal["high", "medium", "low"]`         | How sure we are it'll book.          |

## Algorithm

1. **Parse** with `urllib.parse.urlparse`. Empty input or unparseable hosts
   short-circuit to homepage fallback (`link_type="homepage"`,
   `confidence="low"`).
2. **Classify** by matching `(host, path)` against the provider's
   `deeplink_patterns` and `search_patterns` from the config. First hit
   wins; deeplink patterns are checked first.
3. **Strip** query params not in the provider's `essential_params`
   allow-list AND in the global `tracking_blocklist`. Anything not on
   either list is preserved (be conservative — do not delete unknown
   params, only known-bad ones).
4. **Confidence** is set as a function of `link_type`:
   - `deeplink` -> `high`
   - `search` -> `medium`
   - `homepage` -> `low`
   - Provider not in config -> `low` regardless of pattern match.

## Configuration shape

Callers pass a dict keyed by provider name. See
`references/providers-schema.md` for the full schema. Minimal example:

```python
PROVIDERS_CONFIG = {
    "booking_com": {
        "homepage": "https://www.booking.com/",
        "hosts": ["booking.com", "www.booking.com"],
        "deeplink_patterns": [r"^/hotel/"],
        "search_patterns": [r"^/searchresults"],
        "essential_params": ["aid", "label", "checkin", "checkout"],
    },
    # ...
}

TRACKING_BLOCKLIST = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_eid", "mc_cid", "_ga",
}
```

## Configuring for a project

1. Enumerate every provider whose URLs your app emits.
2. For each, fill `homepage`, `hosts`, `deeplink_patterns`, `search_patterns`,
   and `essential_params`.
3. Pass `providers_config` and `tracking_blocklist` into `normalize()`.
4. Wrap in a thin project module that hardcodes the config so callers
   only pass `(url, provider)`.

## Reference impl

`scripts/normalize.py` is a pure-stdlib reference implementation. It has
zero project-specific knowledge — vendor it or import it from your
project module. `scripts/test_normalize.py` exercises the contract with
representative configs.

## Failure modes

- **Unknown provider name** -> returns `{url: original, link_type:"homepage", confidence:"low"}`
  rather than raising. The caller can decide whether to log.
- **Malformed URL** -> homepage fallback (uses the provider's homepage if
  known; empty string if not).
- **Provider config missing keys** -> treated as empty lists / sets.
  Defensive defaults; never raises.

## Non-goals

- No network calls. This is a pure-function module.
- No HTML parsing. URLs only.
- No URL *construction* from structured data — the skill cleans and
  classifies an input URL; it does not synthesize one.
