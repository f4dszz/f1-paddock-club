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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logging_config import setup_logging
from graph import plan_trip
from refine import refine_plan
from _session import create_session, append_turn, clear_history, get_history

setup_logging()
logger = logging.getLogger(__name__)


app = FastAPI(title="F1 Paddock Club", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class TripRequest(BaseModel):
    gp_name: str = "Italian GP"
    gp_city: str = "Monza"
    gp_date: str = "Sep 6"
    origin: str = "New York"
    budget: float = 2500
    stand_pref: str = "any"
    extra_days: int = 2
    stops: str = ""
    special_requests: str = ""


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


# ── POST /plan (unchanged, backward compatible) ────────────────────

@app.post("/plan")
async def plan(req: TripRequest):
    """Run the full planning pipeline and return the result."""
    result = await asyncio.to_thread(plan_trip, req.model_dump())
    snapshot = _state_snapshot(result)
    snapshot["messages"] = result.get("messages", [])
    return snapshot


# ── WebSocket /ws (two-lane session routing) ────────────────────────

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
    """Run Lane 1 full pipeline. Clears history (fresh start)."""
    logger.info("/ws plan: %s", data.get("gp_name", "?"))

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Starting your trip plan..."},
    })

    result = await asyncio.to_thread(plan_trip, data)

    for msg in result.get("messages", []):
        await ws.send_json({"type": "message", "data": msg})

    # Replace plan state entirely + clear conversation history
    session["plan_state"] = result
    clear_history(session)

    await ws.send_json({"type": "result", "data": _state_snapshot(result)})
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

    # Run Lane 2 with history
    updated_state, reply = await asyncio.to_thread(
        refine_plan, plan_state, user_message, history,
    )

    session["plan_state"] = updated_state

    # Record this turn in conversation history
    append_turn(session, user_message, reply)

    await ws.send_json({"type": "reply", "data": reply})
    await ws.send_json({"type": "result", "data": _state_snapshot(updated_state)})
    await ws.send_json({"type": "done"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
