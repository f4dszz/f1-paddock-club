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
    {"type": "quote", "data": {"selections": {...}}}  — recompute selected total

  Server → Client:
    {"type": "message", "data": {"agent": "...", "text": "..."}}  — status update
    {"type": "result",  "data": {tickets, transport, hotel, ...}} — full state snapshot
    {"type": "quote",   "data": {quote_id, budget_summary}}       — selected quote
    {"type": "reply",   "data": "supervisor text response"}       — Lane 2 text reply
    {"type": "done"}                                               — request complete
    {"type": "error",   "data": "error description"}              — error
"""

from __future__ import annotations
import asyncio
import copy
import json
import logging
import os
import time

from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError, field_validator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from logging_config import setup_logging
from graph import plan_trip
from refine import refine_plan
from _session import create_session, append_turn, clear_history, get_history
from tools._race_calendar import all_races, upcoming_races, is_past
from tools.recompute import recompute_budget
from tools._trip_dates import validate_trip_dates


logger = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return max(value, minimum)
    except (TypeError, ValueError):
        return default


_APP_ENV = os.environ.get("APP_ENV") or os.environ.get("ENV") or "local"
_IS_LOCAL_ENV = _APP_ENV.strip().lower() in {"", "local", "dev", "development", "test"}
_DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
_ALLOWED_ORIGINS = _csv_env("ALLOWED_ORIGINS") or (_DEV_ORIGINS if _IS_LOCAL_ENV else [])
_ALLOWED_ORIGINS_SET = set(_ALLOWED_ORIGINS)
_DEMO_ACCESS_TOKEN = os.environ.get("DEMO_ACCESS_TOKEN", "").strip()
_REQUIRE_DEMO_TOKEN = bool(_DEMO_ACCESS_TOKEN) or (
    not _IS_LOCAL_ENV
) or _env_flag("REQUIRE_DEMO_TOKEN", False)
_MAX_CONCURRENT_PLANS = _int_env("MAX_CONCURRENT_PLANS", 5)
_PLAN_ACQUIRE_TIMEOUT_SECONDS = _int_env("PLAN_ACQUIRE_TIMEOUT_SECONDS", 5)
_HTTP_LIMIT_PER_MINUTE = _int_env("HTTP_RATE_LIMIT_PER_MINUTE", 60)
_WS_LIMIT_PER_MINUTE = _int_env("WS_CONNECT_LIMIT_PER_MINUTE", 20)
_plan_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PLANS)


class ServerBusyError(RuntimeError):
    pass


class IPRateLimiter:
    """Small in-process sliding-window limiter for demo-stage abuse control."""

    def __init__(self, max_per_window: int, window_seconds: int):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        if self.max_per_window <= 0:
            return True
        now = time.monotonic()
        events = self._events[ip]
        cutoff = now - self.window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self.max_per_window:
            return False
        events.append(now)
        return True


_http_rate_limiter = IPRateLimiter(_HTTP_LIMIT_PER_MINUTE, 60)
_ws_connect_limiter = IPRateLimiter(_WS_LIMIT_PER_MINUTE, 60)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ws_client_ip(ws: WebSocket) -> str:
    forwarded = ws.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


def _valid_http_token(authorization: str | None) -> bool:
    if not _REQUIRE_DEMO_TOKEN:
        return True
    if not _DEMO_ACCESS_TOKEN:
        return False
    return authorization == f"Bearer {_DEMO_ACCESS_TOKEN}"


def _valid_ws_token(token: str | None) -> bool:
    if not _REQUIRE_DEMO_TOKEN:
        return True
    return bool(_DEMO_ACCESS_TOKEN and token == _DEMO_ACCESS_TOKEN)


def _check_http_access(request: Request, authorization: str | None) -> None:
    ip = _client_ip(request)
    if not _http_rate_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not _valid_http_token(authorization):
        raise HTTPException(status_code=401, detail="Missing or invalid demo token")


def _ws_origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "")
    if not origin or not _ALLOWED_ORIGINS_SET:
        return True
    return origin in _ALLOWED_ORIGINS_SET


async def _run_plan_with_limit(payload: dict) -> dict:
    try:
        async with asyncio.timeout(_PLAN_ACQUIRE_TIMEOUT_SECONDS):
            await _plan_semaphore.acquire()
    except TimeoutError as exc:
        raise ServerBusyError("Server is busy. Please try again shortly.") from exc
    try:
        return await asyncio.to_thread(plan_trip, payload)
    finally:
        _plan_semaphore.release()


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
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


_SUPPORTED_CURRENCIES = {"EUR", "USD", "CNY"}


class TripRequest(BaseModel):
    gp_name: str = "Italian GP"
    gp_city: str = "Monza"
    gp_date: str = "Sep 6"
    origin: str = "New York"
    budget: float = 2500
    currency: str = "EUR"         # "EUR" | "USD" | "CNY"
    stand_pref: str = "any"
    extra_days: int = 2           # legacy; ignored when depart_date/return_date are set
    depart_date: str = ""         # optional explicit travel dates (ISO YYYY-MM-DD)
    return_date: str = ""
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

    Three layers of validation happen here, in order:
      1. Shape  — reject non-dict payloads outright
      2. Schema — Pydantic + the currency field_validator
      3. Travel-date semantics — validate_trip_dates() on the pair
         (depart_date, return_date). Lets us surface "depart after
         return" at the API boundary instead of producing a bad plan.

    Non-dict payloads and explicit invalid dates are rejected rather
    than silently falling back to defaults — explicit bad input
    deserves an explicit error.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"plan payload must be a JSON object, got {type(data).__name__}"
        )
    try:
        req = TripRequest(**data)
    except ValidationError as e:
        # Surface the first field error in plain text; FastAPI's own
        # error body is noisy and not meant for end-user consumption.
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        msg = first.get("msg", "invalid input")
        raise ValueError(f"{loc}: {msg}" if loc else msg)

    ok, reason = validate_trip_dates(req.gp_date, req.depart_date, req.return_date)
    if not ok:
        raise ValueError(reason)

    return req


def _state_snapshot(state: dict) -> dict:
    """Extract the serializable result from state for the client."""
    return {
        "tickets": state.get("tickets", []),
        "transport": state.get("transport", []),
        "hotel": state.get("hotel", []),
        "itinerary": state.get("itinerary", []),
        "tour": state.get("tour", []),
        "budget_summary": state.get("budget_summary"),
        "active_constraints": state.get("active_constraints", {}),
    }


# ── GET /api/calendar — GP list for frontend ────────────────────────

@app.get("/api/calendar")
async def get_calendar(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return the 2026 race calendar for the GP selection grid."""
    _check_http_access(request, authorization)
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
async def plan(
    payload: dict,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Run the full planning pipeline and return the result.

    Validates explicitly via _validate_plan_payload so that invalid
    input (e.g. unsupported currency) surfaces as a clean 400 rather
    than Pydantic's default 422 or a downstream 500.
    """
    _check_http_access(request, authorization)
    try:
        req = _validate_plan_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await _run_plan_with_limit(req.model_dump())
    except ServerBusyError as e:
        raise HTTPException(status_code=503, detail=str(e))
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

    Emits three event kinds (minimum viable observability surface):
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
    client_ip = _ws_client_ip(ws)
    if not _ws_connect_limiter.allow(client_ip):
        await ws.close(code=1008)
        return
    if not _ws_origin_allowed(ws):
        await ws.close(code=1008)
        return
    if not _valid_ws_token(ws.query_params.get("demo_token")):
        await ws.close(code=1008)
        return

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

            elif msg_type == "quote":
                await _handle_quote(ws, msg_data, session)

            else:
                await ws.send_json({
                    "type": "error",
                    "data": f"Unknown message type: {msg_type}. Use 'plan', 'chat', or 'quote'.",
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
    logger.info("/ws plan: %s", data.get("gp_name", "?") if isinstance(data, dict) else "?")

    # Debug opt-in: once set on a plan call, it stays on for subsequent
    # chats in the same session. Plan-envelope flag is preferred over a
    # ws query string because it lets clients toggle per-request later.
    if isinstance(data, dict) and (data.get("debug") is True or data.get("_debug") is True):
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
    try:
        result = await _run_plan_with_limit(req.model_dump())
    except ServerBusyError as e:
        await ws.send_json({"type": "error", "data": str(e)})
        return

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
    """Run Lane 2 supervisor with conversation history.

    Copy-on-write discipline: `refine_plan` mutates the state dict
    it receives (the state-aware tool factory + `_apply_tool_updates`
    write directly onto it). If any step raises mid-mutation, the
    session must not be left with a half-updated plan. We deep-copy
    the session plan_state once up front, hand the copy to refine_plan,
    and only swap it back into the session on success.
    """
    user_message = data if isinstance(data, str) else str(data)
    logger.info("/ws chat: %s", user_message[:100])

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Processing your request..."},
    })

    original = session.get("plan_state") or {}
    history = get_history(session)

    # Snapshot pre-mutation field lists for the trace diff. Cheap and
    # taken from the original (not the working copy) so it survives
    # regardless of what happens inside refine_plan.
    before_snapshot = {
        f: list(original.get(f) or [])
        for f in ("tickets", "transport", "hotel", "itinerary", "tour")
    }

    working = copy.deepcopy(original)
    try:
        updated_state, reply, trace_ctx = await asyncio.to_thread(
            refine_plan, working, user_message, history,
        )
    except ValueError as e:
        # Known, user-actionable: surface plainly, keep session intact
        await ws.send_json({"type": "error", "data": f"Refine failed: {e}"})
        return
    except Exception:
        logger.exception("_handle_chat unexpected error")
        await ws.send_json({
            "type": "error",
            "data": "Internal chat error. Your plan is unchanged — please try again.",
        })
        return

    # Only reached on success — commit to session
    session["plan_state"] = updated_state
    append_turn(session, user_message, reply)

    await ws.send_json({"type": "reply", "data": reply})
    await ws.send_json({"type": "result", "data": _state_snapshot(updated_state)})

    # updated_fields from refine trace_ctx is authoritative (tool
    # actually wrote), which also covers the "3 hotels → 3 different
    # hotels" case that pure count diff would miss.
    trace = _build_trace_events(
        before_snapshot,
        updated_state,
        failed_tools=trace_ctx.get("failed_tools") or [],
        updated_fields=trace_ctx.get("updated_fields") or [],
    )
    await _send_trace(ws, trace, session.get("debug", False))

    await ws.send_json({"type": "done"})


async def _handle_quote(ws: WebSocket, data, session: dict) -> None:
    """Recompute budget against frontend selections without mutating state."""
    if not isinstance(data, dict):
        await ws.send_json({"type": "error", "data": "quote payload must be a JSON object"})
        return

    state = session.get("plan_state") or {}
    if not state:
        await ws.send_json({"type": "error", "data": "No active plan to quote. Run planning first."})
        return

    selections = data.get("selections") or {}
    quote_id = data.get("quote_id")
    try:
        summary = recompute_budget(state, selections=selections)
    except ValueError as e:
        await ws.send_json({"type": "error", "data": f"Invalid quote selection: {e}"})
        return

    await ws.send_json({
        "type": "quote",
        "data": {"quote_id": quote_id, "budget_summary": summary},
    })


if __name__ == "__main__":
    # Lifespan handler will call setup_logging() when the app starts.
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
