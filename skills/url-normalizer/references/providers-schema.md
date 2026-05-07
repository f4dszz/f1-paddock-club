# Providers config schema

Callers of `normalize(url, provider, providers_config)` supply a dict
whose keys are provider names (free-form strings the caller picks) and
whose values follow this schema.

## Per-provider entry

| Key                | Type            | Required | Meaning                                           |
|--------------------|-----------------|----------|---------------------------------------------------|
| `homepage`         | `str`           | yes      | Absolute URL used as fallback when classification fails or input is empty. |
| `hosts`            | `list[str]`     | yes      | Allowed hostnames. Subdomains match (`m.booking.com` matches `booking.com`). |
| `deeplink_patterns`| `list[str]`     | no       | Python regexes matched against the URL path. First-hit-wins, checked before search. |
| `search_patterns`  | `list[str]`     | no       | Same shape as deeplink, evaluated only if no deeplink hit. |
| `essential_params` | `list[str]`     | no       | Query-param names that must survive tracking strip even if globally blocked. Compared case-insensitively. |

Missing optional keys default to empty lists. The whole entry is read defensively — a malformed
regex is logged and skipped rather than raising.

## Worked example

```python
PROVIDERS_CONFIG = {
    "booking_com": {
        "homepage": "https://www.booking.com/",
        "hosts": ["booking.com"],
        "deeplink_patterns": [r"^/hotel/"],            # /hotel/it/foo.html
        "search_patterns":   [r"^/searchresults"],     # /searchresults.html?...
        "essential_params":  ["aid", "label", "checkin", "checkout"],
    },
    "google_flights": {
        "homepage": "https://www.google.com/travel/flights",
        "hosts": ["google.com"],
        "deeplink_patterns": [r"^/travel/flights/booked"],
        "search_patterns":   [r"^/travel/flights"],    # bare /travel/flights is a search
        "essential_params":  ["tfs", "hl", "curr"],
    },
    "f1_official": {
        "homepage": "https://tickets.formula1.com/en",
        "hosts": ["formula1.com", "tickets.formula1.com"],
        "deeplink_patterns": [r"^/en/racing/\d{4}/"],
        "search_patterns":   [r"^/en/tickets"],
        "essential_params":  [],
    },
}

TRACKING_BLOCKLIST = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_eid", "_ga",
}
```

## Classification semantics

For each `(host, path)`:

1. If `host` (or any subdomain) is not in the provider's `hosts`, the
   result is `homepage` and the caller's URL is replaced with the
   configured homepage.
2. Otherwise the path is checked against `deeplink_patterns` first
   (most specific). First match -> `link_type="deeplink"`.
3. If no deeplink match, check `search_patterns`. First match ->
   `link_type="search"`.
4. If nothing matches:
   - Path is `""` or `"/"` -> `homepage`.
   - Anything else -> `search` (conservative: there is *something*, but
     we cannot promise it books).

Confidence flows mechanically from `link_type`:

| link_type  | confidence |
|------------|------------|
| deeplink   | high       |
| search     | medium     |
| homepage   | low        |

## Querystring cleaning

A param is dropped iff it is in the global tracking blocklist AND not
in the provider's `essential_params`. Unknown params (in neither list)
are preserved. Comparison is case-insensitive on the key.

## What this schema doesn't do

- No URL synthesis. The skill cleans existing URLs; it doesn't build
  new ones from search criteria.
- No host validation against DNS / liveness. Pattern match only.
- No project-specific knowledge in the schema itself — provider names
  are caller-defined strings, not enums.
