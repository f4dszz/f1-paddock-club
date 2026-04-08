# F1 Paddock Club — Multi-Agent Travel Assistant

> A LangGraph-orchestrated multi-agent system that plans your entire Formula 1 Grand Prix trip — tickets, flights, hotel, day-by-day itinerary, sights & food, and a live budget — all in one parallel pipeline.

[简体中文](./README.zh-CN.md) · English

---

## Why this project

It started as a generic "I'm tired of manually triggering Claude / GPT / Gemini for each step of a task" problem. We picked an opinionated, demo-friendly use case — **planning a trip to a Formula 1 Grand Prix** — to showcase real multi-agent orchestration:

- One **concierge** parses your request.
- A **ticket agent** finds grandstand options.
- **Transport** and **hotel** agents run **in parallel**.
- **Itinerary** and **tour** agents run **in parallel** once travel basics are known.
- A **budget agent** totals everything and, if you're over budget, **loops back** to the hotel agent for cheaper options (max 2 retries).

The whole flow is a single [LangGraph](https://github.com/langchain-ai/langgraph) state machine — parallel fan-out, conditional edges, and a typed shared state.

---

## Architecture

```
              ┌─────────────┐
              │ parse_input │
              └──────┬──────┘
                     ▼
              ┌──────────────┐
              │ ticket_agent │
              └──────┬───────┘
            ┌────────┴────────┐
            ▼                 ▼
   ┌────────────────┐ ┌──────────────┐
   │ transport_agent│ │ hotel_agent  │   (parallel)
   └────────┬───────┘ └──────┬───────┘
            └────────┬────────┘
                     ▼
            ┌────────┴────────┐
            ▼                 ▼
   ┌────────────────┐ ┌──────────────┐
   │ itinerary_agent│ │ tour_agent   │   (parallel)
   └────────┬───────┘ └──────┬───────┘
            └────────┬────────┘
                     ▼
              ┌──────────────┐
              │ budget_agent │
              └──────┬───────┘
                     │
       ┌─────────────┴─────────────┐
       │ over budget? (max 2 retries)
       │   yes → increment_retry → hotel_agent
       │   no  → END
       └───────────────────────────┘
```

The shared `TravelPlanState` uses `Annotated[list, operator.add]` reducers so parallel agents can append to the same list without overwriting each other.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Orchestration | **LangGraph** (state machine + parallel fan-out + conditional edges) |
| LLM | **Claude** via `langchain-anthropic` |
| Backend | **Python 3.12+** + **FastAPI** + **Uvicorn** |
| Streaming | **WebSocket** (`/ws`) for real-time agent status |
| Frontend | React prototype (`frontend/prototype.jsx`) → Next.js (planned) |

---

## Current State (Phase 2 in progress)

| Phase | Status | What's in it |
|---|---|---|
| **1 — Graph + mock data** | ✅ Done | Full LangGraph wired up, all 7 agents return mock data, CLI test runs end-to-end, FastAPI `/plan` and `/ws` endpoints work. |
| **2 — Real LLM calls** | 🟡 In progress | `itinerary_agent` and `tour_agent` now call **Claude** via `langchain-anthropic` with `with_structured_output`. Mock data is the automatic fallback when `ANTHROPIC_API_KEY` is unset or the call fails. |
| **3 — External data tools** | ⏳ Planned | SerpAPI for flights/hotels, real ticket search. |
| **4 — Frontend migration** | ⏳ Planned | Move `prototype.jsx` to Next.js, wire to `/ws`. |
| **5 — Polish + deploy** | ⏳ Planned | Error handling, persistence, deploy. |

---

## Project Layout

```
f1-paddock-club/
├── CLAUDE.md                  # Full design context for Claude Code
├── README.md                  # ← you are here
├── README.zh-CN.md            # 简体中文版
├── backend/
│   ├── main.py                # FastAPI: POST /plan, WS /ws
│   ├── graph.py               # LangGraph orchestrator + CLI test
│   ├── state.py               # TravelPlanState (typed shared state)
│   ├── llm.py                 # Claude client wrapper (Phase 2)
│   ├── agents/__init__.py     # All 7 agent node functions
│   ├── tools/__init__.py      # External tool stubs (Phase 3+)
│   └── requirements.txt
└── frontend/
    └── prototype.jsx          # Paddock Club themed React prototype
```

---

## Getting Started

### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. (Optional) Set your Anthropic API key

Without a key, the LLM-powered agents (`itinerary`, `tour`) automatically fall back to mock data. With a key they call Claude.

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Windows cmd / git-bash
set ANTHROPIC_API_KEY=sk-ant-...
```

Optional: override the model (default is `claude-sonnet-4-5`).

```bash
export ANTHROPIC_MODEL=claude-sonnet-4-6
```

### 3. Run the CLI test

```bash
# from backend/
python graph.py
```

> **Windows note:** the trace contains unicode arrows (`↔`, `→`). If your console is `gbk` you'll get a `UnicodeEncodeError`. Run with `PYTHONIOENCODING=utf-8 python graph.py` or `chcp 65001` first.

You should see something like:

```
=== MESSAGES (execution trace) ===
  [concierge] Planning your Italian GP trip from New York...
  [ticket]    Found 3 ticket options for Italian GP
  [hotel]     Found 2 stays in Monza (5 nights)
  [transport] Found flights New York ↔ Monza
  [plan]      Created 5-day itinerary (Claude)
  [tour]      Curated 5 recommendations (Claude)
  [budget]    Total €2189 / €2500 — within budget ✓
```

The `(Claude)` / `(mock)` tag tells you whether the agent hit the real LLM or the fallback.

### 4. Run the API server

```bash
# from backend/
uvicorn main:app --reload
# → http://localhost:8000
```

#### POST `/plan`

```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "gp_name": "Italian GP",
    "gp_city": "Monza",
    "gp_date": "Sep 7",
    "origin": "New York",
    "budget": 2500,
    "stand_pref": "mid",
    "extra_days": 2,
    "stops": "Milan 2 days → Lake Como → Monza",
    "special_requests": "Wheelchair accessible hotel, vegetarian restaurants"
  }'
```

#### WebSocket `/ws`

Send the same JSON payload, receive a stream of `{type: "message", data: {...}}` frames as agents complete, then a final `{type: "result", data: {...}}` and `{type: "done"}`.

---

## Agents at a Glance

| Agent | Input | Output | Mock or LLM? |
|---|---|---|---|
| `parse_input` | user form | normalized state | deterministic |
| `ticket_agent` | gp, date, pref, budget | 3 grandstand options | mock (Phase 3 → real) |
| `transport_agent` | origin, city, date, stops | flights + local | mock (Phase 3 → SerpAPI) |
| `hotel_agent` | city, dates, budget left | 2–3 stays | mock (Phase 3 → SerpAPI) |
| `itinerary_agent` | all prior + special requests | day-by-day lines | **Claude** (Phase 2) |
| `tour_agent` | city, days, special requests | sights + food | **Claude** (Phase 2) |
| `budget_agent` | all outputs | cost breakdown + over/under | deterministic |

---

## Roadmap

- **Phase 3** — wire `tools/` to SerpAPI (flights, hotels) and a ticket search source; replace `ticket`/`transport`/`hotel` mocks.
- **Phase 4** — port the React prototype to Next.js, drive the planning view from `/ws` streaming.
- **Phase 5** — error handling, run persistence, deploy.

---

## License

TBD.
