"""Structured trip constraints extracted from form text and chat turns."""

from __future__ import annotations

import re
from typing import Any


_DIRECT_ONLY_RE = re.compile(
    r"\b(only\s+direct|direct\s+only|non[-\s]?stop|no\s+stops?|without\s+stops?)\b"
    r"|直飞|直航|直达|直達|不转机|不要转机|无转机|不中转|不中轉",
    re.IGNORECASE,
)

_DIRECT_CLEAR_RE = re.compile(
    r"\b(connections?\s+(are\s+)?ok|connecting\s+flights?\s+(are\s+)?ok|"
    r"stopovers?\s+(are\s+)?ok|any\s+flight|no\s+need\s+for\s+direct)\b"
    r"|可以转机|可以中转|转机也可以|中转也可以|不用直飞",
    re.IGNORECASE,
)

_BRAND_ALIASES: dict[str, set[str]] = {
    "Marriott": {
        "marriott", "jw marriott", "courtyard", "sheraton", "westin",
        "moxy", "ac hotel", "tribute portfolio", "renaissance",
        "fairfield", "residence inn", "万豪", "萬豪",
    },
    "Hilton": {
        "hilton", "hampton", "doubletree", "curio", "canopy",
        "waldorf", "conrad", "tapestry", "希尔顿", "希爾頓",
    },
    "Hyatt": {"hyatt", "andaz", "thompson", "凯悦", "凱悅"},
    "IHG": {
        "ihg", "holiday inn", "intercontinental", "voco",
        "crowne plaza", "洲际", "洲際", "假日酒店",
    },
}

_BRAND_CLEAR_RE = re.compile(
    r"\b(any\s+brand|brand\s+doesn'?t\s+matter|no\s+brand\s+preference|"
    r"whatever\s+hotel|any\s+hotel)\b"
    r"|任何品牌|品牌不限|不限制品牌|什么酒店都可以",
    re.IGNORECASE,
)

_DIETARY_RE = re.compile(
    r"\b(vegetarian|vegan|halal|kosher|gluten[-\s]?free|dairy[-\s]?free)\b"
    r"|素食|纯素|清真|无麸质|無麩質",
    re.IGNORECASE,
)

_ACCESSIBILITY_RE = re.compile(
    r"\b(wheelchair|accessible|accessibility|step[-\s]?free|mobility)\b"
    r"|轮椅|輪椅|无障碍|無障礙|行动不便|行動不便",
    re.IGNORECASE,
)

# Intent-bearing phrases only. A bare "budget"/"预算" appears in neutral
# questions ("what is my budget?", "increase my budget") and must NOT flip
# avoid_luxury; same reasoning for the next regex.
_AVOID_LUXURY_RE = re.compile(
    r"\b(avoid\s+luxury|no\s+luxury|not\s+luxury|cheaper|cheap|save\s+money"
    r"|budget[-\s]?friendly|low\s+budget|tight\s+budget|on\s+a\s+budget)\b"
    r"|不要奢华|不要奢華|不要豪华|不要豪華|便宜|省钱|省錢|预算有限|省预算|省預算",
    re.IGNORECASE,
)

# "paddock" is the product's own name and "premium" is a neutral F1 ticket
# tier; neither should imply a VIP preference. Keep explicit VIP/luxury intent.
_VIP_RE = re.compile(r"\b(vip|luxury)\b|奢华|奢華|豪华|豪華", re.IGNORECASE)


def empty_constraints() -> dict[str, Any]:
    return {
        "direct_only": False,
        "allowed_hotel_brands": [],
        "dietary": "",
        "accessibility": False,
        "avoid_luxury": False,
        "budget_strategy": "balanced",
    }


def _canonical_brand_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    found: list[str] = []
    for value in values:
        lowered = str(value).strip().lower()
        if not lowered:
            continue
        for canonical, aliases in _BRAND_ALIASES.items():
            if lowered == canonical.lower() or lowered in aliases:
                if canonical not in found:
                    found.append(canonical)
                break
    return found


def normalize_constraints(raw: dict[str, Any] | None) -> dict[str, Any]:
    constraints = empty_constraints()
    if not isinstance(raw, dict):
        return constraints
    constraints.update({k: v for k, v in raw.items() if k in constraints})
    constraints["allowed_hotel_brands"] = _canonical_brand_values(
        constraints.get("allowed_hotel_brands") or []
    )
    constraints["direct_only"] = bool(constraints.get("direct_only"))
    constraints["accessibility"] = bool(constraints.get("accessibility"))
    constraints["avoid_luxury"] = bool(constraints.get("avoid_luxury"))
    if constraints.get("budget_strategy") not in {"balanced", "cheapest", "comfort", "vip"}:
        constraints["budget_strategy"] = "balanced"
    return constraints


def extract_hotel_brands(text: str) -> list[str]:
    lowered = (text or "").lower()
    found: list[str] = []
    for canonical, aliases in _BRAND_ALIASES.items():
        if canonical.lower() in lowered or any(alias in lowered for alias in aliases):
            found.append(canonical)
    return found


def merge_constraints(existing: dict[str, Any] | None, text: str) -> dict[str, Any]:
    constraints = normalize_constraints(existing)
    message = text or ""

    if _DIRECT_CLEAR_RE.search(message):
        constraints["direct_only"] = False
    elif _DIRECT_ONLY_RE.search(message):
        constraints["direct_only"] = True

    if _BRAND_CLEAR_RE.search(message):
        constraints["allowed_hotel_brands"] = []
    else:
        brands = extract_hotel_brands(message)
        if brands:
            constraints["allowed_hotel_brands"] = brands

    if _DIETARY_RE.search(message):
        constraints["dietary"] = _DIETARY_RE.search(message).group(0)
    if _ACCESSIBILITY_RE.search(message):
        constraints["accessibility"] = True
    if _AVOID_LUXURY_RE.search(message):
        constraints["avoid_luxury"] = True
        constraints["budget_strategy"] = "cheapest"
    elif _VIP_RE.search(message):
        constraints["avoid_luxury"] = False
        constraints["budget_strategy"] = "vip"

    return constraints
