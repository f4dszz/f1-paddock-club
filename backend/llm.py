"""LLM client helper for the F1 Paddock Club agents.

The provider is selectable via the LLM_PROVIDER env var:

- "openai" (default)
    Uses langchain-openai. Reads OPENAI_API_KEY. Optional OPENAI_MODEL
    (default "gpt-4o-mini") and OPENAI_BASE_URL (for OpenAI-compatible
    proxies like DeepSeek, Moonshot, GLM, etc.).

- "anthropic"
    Uses langchain-anthropic. Reads ANTHROPIC_API_KEY. Optional
    ANTHROPIC_MODEL (default "claude-sonnet-4-5") and ANTHROPIC_BASE_URL.

Agents call get_llm() and treat a None return as "fall back to mock".
That happens when:
- the required API key is not set
- the required langchain provider package is not installed
- the client fails to initialize

Environment variables can come from the process environment or from a
backend/.env file (loaded automatically here via python-dotenv).
"""

from __future__ import annotations
import logging
import os
import threading
import time
from collections import defaultdict

# Load .env file if python-dotenv is installed. Best-effort: if the
# package isn't there or the file is missing, we silently fall through
# to the bare process environment.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


logger = logging.getLogger(__name__)


PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()

DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    """Read an int env var with a floor, falling back to default on garbage."""
    try:
        return max(int(os.environ.get(name, str(default))), minimum)
    except (TypeError, ValueError):
        return default


# ── Request timeout / retry (backend-completeness-2) ────────────────
# An LLM provider stall used to block an asyncio.to_thread worker for as
# long as the underlying httpx client allowed (effectively unbounded behind
# a proxy). With MAX_CONCURRENT_PLANS workers, a few stalled calls could
# exhaust the pool. Bounding both timeout and retries caps tail latency.
# Env-configurable per the project's "new tunable limits" rule.
def _llm_timeout_seconds() -> float:
    raw = os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS", "60")
    try:
        return max(float(raw), 1.0)
    except (TypeError, ValueError):
        return 60.0


def _llm_max_retries() -> int:
    return _int_env("LLM_MAX_RETRIES", 2, minimum=0)


# ── Per-identity daily LLM call ceiling (BS-15) ─────────────────────
# In-process, per-identity counter consistent with main.IPRateLimiter's
# demo-grade style. NOTE: like that limiter, this state lives in one
# process only — it resets on restart and does NOT coordinate across
# multiple uvicorn workers/replicas. A shared store (Redis) would be the
# cross-instance fix; documented as a known limitation. 0 = disabled.
_llm_call_lock = threading.Lock()
_llm_call_counts: dict[tuple[str, str], int] = defaultdict(int)


class LLMDailyLimitError(RuntimeError):
    """Raised when an identity exceeds its daily LLM call ceiling."""


def _llm_daily_limit() -> int:
    return _int_env("LLM_DAILY_CALL_LIMIT", 200, minimum=0)


def _utc_day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def check_llm_quota(identity: str | None) -> None:
    """Enforce a per-identity daily LLM call ceiling.

    Raises LLMDailyLimitError when the configured ceiling is exceeded.
    A ceiling of 0 (LLM_DAILY_CALL_LIMIT=0) disables the guard entirely.
    `identity` is typically the authenticated user_id; None/"" collapses
    to a shared "anonymous" bucket.
    """
    limit = _llm_daily_limit()
    if limit <= 0:
        return
    key = (identity or "anonymous", _utc_day_key())
    with _llm_call_lock:
        current = _llm_call_counts.get(key, 0)
        if current >= limit:
            raise LLMDailyLimitError(
                f"daily LLM call limit reached ({limit}/day). Try again tomorrow."
            )
        _llm_call_counts[key] = current + 1


def reset_llm_quota_for_tests() -> None:
    """Test helper: clears the in-process per-identity daily call counter."""
    with _llm_call_lock:
        _llm_call_counts.clear()

_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
}


def provider_label() -> str:
    """Human-readable label for the active provider, used in status messages."""
    return _PROVIDER_LABELS.get(PROVIDER, PROVIDER)


def get_llm(temperature: float = 0.7, max_tokens: int = 1024):
    """Return a configured LangChain chat model, or None if unavailable.

    The returned model supports `with_structured_output(PydanticSchema)`,
    which is what the itinerary and tour agents rely on.
    """
    if PROVIDER == "openai":
        return _get_openai(temperature, max_tokens)
    if PROVIDER == "anthropic":
        return _get_anthropic(temperature, max_tokens)
    return None


def _get_openai(temperature: float, max_tokens: int):
    if not os.environ.get("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY not set, agents will use mock fallback")
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning("langchain-openai not installed, agents will use mock fallback")
        return None
    try:
        kwargs: dict = {
            "model": DEFAULT_OPENAI_MODEL,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Bound provider tail latency so a stalled call cannot pin a
            # worker thread indefinitely (backend-completeness-2).
            "timeout": _llm_timeout_seconds(),
            "max_retries": _llm_max_retries(),
        }
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        logger.debug("initializing ChatOpenAI model=%s base_url=%s", DEFAULT_OPENAI_MODEL, base_url or "default")
        return ChatOpenAI(**kwargs)
    except Exception:
        logger.exception("failed to initialize ChatOpenAI")
        return None


def _get_anthropic(temperature: float, max_tokens: int):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("ANTHROPIC_API_KEY not set, agents will use mock fallback")
        return None
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        logger.warning("langchain-anthropic not installed, agents will use mock fallback")
        return None
    try:
        kwargs: dict = {
            "model": DEFAULT_ANTHROPIC_MODEL,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Bound provider tail latency so a stalled call cannot pin a
            # worker thread indefinitely (backend-completeness-2).
            "timeout": _llm_timeout_seconds(),
            "max_retries": _llm_max_retries(),
        }
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        logger.debug("initializing ChatAnthropic model=%s base_url=%s", DEFAULT_ANTHROPIC_MODEL, base_url or "default")
        return ChatAnthropic(**kwargs)
    except Exception:
        logger.exception("failed to initialize ChatAnthropic")
        return None
