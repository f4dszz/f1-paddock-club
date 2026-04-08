"""LLM client helper for the F1 Paddock Club agents.

Wraps langchain-anthropic so agents can do:

    llm = get_llm()
    if llm is None:
        return mock_data()
    structured = llm.with_structured_output(MySchema)
    result = structured.invoke([("system", ...), ("user", ...)])

If ANTHROPIC_API_KEY is missing or langchain-anthropic isn't installed,
get_llm() returns None and agents fall back to their Phase 1 mock data.

Override the model with the ANTHROPIC_MODEL env var.
"""

from __future__ import annotations
import os

# Default to a known-good Sonnet model. Override with ANTHROPIC_MODEL env var
# (e.g. "claude-sonnet-4-6" or "claude-haiku-4-5-20251001") if you want a
# different model.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


def get_llm(temperature: float = 0.7, max_tokens: int = 1024):
    """Return a configured ChatAnthropic instance, or None if unavailable.

    Returns None when:
    - ANTHROPIC_API_KEY is not set in the environment
    - langchain-anthropic is not installed
    - the client fails to initialize for any other reason

    Agents should treat None as a signal to fall back to mock data.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        return None
    try:
        return ChatAnthropic(
            model=DEFAULT_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception:
        return None
