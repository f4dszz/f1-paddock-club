# F1 Paddock Club — Multi-Agent Travel Assistant

## Project Origin & Context

This project started from a conversation about multi-agent orchestration — how to coordinate multiple AI agents to complete complex tasks. The original problem was: "I use multiple AI products (Claude, OpenAI, Gemini) for different steps of a task, and manually triggering each one is exhausting."

After exploring several approaches (CLI wrapping, API adapters, frameworks), we landed on:
- **LangGraph** as the orchestration framework
- **Python + FastAPI** for the backend
- **React** for the frontend

The idea evolved from a generic code-refactoring orchestrator to an **F1 Grand Prix travel assistant** — a more compelling, demo-friendly, and portfolio-worthy project.

### Key Design Decisions

1. **Why F1?** More engaging than code-refactoring. Anyone can understand it. Strong visual identity. Natural multi-agent use case.
2. **Why LangGraph?** User knows Python/Java. LangGraph handles execution engine, parallel coordination, state management. Focus effort on agent logic, not infrastructure.
3. **Why structured form + chat?** Form handles fixed fields (origin, budget, dates, stand pref, stops, extra days). Chat handles special requests and adjustments. No LLM parsing needed for structured data.
4. **Why "Paddock Club" theme?** VIP experience metaphor. Dark theme + pixel-art characters. Each agent has a workstation in a top-down scene. Concierge dispatches visually.
5. **Why parallel execution?** Transport + hotel don't depend on each other. Itinerary + tour don't depend on each other. Parallel cuts time and looks impressive.
6. **Booking approach**: No payments. Agents return booking links (F1 official, Google Flights, Booking.com). Per-card Book buttons. Tickets = single-select, flights = multi-select, hotel = single-select, activities = multi-select.

---

## Architecture

```
Frontend (React / Next.js)
    |  WebSocket (SSE streaming)
API Layer (FastAPI)
    |
LangGraph Orchestrator
    +-- parse_input
    +-- ticket_agent (runs first)
    +-- transport_agent --+
    |                     +-- parallel
    +-- hotel_agent ------+
    +-- itinerary_agent --+
    |                     +-- parallel
    +-- tour_agent -------+
    +-- budget_agent
         |
    [over budget?] --yes--> increment_retry --> hotel_agent (loop, max 2)
         |
        END
```

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, LangGraph, LangChain
- **LLM**: Claude (primary), LangChain adapter for provider switching
- **Data**: SerpAPI (flights, hotels), TicketsData (tickets), LLM knowledge (tour, itinerary)
- **Frontend**: React prototype exists, migrate to Next.js
- **Streaming**: FastAPI WebSocket for real-time agent status

---

## State Schema

See `backend/state.py` for full typed definition. Key fields:
- User input: gp_name, gp_city, gp_date, origin, budget, stand_pref, extra_days, stops, special_requests
- Agent outputs: tickets[], transport[], hotel[], itinerary[], tour[], budget_summary
- Control: budget_ok, retry_count, messages[]

Only `messages` uses `Annotated[list, operator.add]` — it's the one field every agent writes to in parallel. All other list fields (tickets, transport, hotel, itinerary, tour) are single-writer and use LangGraph's default replace-semantics, so the budget retry loop correctly replaces their previous attempt instead of accumulating.

---

## Agent Specs

| Agent | Input | Output | Selection | Booking |
|-------|-------|--------|-----------|---------|
| ticket | gp, date, pref, budget | 3 grandstand options | Single | F1 official / StubHub |
| transport | origin, city, date, stops | Flights + local | Multi | Google Flights |
| hotel | city, dates, budget remaining | 2-3 stays | Single | Booking.com / Airbnb |
| itinerary | all prior results | Day-by-day schedule | Display only | — |
| tour | city, days, special requests | Sights + food | Multi | Attraction websites |
| budget | all outputs | Cost breakdown | Dynamic | — |

---

## Frontend — Paddock Club Theme

### Screens
1. **GP Select** — 24-station grid, track SVG outlines, per-station accent colors
2. **Welcome + Form** — Concierge greets, structured form (origin, budget, stand buttons, days slider, stops input, special requests textarea)
3. **Planning** — Top-down map with 5 zones, concierge walks between them, zones light up, race-lights progress bar
4. **Results** — Themed cards with per-item selection, dynamic budget bar, per-card Book buttons
5. **Chat** — Bottom input for adjustments anytime

### Characters (pixel-art SVG)
- Concierge: black suit, red bowtie
- Ticket: gold uniform
- Flight: pilot cap, navy
- Hotel: purple bellhop
- Schedule: orange, clipboard
- Explorer: teal adventure gear

---

## File Structure

```
f1-paddock-club/
+-- CLAUDE.md
+-- backend/
|   +-- main.py          # FastAPI + WebSocket
|   +-- graph.py         # LangGraph orchestrator
|   +-- state.py         # TravelPlanState types
|   +-- agents/__init__.py  # All agent nodes (mock Phase 1)
|   +-- tools/__init__.py   # Tool stubs (Phase 3+)
|   +-- requirements.txt
+-- frontend/
|   +-- prototype.jsx    # Working Paddock Club prototype
+-- docs/
```

---

## Development Phases

1. **Phase 1 — Graph + mock data** — DONE. Graph runs, all agents return mock, CLI test works.
2. **Phase 2 — Real LLM calls** — NEXT. Replace itinerary + tour agents with Claude API. Cheapest to implement.
3. **Phase 3 — External data tools** — Add SerpAPI for flights/hotels, ticket search API.
4. **Phase 4 — Frontend migration** — Move prototype to Next.js, connect WebSocket to backend.
5. **Phase 5 — Polish + deploy** — Error handling, persistence, deploy.

---

## How to Run

```bash
cd backend
pip install -r requirements.txt
python graph.py              # CLI test
uvicorn main:app --reload    # API on :8000
```

---

## For Claude Code / Cowork

Read this file first. It contains all context from the original design conversation.

Priorities when working on this project:
1. Make existing code run without errors first
2. Follow phase order (2 -> 3 -> 4 -> 5)
3. Keep mock data as fallback when real APIs fail
4. Test each agent individually before full pipeline
5. The graph.py orchestrator is the core — start there
6. Parallel execution: multiple edges from one node = auto-parallel in LangGraph
7. Budget retry: conditional edge, if over budget go back to hotel with retry_count++
