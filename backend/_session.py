"""Session-level conversation history management.

Maintains chat history separate from plan state (TravelPlanState).
The supervisor reads history to resolve references like "not that one"
or "the hotel you showed earlier."

Design (per supervisor Round 008/010):
- History lives at session level, NOT inside TravelPlanState
- Max 6 turns (12 messages) to limit token usage
- Helper functions for append/trim — ready for future Redis/persistence
"""

from __future__ import annotations

MAX_TURNS = 6  # 6 turns = 12 messages (user + assistant)


def create_session() -> dict:
    """Create a fresh session context.

    Returns:
        dict with plan_state (empty) and conversation_history (empty list).
        These are the two top-level buckets — plan data and chat context
        are kept separate by design.
    """
    return {
        "plan_state": {},
        "conversation_history": [],
    }


def append_turn(session: dict, user_message: str, assistant_reply: str) -> None:
    """Append a user/assistant turn to conversation history.

    Automatically trims to MAX_TURNS if over limit.
    """
    history = session.setdefault("conversation_history", [])
    history.append(("user", user_message))
    history.append(("assistant", assistant_reply))
    _trim(history)


def clear_history(session: dict) -> None:
    """Clear conversation history (e.g., on new plan)."""
    session["conversation_history"] = []


def get_history(session: dict) -> list[tuple[str, str]]:
    """Return current conversation history as list of (role, content) tuples."""
    return session.get("conversation_history", [])


def _trim(history: list) -> None:
    """Keep only the most recent MAX_TURNS turns (2 messages per turn)."""
    max_messages = MAX_TURNS * 2
    if len(history) > max_messages:
        del history[:len(history) - max_messages]
