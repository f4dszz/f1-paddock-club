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
import os

# Load .env file if python-dotenv is installed. Best-effort: if the
# package isn't there or the file is missing, we silently fall through
# to the bare process environment.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()

DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

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
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    try:
        kwargs: dict = {
            "model": DEFAULT_OPENAI_MODEL,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)
    except Exception:
        return None


def _get_anthropic(temperature: float, max_tokens: int):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return None
    try:
        kwargs: dict = {
            "model": DEFAULT_ANTHROPIC_MODEL,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        return ChatAnthropic(**kwargs)
    except Exception:
        return None
