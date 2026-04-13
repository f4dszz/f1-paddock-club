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

The shared `TravelPlanState` uses `Annotated[list, operator.add]` on the `messages` field (the only field written by parallel agents). All other fields (`tickets`, `transport`, `hotel`, etc.) use LangGraph's default replace semantics — each is written by a single agent, so no merge conflicts.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Orchestration | **LangGraph** (state machine + parallel fan-out + conditional edges) |
| LLM | **Pluggable** — OpenAI (default) or Anthropic, switchable via `LLM_PROVIDER` env var. Also supports any OpenAI-compatible proxy via `OPENAI_BASE_URL`. |
| Backend | **Python 3.12+** + **FastAPI** + **Uvicorn** |
| Streaming | **WebSocket** (`/ws`) for real-time agent status |
| Frontend | React prototype (`frontend/prototype.jsx`) → Next.js (planned) |

---

## Current State (Phase 3 complete)

| Phase | Status | What's in it |
|---|---|---|
| **1 — Graph + mock data** | ✅ Done | Full LangGraph wired up, all 7 agents return mock data, CLI test runs end-to-end, FastAPI endpoints work. |
| **2 — Real LLM calls** | ✅ Done | `itinerary_agent` and `tour_agent` call real LLM via `with_structured_output`. Provider selectable (OpenAI/Anthropic). Mock fallback when no key. |
| **3 — External data + supervisor** | ✅ Done | SerpAPI (flights/hotels), Firecrawl (tickets), supervisor agent for chat refinement, `/ws` dual-lane routing, currency conversion (EUR/USD/CNY), trip date computation. See details below. |
| **4 — Frontend** | ⏳ Next | Connect `prototype.jsx` to `/ws`, then migrate to Next.js. |
| **5 — Polish + deploy** | ⏳ Planned | Security baseline, error handling, persistence, deploy. |

### Phase 3 — what was built

- **Tools layer** (`backend/tools/`): `search_flights` (SerpAPI google_flights + google_search), `search_hotels` (SerpAPI google_hotels + google_maps), `search_tickets` (Firecrawl scraping + google_search + LLM extraction). All with 3-layer fallback: real APIs → LLM estimation → agent mock. Disk-cached with TTL.
- **Supervisor agent** (`backend/refine.py`): Dual-mode — planning from natural language + refinement of existing plans. State-aware tool factory auto-fills parameters from existing plan context.
- **`/ws` dual-lane routing**: `type=plan` → Lane 1 (full parallel DAG), `type=chat` → Lane 2 (supervisor refinement). Session state maintained per connection.
- **Budget accuracy**: Multi-currency conversion (EUR/USD/CNY), correct trip date computation (outbound/return/checkin/checkout), round-trip flight handling.

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
│   ├── llm.py                 # Pluggable LLM client wrapper (Phase 2)
│   ├── agents/__init__.py     # All 7 agent node functions
│   ├── refine.py              # Lane 2: Supervisor agent (dual-mode planning + refinement)
│   ├── tools/                 # External data tools (SerpAPI, Firecrawl, cache, currency, dates)
│   ├── logging_config.py      # File logger setup (writes to logs/)
│   ├── requirements.txt
│   └── .env.example           # Documents all supported env vars
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

### 2. (Optional) Configure an LLM provider

Without an API key, the LLM-powered agents (`itinerary`, `tour`) automatically fall back to mock data. With a key they call a real model. The recommended way to configure this is a `.env` file:

```bash
cd backend
cp .env.example .env
# then edit .env and put your key in
```

The defaults work with **any OpenAI key**:

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini          # optional, this is the default
# OPENAI_BASE_URL=https://...       # optional, for OpenAI-compatible proxies
```

Want to use Claude instead? Switch the provider:

```ini
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-sonnet-4-5
# ANTHROPIC_BASE_URL=https://...    # optional, for Anthropic-compatible proxies
```

Want to use an OpenAI-compatible third-party provider (DeepSeek, Moonshot, GLM, Qwen, local vLLM, ...)? Keep `LLM_PROVIDER=openai` and point `OPENAI_BASE_URL` at the provider's endpoint:

```ini
LLM_PROVIDER=openai
OPENAI_API_KEY=<key from that provider>
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

> Prefer environment variables over a `.env` file? Just `export` the same names — `llm.py` reads both. The `.env` file is gitignored.

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
  [plan]      Created 5-day itinerary (OpenAI)
  [tour]      Curated 5 recommendations (OpenAI)
  [budget]    Total €2189 / €2500 — within budget ✓
```

The `(OpenAI)` / `(Anthropic)` / `(mock)` tag tells you which provider answered, or that the agent fell back to mock data.

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
    "gp_date": "Sep 6",
    "origin": "New York",
    "budget": 2500,
    "stand_pref": "mid",
    "extra_days": 2,
    "stops": "Milan 2 days → Lake Como → Monza",
    "special_requests": "Wheelchair accessible hotel, vegetarian restaurants"
  }'
```

#### WebSocket `/ws` — dual-lane session

The WebSocket supports multi-message sessions with two lanes:

**Start a new plan (Lane 1 — full parallel pipeline):**
```json
{"type": "plan", "data": {"gp_name": "Italian GP", "gp_city": "Monza", "gp_date": "Sep 6", "origin": "New York", "budget": 2500, "extra_days": 2}}
```

**Refine the plan (Lane 2 — supervisor agent):**
```json
{"type": "chat", "data": "I want Marriott hotels near the circuit"}
```

Server responses:
- `{"type": "message", "data": {"agent": "...", "text": "..."}}` — status updates
- `{"type": "result", "data": {...}}` — full state snapshot (after each lane completes)
- `{"type": "reply", "data": "..."}` — supervisor's text reply (Lane 2 only)
- `{"type": "done"}` — current request finished

> **Backward compat:** raw TripRequest JSON (without `{type, data}` envelope) is auto-detected and routed to Lane 1.

> **Note:** `type=chat` as the first message uses the supervisor's planning mode, which produces tickets/flights/hotels/budget but **not** itinerary or tour (3/5 sections). For a complete 5/5 plan, use `type=plan` first.

### Logs

Every run writes a structured audit trail to `backend/logs/backend.log` (UTF-8, append mode). Each agent's status messages, LLM call boundaries, and any exceptions land there with timestamps and the originating module name. The pretty console output from the CLI test is untouched — file logs are additive, not a replacement.

```bash
tail -f backend/logs/backend.log   # follow live
```

Bump verbosity with `LOG_LEVEL=DEBUG` in your `.env` (or `export`) to see LLM init details and prompts-related debug lines. `backend/logs/` is gitignored.

---

## Agents at a Glance

| Agent | Input | Output | Mock or LLM? |
|---|---|---|---|
| `parse_input` | user form | normalized state | deterministic |
| `ticket_agent` | gp, date, pref, budget | 3 grandstand options | **Firecrawl + LLM extraction** → LLM estimate → mock |
| `transport_agent` | origin, city, date, stops | flights + local | **SerpAPI google_flights** → LLM estimate → mock |
| `hotel_agent` | city, dates, budget left | 2–3 stays | **SerpAPI google_hotels + maps** → LLM estimate → mock |
| `itinerary_agent` | all prior + special requests | day-by-day lines | **LLM** (OpenAI / Anthropic) → mock |
| `tour_agent` | city, days, special requests | sights + food | **LLM** (OpenAI / Anthropic) → mock |
| `budget_agent` | all outputs | cost breakdown + over/under | deterministic |

---

## Roadmap

- **Phase 4 (next)** — connect `frontend/prototype.jsx` to `/ws`, then migrate to Next.js with real-time planning UI.
- **Phase 5** — security baseline, error handling, run persistence, deploy.

---

## License

TBD.
