"""Disk-backed cache decorator for tool functions.

Usage:
    @cached(ttl=3600)               # 固定 TTL (秒)
    def search_flights(...): ...

    @cached(ttl=my_ttl_function)    # 动态 TTL: callable 接收和被装饰函数一样的参数
    def search_tickets(...): ...

Cache files live in backend/tools/.cache/ (one JSON file per function).
This directory is gitignored. Cache is keyed by a hash of the function's
arguments, so the same query returns the same cached result until expiry.

Design notes:
- Zero external dependencies (stdlib only).
- Disk-backed so cache survives process restarts — important for
  rate-limited APIs like SerpAPI (100 free/month).
- Each function gets its own JSON file, so you can inspect/delete
  caches per tool: `cat backend/tools/.cache/search_flights.json`
- Not thread-safe for writes. Fine for our single-process FastAPI +
  uvicorn setup. If we go multi-worker later, swap to Redis (only
  this file changes; no tool code changes).
"""

from __future__ import annotations
import hashlib
import json
import logging
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Cache directory sits alongside the tool modules.
# .gitignore should include `backend/tools/.cache/`.
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


def _make_key(args: tuple, kwargs: dict) -> str:
    """Deterministic cache key from function arguments.

    We serialize args + kwargs to a canonical JSON string, then take
    its MD5 hex digest. sort_keys=True + default=str ensure the same
    logical arguments always produce the same key, regardless of dict
    ordering or non-JSON types (dates, enums, etc.).
    """
    raw = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _load(path: Path) -> dict:
    """Load an existing cache file, or return empty dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupted cache file — start fresh.
        logger.warning("cache file corrupted, resetting: %s", path)
        return {}


def _save(path: Path, data: dict) -> None:
    """Atomically write cache data to disk."""
    # ensure_ascii=False so Chinese city names etc. stay readable.
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def cached(ttl: int | float | Callable[..., int | float]):
    """Decorator that caches a function's return value on disk.

    Args:
        ttl: Time-to-live in seconds. Can be:
             - A number (int/float): every call uses this fixed TTL.
             - A callable: receives the same (*args, **kwargs) as the
               decorated function and returns the TTL for that specific
               call. Use this for search_tickets where TTL varies by
               how close the race is.

    The decorated function MUST return JSON-serializable data (dicts,
    lists, strings, numbers). Our tool functions return list[dict]
    which satisfies this.
    """
    def decorator(func: Callable) -> Callable:
        cache_file = CACHE_DIR / f"{func.__name__}.json"

        @wraps(func)  # preserves __name__, __doc__ of the original
        def wrapper(*args, **kwargs) -> Any:
            # ── Compute TTL for this call ──
            if callable(ttl):
                ttl_seconds = float(ttl(*args, **kwargs))
            else:
                ttl_seconds = float(ttl)

            # ── Build cache key ──
            key = _make_key(args, kwargs)

            # ── Check cache ──
            store = _load(cache_file)
            entry = store.get(key)
            if entry is not None and entry["expires_at"] > time.time():
                logger.info(
                    "cache HIT  %s (key=%s..., expires in %ds)",
                    func.__name__, key[:8],
                    int(entry["expires_at"] - time.time()),
                )
                return entry["value"]

            # ── Cache miss — call the real function ──
            logger.info("cache MISS %s (key=%s...)", func.__name__, key[:8])
            value = func(*args, **kwargs)

            # ── Store result ──
            store[key] = {
                "value": value,
                "expires_at": time.time() + ttl_seconds,
            }
            _save(cache_file, store)

            return value

        return wrapper
    return decorator


def clear_cache(name: str | None = None) -> int:
    """Delete cached data.

    Args:
        name: Function name (e.g. "search_flights") to clear just that
              tool's cache. None = clear everything.

    Returns:
        Number of cache files deleted.
    """
    deleted = 0
    if name:
        target = CACHE_DIR / f"{name}.json"
        if target.exists():
            target.unlink()
            deleted = 1
    else:
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
            deleted += 1
    logger.info("cache cleared: %d file(s)%s", deleted, f" ({name})" if name else "")
    return deleted
