"""Small deterministic edit helpers used by Lane 2 refinement tools.

The supervisor decides when an itinerary or tour card should change; this
module keeps the actual card rewrite server-side and schema-light.
"""

from __future__ import annotations

import json
import re
from typing import Any


def bounded_request(text: str, fallback: str = "") -> str:
    value = (text or fallback or "").strip()
    return value[:500] if len(value) > 500 else value


def entry_to_line(entry: Any, label: str) -> str:
    """Normalize LLM/tool-shaped entries into frontend-friendly strings."""
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        if label == "Itinerary":
            day = entry.get("day") or entry.get("day_number") or entry.get("index")
            title = entry.get("title") or entry.get("weekday") or entry.get("date") or ""
            items = entry.get("items") or entry.get("activities") or entry.get("plan") or entry.get("summary") or ""
            if isinstance(items, list):
                body = "; ".join(str(item).strip() for item in items if str(item).strip())
            else:
                body = str(items).strip()
            if day and body:
                day_text = str(day).strip()
                day_prefix = day_text if re.match(r"^day\b", day_text, re.IGNORECASE) else f"Day {day_text}"
                title_part = f" ({title})" if title else ""
                return f"{day_prefix}{title_part}: {body}"
            if body:
                return body
        name = entry.get("name") or entry.get("title") or entry.get("place") or entry.get("activity") or ""
        price = entry.get("price") or entry.get("cost") or entry.get("price_range") or ""
        desc = entry.get("description") or entry.get("summary") or entry.get("reason") or entry.get("notes") or ""
        if name and desc:
            price_part = f" ({price})" if price else ""
            return f"{name}{price_part} — {desc}"
        if name:
            return str(name).strip()
        if desc:
            return str(desc).strip()
        return json.dumps(entry, ensure_ascii=False)
    return str(entry).strip()


def target_index(lines: list[str], request: str) -> int:
    lowered = request.lower()
    for idx, line in enumerate(lines):
        candidate = re.split(r"\s+[—–-]\s+|:", line, maxsplit=1)[0]
        candidate = re.sub(r"\([^)]*\)", "", candidate).strip()
        if len(candidate) >= 4 and candidate.lower() in lowered:
            return idx

    weekday_aliases = [
        (("monday", "mon", "周一", "星期一"), ("monday", "mon", "周一", "星期一")),
        (("tuesday", "tue", "周二", "星期二"), ("tuesday", "tue", "周二", "星期二")),
        (("wednesday", "wed", "周三", "星期三"), ("wednesday", "wed", "周三", "星期三")),
        (("thursday", "thu", "周四", "星期四"), ("thursday", "thu", "周四", "星期四")),
        (("friday", "fri", "周五", "星期五"), ("friday", "fri", "周五", "星期五")),
        (("saturday", "sat", "周六", "星期六"), ("saturday", "sat", "周六", "星期六")),
        (("sunday", "sun", "周日", "星期日"), ("sunday", "sun", "周日", "星期日")),
    ]
    for request_terms, line_terms in weekday_aliases:
        if any(term in lowered or term in request for term in request_terms):
            for idx, line in enumerate(lines):
                ll = line.lower()
                if any(term in ll or term in line for term in line_terms):
                    return idx

    day_match = re.search(r"\bday\s*(\d+)\b|第\s*(\d+)\s*天", request, re.IGNORECASE)
    if day_match:
        day_num = int(next(g for g in day_match.groups() if g))
        if 1 <= day_num <= len(lines):
            return day_num - 1

    for idx, line in enumerate(lines):
        ll = line.lower()
        if any(token in lowered for token in ("dinner", "restaurant", "meal", "晚餐", "餐厅", "吃饭")) and any(
            token in ll or token in line for token in ("dinner", "restaurant", "meal", "晚餐", "餐厅", "吃饭")
        ):
            return idx
        if any(token in lowered or token in request for token in ("museum", "design", "景点", "博物馆", "设计")) and any(
            token in ll or token in line for token in ("museum", "gallery", "design", "景点", "博物馆", "美术馆", "设计")
        ):
            return idx
    return 0


def replacement_name(request: str) -> str:
    patterns = [
        r"(?:改成|改为|换成|替换为)\s*([^，。,.;；]+)",
        r"(?:replace|change|switch).{0,80}?\bto\s+([^,.;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, request, re.IGNORECASE)
        if match:
            return match.group(1).strip(" \"'")
    return ""


def apply_line_update(lines: list[Any], request: str, label: str, fallback_request: str = "") -> list[str]:
    request = bounded_request(request, fallback_request)
    clean_lines = [entry_to_line(line, label) for line in (lines or []) if entry_to_line(line, label)]
    if not clean_lines:
        return [f"{label} update requested: {request}"]
    target = target_index(clean_lines, request)
    updated = list(clean_lines)
    replacement = replacement_name(request) if label == "Tour" else ""
    if replacement:
        parts = re.split(r"\s+[—–-]\s+", updated[target], maxsplit=1)
        detail = parts[1] if len(parts) > 1 else "Updated recommendation"
        updated[target] = f"{replacement} — {detail}; Requested update: {request}"
        return updated
    separator = "; " if ":" in updated[target] else " — "
    updated[target] = f"{updated[target]}{separator}Requested update: {request}"
    return updated
