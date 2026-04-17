"""FastAPI server for the F1 Paddock Club Travel Assistant.

Provides:
- POST /plan  — trigger a full planning run, returns complete result
- WS   /ws    — WebSocket session with two-lane routing:
                  First message (type=plan) → Lane 1 (full DAG pipeline)
                  Subsequent messages (type=chat) → Lane 2 (supervisor refinement)

WebSocket message protocol:

  Client → Server:
    {"type": "plan", "data": {TripRequest fields}}   — start/restart full plan
    {"type": "chat", "data": "user message text"}     — refine existing plan

  Server → Client:
    {"type": "message", "data": {"agent": "...", "text": "..."}}  — status update
    {"type": "result",  "data": {tickets, transport, hotel, ...}} — full state snapshot
    {"type": "reply",   "data": "supervisor text response"}       — Lane 2 text reply
    {"type": "done"}                                               — request complete
    {"type": "error",   "data": "error description"}              — error
"""

from __future__ import annotations
import asyncio
import json
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError, field_validator

from logging_config import setup_logging
from graph import plan_trip
from refine import refine_plan
from _session import create_session, append_turn, clear_history, get_history
from tools._race_calendar import all_races, upcoming_races, is_past


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize file logging only when the app actually starts serving.
    # Bare imports (e.g. `from main import TripRequest` in a script)
    # no longer write to the log file.
    log_file = setup_logging()
    logger.info("FastAPI starting, log file: %s", log_file)
    yield
    logger.info("FastAPI shutting down")


app = FastAPI(title="F1 Paddock Club", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


_SUPPORTED_CURRENCIES = {"EUR", "USD", "CNY"}


class TripRequest(BaseModel):
    gp_name: str = "Italian GP"
    gp_city: str = "Monza"
    gp_date: str = "Sep 6"
    origin: str = "New York"
    budget: float = 2500
    currency: str = "EUR"     # "EUR" | "USD" | "CNY"
    stand_pref: str = "any"
    extra_days: int = 2
    stops: str = ""
    special_requests: str = ""

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, v):
        # Accept any case (e.g. "usd") and normalize to upper.
        # Reject anything outside the supported set — explicit invalid input
        # must not silently fall back to EUR.
        code = str(v or "EUR").strip().upper()
        if code not in _SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency {v!r}. Must be one of: "
                f"{', '.join(sorted(_SUPPORTED_CURRENCIES))}."
            )
        return code


def _validate_plan_payload(data) -> TripRequest:
    """Wrap TripRequest validation with a clean error surface.

    Raises ValueError(reason) on invalid input. Used by both HTTP and
    WS entry points so they share the same validation contract.

    Non-dict payloads (string, list, null, number) are rejected rather
    than silently falling back to default values — an explicit bad
    input deserves an explicit error.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"plan payload must be a JSON object, got {type(data).__name__}"
        )
    try:
        return TripRequest(**data)
    except ValidationError as e:
        # Surface the first field error in plain text; FastAPI's own
        # error body is noisy and not meant for end-user consumption.
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        msg = first.get("msg", "invalid input")
        raise ValueError(f"{loc}: {msg}" if loc else msg)


def _state_snapshot(state: dict) -> dict:
    """Extract the serializable result from state for the client."""
    return {
        "tickets": state.get("tickets", []),
        "transport": state.get("transport", []),
        "hotel": state.get("hotel", []),
        "itinerary": state.get("itinerary", []),
        "tour": state.get("tour", []),
        "budget_summary": state.get("budget_summary"),
    }


# ── GET /api/calendar — GP list for frontend ────────────────────────

@app.get("/api/calendar")
async def get_calendar():
    """Return the 2026 race calendar for the GP selection grid."""
    from datetime import date
    today = date.today()
    races = all_races()
    return [
        {
            "gp_name": r["gp_name"],
            "city": r["city"],
            "country": r["country"],
            "race_date": r["race_date"],
            "round": r["round"],
            "sprint": r.get("sprint", False),
            "is_past": is_past(r["gp_name"], today),
        }
        for r in races
    ]


# ── POST /plan (unchanged, backward compatible) ────────────────────

@app.post("/plan")
async def plan(payload: dict):
    """Run the full planning pipeline and return the result.

    Validates explicitly via _validate_plan_payload so that invalid
    input (e.g. unsupported currency) surfaces as a clean 400 rather
    than Pydantic's default 422 or a downstream 500.
    """
    try:
        req = _validate_plan_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = await asyncio.to_thread(plan_trip, req.model_dump())
    snapshot = _state_snapshot(result)
    snapshot["messages"] = result.get("messages", [])
    return snapshot


# ── WebSocket /ws (two-lane session routing) ────────────────────────

MAX_WS_MESSAGE_SIZE = 16 * 1024  # 16KB max per ws message


def _build_trace_events(
    before_state: dict | None,
    after_state: dict,
    failed_tools: list[str] | None = None,
    updated_fields: list[str] | None = None,
) -> list[dict]:
    """Derive trace events from state before/after a handler run.

    Emits three event kinds per reviewer Round 026 Step 1 scope:
      - state_apply  (one per changed list field — by content, not just count)
      - tool_fail    (one per failed Lane-2 tool call)
      - budget_final (once, from final budget_summary)

    state_apply detection: Lane 2 callers pass an explicit `updated_fields`
    list from `_apply_tool_updates`, which is the authoritative signal
    that a tool wrote to that field (even if counts match, e.g. 3 hotels
    replaced by 3 different hotels). Lane 1 callers pass None, in which
    case we fall back to a JSON content diff (every agent run rewrites
    state fresh, so this catches real content changes).
    """
    events: list[dict] = []
    before = before_state or {}

    for field in ("tickets", "transport", "hotel", "itinerary", "tour"):
        b = before.get(field) or []
        a = after_state.get(field) or []

        if updated_fields is not None:
            # Lane 2: trust the refine closure's report
            changed = field in updated_fields
        else:
            # Lane 1 (or unknown): content-aware diff
            try:
                changed = json.dumps(a, sort_keys=True, ensure_ascii=False) \
                       != json.dumps(b, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                changed = len(a) != len(b)

        if changed:
            events.append({
                "event": "state_apply",
                "field": field,
                "before_count": len(b),
                "after_count": len(a),
            })

    for name in (failed_tools or []):
        events.append({"event": "tool_fail", "tool": name})

    bs = after_state.get("budget_summary") or {}
    if bs:
        events.append({
            "event": "budget_final",
            "total": bs.get("total"),
            "budget": bs.get("budget"),
            "currency": bs.get("currency"),
            "within_budget": bs.get("within_budget"),
        })

    return events


async def _send_trace(ws: WebSocket, events: list[dict], enabled: bool) -> None:
    if not enabled or not events:
        return
    for ev in events:
        await ws.send_json({"type": "trace", "data": ev})

@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    """WebSocket endpoint with session state and two-lane routing.

    The connection IS the session. State lives for the duration of
    the WebSocket connection. No external session store needed.

    Routing:
      type=plan → Lane 1 (graph.py): full parallel DAG, produces complete plan
      type=chat → Lane 2 (refine.py): supervisor agent, targeted updates

    type=plan can be sent again to start fresh (clears state).
    type=chat as the very first message goes to refine.py planning mode
    (produces 3/5 sections — no itinerary/tour).
    """
    await ws.accept()
    session = create_session()

    try:
        while True:
            raw = await ws.receive_text()

            # Minimal safety: reject oversized messages
            if len(raw) > MAX_WS_MESSAGE_SIZE:
                await ws.send_json({"type": "error", "data": "Message too large"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")
            msg_data = msg.get("data", {})

            # Backward compat: raw TripRequest without {type, data} envelope.
            if not msg_type and msg.get("gp_name"):
                msg_type = "plan"
                msg_data = msg

            if msg_type == "plan":
                await _handle_plan(ws, msg_data, session)

            elif msg_type == "chat":
                await _handle_chat(ws, msg_data, session)

            else:
                await ws.send_json({
                    "type": "error",
                    "data": f"Unknown message type: {msg_type}. Use 'plan' or 'chat'.",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket session error")
        try:
            await ws.send_json({"type": "error", "data": str(e)})
            await ws.close()
        except Exception:
            pass


async def _handle_plan(ws: WebSocket, data: dict, session: dict) -> None:
    """Run Lane 1 full pipeline. Clears history (fresh start).

    Validates the payload in-place (e.g. unsupported currency) and
    sends a type=error without closing the socket, so the user can
    correct the input and try again.
    """
    logger.info("/ws plan: %s", data.get("gp_name", "?"))

    # Debug opt-in: once set on a plan call, it stays on for subsequent
    # chats in the same session. Reviewer Round 026 picked plan-envelope
    # flag over ws query string.
    if data.get("debug") is True or data.get("_debug") is True:
        session["debug"] = True

    try:
        req = _validate_plan_payload(data)
    except ValueError as e:
        await ws.send_json({"type": "error", "data": f"Invalid plan input: {e}"})
        return  # socket stays open for retry

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Starting your trip plan..."},
    })

    before = session.get("plan_state") or {}
    result = await asyncio.to_thread(plan_trip, req.model_dump())

    for msg in result.get("messages", []):
        await ws.send_json({"type": "message", "data": msg})

    # Replace plan state entirely + clear conversation history
    session["plan_state"] = result
    clear_history(session)

    await ws.send_json({"type": "result", "data": _state_snapshot(result)})

    # Minimal trace (Step 1): state_apply + budget_final. Lane 1 doesn't
    # expose per-tool failures so tool_fail stays empty here.
    trace = _build_trace_events(before, result, failed_tools=[])
    await _send_trace(ws, trace, session.get("debug", False))

    await ws.send_json({"type": "done"})


async def _handle_chat(ws: WebSocket, data, session: dict) -> None:
    """Run Lane 2 supervisor with conversation history."""
    user_message = data if isinstance(data, str) else str(data)
    logger.info("/ws chat: %s", user_message[:100])

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Processing your request..."},
    })

    plan_state = session.get("plan_state", {})
    history = get_history(session)

    # Snapshot state for trace diff; refine_plan mutates plan_state
    # in place but returns the same object, so the shallow before-copy
    # would see post-mutation values. Keep a pre-mutation field-count
    # snapshot instead of deep-copying the whole state.
    before_snapshot = {f: list(plan_state.get(f) or []) for f in ("tickets", "transport", "hotel", "itinerary", "tour")}

    # Run Lane 2 with history. Returns (state, reply, trace_context).
    updated_state, reply, trace_ctx = await asyncio.to_thread(
        refine_plan, plan_state, user_message, history,
    )

    session["plan_state"] = updated_state

    # Record this turn in conversation history
    append_turn(session, user_message, reply)

    await ws.send_json({"type": "reply", "data": reply})
    await ws.send_json({"type": "result", "data": _state_snapshot(updated_state)})

    # Minimal trace for Lane 2 — updated_fields from refine trace_ctx is
    # authoritative (tool actually wrote), which also covers the
    # "3 hotels → 3 different hotels" case that pure count diff misses.
    trace = _build_trace_events(
        before_snapshot,
        updated_state,
        failed_tools=trace_ctx.get("failed_tools") or [],
        updated_fields=trace_ctx.get("updated_fields") or [],
    )
    await _send_trace(ws, trace, session.get("debug", False))

    await ws.send_json({"type": "done"})


if __name__ == "__main__":
    # Lifespan handler will call setup_logging() when the app starts.
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
