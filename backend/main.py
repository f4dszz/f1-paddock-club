"""FastAPI server for the F1 Paddock Club Travel Assistant.

Provides:
- POST /plan — trigger a trip planning run, returns full result
- WS  /ws   — WebSocket for streaming agent status messages in real-time
"""

from __future__ import annotations
import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph import plan_trip


app = FastAPI(title="F1 Paddock Club", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


class TripRequest(BaseModel):
    gp_name: str = "Italian GP"
    gp_city: str = "Monza"
    gp_date: str = "Sep 7"
    origin: str = "New York"
    budget: float = 2500
    stand_pref: str = "any"
    extra_days: int = 2
    stops: str = ""
    special_requests: str = ""


@app.post("/plan")
async def plan(req: TripRequest):
    """Run the full planning pipeline synchronously and return the result."""
    result = await asyncio.to_thread(plan_trip, req.model_dump())

    # Strip non-serializable bits, return clean JSON
    return {
        "tickets": result.get("tickets", []),
        "transport": result.get("transport", []),
        "hotel": result.get("hotel", []),
        "itinerary": result.get("itinerary", []),
        "tour": result.get("tour", []),
        "budget_summary": result.get("budget_summary"),
        "messages": result.get("messages", []),
    }


@app.websocket("/ws")
async def websocket_plan(ws: WebSocket):
    """WebSocket endpoint for streaming agent status messages.

    Client sends a JSON TripRequest, server streams back messages
    as each agent completes, then sends the final result.
    """
    await ws.accept()
    try:
        raw = await ws.receive_text()
        req = json.loads(raw)

        # Run planning in a thread (LangGraph is sync)
        result = await asyncio.to_thread(plan_trip, req)

        # Stream messages one by one (simulate real-time in Phase 1)
        for msg in result.get("messages", []):
            await ws.send_json({"type": "message", "data": msg})
            await asyncio.sleep(0.3)  # simulate agent work time

        # Send final result
        await ws.send_json({
            "type": "result",
            "data": {
                "tickets": result.get("tickets", []),
                "transport": result.get("transport", []),
                "hotel": result.get("hotel", []),
                "itinerary": result.get("itinerary", []),
                "tour": result.get("tour", []),
                "budget_summary": result.get("budget_summary"),
            },
        })

        await ws.send_json({"type": "done"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_json({"type": "error", "data": str(e)})
        await ws.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
