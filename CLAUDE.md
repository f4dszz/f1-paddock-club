# F1 Paddock Club — Multi-Agent Travel Assistant

## Project Origin & Context

This project started from a conversation about multi-agent orchestration — how to coordinate multiple AI agents to complete complex tasks. The original problem was: "I use multiple AI products (Claude, OpenAI, Gemini) for different steps of a task, and manually triggering each one is exhausting."

After exploring several approaches (CLI wrapping, API adapters, frameworks), we landed on:
- **LangGraph** as the orchestration framework
- **Python + FastAPI** for the backend
- **React** for the frontend

The idea evolved from a generic code-refactoring orchestrator to an **F1 Grand Prix travel assistant** — a more compelling, demo-friendly, and portfolio-worthy project. The architecture is designed as an **event-based travel planning framework** where F1 is the first vertical — the same system could serve music festivals, sports events, or conferences with minimal code changes.

### Key Design Decisions

1. **Why F1?** More engaging than code-refactoring. Anyone can understand it. Strong visual identity. Natural multi-agent use case.
2. **Why LangGraph?** User knows Python/Java. LangGraph handles execution engine, parallel coordination, state management. Focus effort on agent logic, not infrastructure.
3. **Why structured form + chat?** Form handles fixed fields (origin, budget, dates, stand pref, stops, extra days). Chat handles special requests and adjustments via the supervisor agent.
4. **Why "Paddock Club" theme?** VIP experience metaphor. Dark theme + pixel-art characters. Each agent has a workstation in a top-down scene. Concierge dispatches visually.
5. **Why parallel execution?** Transport + hotel don't depend on each other. Itinerary + tour don't depend on each other. Parallel cuts time and looks impressive.
6. **Booking approach**: No payments. Agents return booking links (F1 official, Google Flights, Booking.com). Per-card Book buttons. Tickets = single-select, flights = multi-select, hotel = single-select, activities = multi-select.

---

## Architecture — Two-Lane Design

The system uses two lanes sharing one state and one tools layer:

```
                        ┌─────────────────────────┐
                        │     TravelPlanState      │
                        │  (single shared state)   │
                        └────────────┬────────────┘
                                     │
             ┌───────────────────────┼──────────────────────────┐
             ▼                                                   ▼
┌────────────────────────────┐                    ┌────────────────────────────┐
│   LANE 1: Initial planning │                    │   LANE 2: Refinement       │
│                            │                    │                            │
│   LangGraph DAG            │                    │   Supervisor Agent (ReAct) │
│   parse_input              │                    │     - search_hotels_tool   │
│     -> ticket_agent        │                    │     - search_flights_tool  │
│     -> (transport || hotel) │                    │     - search_tickets_tool  │
│     -> (itinerary || tour) │                    │     - recompute_budget_tool│
│     -> budget_agent        │                    │                            │
│     -> [retry if over]     │                    │   Makes targeted updates   │
│                            │                    │   only, not full replan    │
│   Runs once per new trip.  │                    │   Runs per chat message.   │
│   Fast, parallel, fixed.   │                    │   Flexible, agentic.       │
└──────────────┬─────────────┘                    └──────────────┬─────────────┘
               └────────────────────┬────────────────────────────┘
                                    ▼
                    ┌────────────────────────────┐
                    │   Shared Tools Layer       │
                    │                            │
                    │   search_flights (SerpAPI  │
                    │     google_flights +       │
                    │     google_search parallel)│
                    │   search_hotels  (SerpAPI  │
                    │     google_hotels +        │
                    │     google_maps parallel)  │
                    │   search_tickets (Firecrawl│
                    │     + google_search        │
                    │     parallel -> LLM        │
                    │     extraction -> mock)    │
                    │   search_web (Tavily/DDG)  │
                    │   recompute_budget (pure fn)│
                    │                            │
                    │   All @cached with TTL     │
                    │   Parallel multi-source    │
                    │   (3h flights/hotels,      │
                    │    dynamic for tickets,    │
                    │    1d for web search)      │
                    └────────────────────────────┘
```

**Lane 1** generates the initial plan via a fixed LangGraph DAG with parallel fan-out and budget retry. All 7 agent nodes follow the same pattern: try tools first, fall back to mock on any failure.

**Lane 2** handles user refinement ("only Marriott hotels", "direct flights", "swap day 3 for Como") via a ReAct supervisor agent. The supervisor decides which tool(s) to call — it does NOT re-run the entire pipeline.

Both lanes share the same `TravelPlanState` and the same tool functions.

Long-term vision: the supervisor may eventually replace Lane 1 for initial planning too (supervisor-only mode), once parallel tool calling and prompt reliability are validated. See `docs/phase3-architecture-decision.md` for the full reasoning.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, LangGraph, LangChain
- **LLM**: Pluggable via `LLM_PROVIDER` env var — OpenAI (default) or Anthropic. Supports any OpenAI-compatible proxy via `OPENAI_BASE_URL`.
- **Data tools**: SerpAPI — active, real data verified (flights + hotels); Firecrawl — active, real data verified (ticket page scraping); Tavily/DuckDuckGo — **stubbed** (search_web.py skeleton only, not wired). All active tools disk-cached with TTL.
- **Frontend**: React prototype exists (`frontend/prototype.jsx`), planned migration to Next.js.
- **Streaming**: FastAPI WebSocket for real-time agent status.
- **Logging**: File-based (`backend/logs/backend.log`), `LOG_LEVEL` env var controllable.

---

## State Schema

See `backend/state.py` for full typed definition. Key fields:
- User input: gp_name, gp_city, gp_date, origin, budget, stand_pref, extra_days, stops, special_requests
- Agent outputs: tickets[], transport[], hotel[], itinerary[], tour[], budget_summary
- Control: budget_ok, retry_count, messages[]

Only `messages` uses `Annotated[list, operator.add]` — it's the one field every agent writes to in parallel. All other list fields (tickets, transport, hotel, itinerary, tour) are single-writer and use LangGraph's default replace-semantics, so the budget retry loop correctly replaces their previous attempt instead of accumulating.

---

## Agent Specs

| Agent | Input | Output | Data Source (Phase 3) | Selection |
|-------|-------|--------|-----------------------|-----------|
| ticket | gp, date, pref, budget | 3 grandstand options | Firecrawl -> google_search -> LLM extraction -> LLM estimate -> mock | Single |
| transport | origin, city, date, stops | Flights + local | SerpAPI Google Flights -> LLM estimate -> mock | Multi |
| hotel | city, dates, budget remaining | 2-3 stays | SerpAPI Google Hotels -> LLM estimate -> mock | Single |
| itinerary | all prior results | Day-by-day schedule | LLM (with_structured_output) -> mock | Display only |
| tour | city, days, special requests | Sights + food | LLM (with_structured_output) -> mock | Multi |
| budget | all outputs | Cost breakdown | Pure computation (recompute.py) | Dynamic |

All agents follow the same internal pattern: tools-first -> mock-fallback -> source-tag in log message.

---

## Frontend — Paddock Club Theme

### Screens
1. **GP Select** — 24-station grid, track SVG outlines, per-station accent colors
2. **Welcome + Form** — Concierge greets, structured form (origin, budget, stand buttons, days slider, stops input, special requests textarea)
3. **Planning** — Top-down map with 5 zones, concierge walks between them, zones light up, race-lights progress bar
4. **Results** — Themed cards with per-item selection, dynamic budget bar, per-card Book buttons
5. **Chat** — Bottom input for adjustments anytime (routed to Lane 2 supervisor)

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
├── CLAUDE.md                       # This file — full project context
├── README.md                       # English README
├── README.zh-CN.md                 # Chinese README
├── .gitignore
├── backend/
│   ├── main.py                     # FastAPI: POST /plan, WS /ws (dual-lane session routing)
│   ├── graph.py                    # Lane 1: LangGraph orchestrator + CLI test
│   ├── refine.py                   # Lane 2: Supervisor agent (dual-mode: planning + refinement)
│   ├── state.py                    # TravelPlanState (typed shared state)
│   ├── llm.py                      # Pluggable LLM client (OpenAI/Anthropic + .env)
│   ├── logging_config.py           # File logger setup (logs/)
│   ├── agents/__init__.py          # 7 agent node functions (tools-first + mock-fallback)
│   ├── tools/
│   │   ├── __init__.py             # Re-exports all tool functions
│   │   ├── _cache.py               # Disk-backed @cached decorator (TTL, callable TTL)
│   │   ├── _currency.py             # EUR/USD/CNY conversion for budget computation
│   │   ├── _date_util.py           # Date normalization (any format → ISO)
│   │   ├── _trip_dates.py          # Trip date computation (gp_date + extra_days → all boundaries)
│   │   ├── _parallel.py            # run_parallel() helper for multi-source fan-out
│   │   ├── search_flights.py       # SerpAPI google_flights + google_search parallel (@cached 3h)
│   │   ├── search_hotels.py        # SerpAPI google_hotels + google_maps parallel (@cached 3h)
│   │   ├── search_tickets.py       # Firecrawl + google_search parallel -> LLM extraction (@cached dynamic)
│   │   ├── search_web.py           # Tavily -> DuckDuckGo general search — STUBBED (@cached 1d)
│   │   ├── recompute.py            # Budget recomputation (pure function, shared by both lanes)
│   │   └── .cache/                 # Disk cache files (gitignored)
│   ├── logs/                       # Log files (gitignored)
│   ├── .env                        # Local secrets (gitignored)
│   ├── .env.example                # Documents all supported env vars
│   └── requirements.txt
├── frontend/
│   └── prototype.jsx               # Paddock Club themed React prototype
└── docs/
    ├── phase3-architecture-decision.md  # Full architecture discussion + rollout plan
    └── architecture-lessons.md          # 18 design lessons (teaching reference)
```

---

## Development Phases

1. **Phase 1 — Graph + mock data** — DONE. LangGraph wired, all agents return mock, CLI test works, FastAPI endpoints work.
2. **Phase 2 — Real LLM calls** — DONE. itinerary + tour agents call real LLM (OpenAI/Anthropic) via `with_structured_output`. Pluggable provider. .env support. File logging. Tested with Singapore/Monaco/Italian GP. Bug fix: retry list accumulation.
3. **Phase 3 — External data tools + supervisor** — DONE.
   - 3.0 ✅ Tools skeleton (search_flights, search_hotels, search_tickets, search_web, recompute)
   - 3.1 ✅ Disk-backed cache decorator with callable TTL
   - 3.2 ✅ SerpAPI integration — search_flights (google_flights + google_search parallel), search_hotels (google_hotels + google_maps parallel). Real data verified: JFK→MXP $365, Monza hotels $116–235/night.
   - 3.3 ✅ Firecrawl integration for tickets — search_tickets (firecrawl + google_search parallel → LLM extraction). Real data verified: Monza Lateral Parabolic €594.
   - 3.4 ✅ Supervisor agent skeleton (refine.py)
   - 3.5 ✅ Supervisor dual-mode (planning from natural language + refinement with state mutation). State mutation via post-loop ToolMessage scanning. Budget auto-recompute.
   - 3.6 ✅ Supervisor hardening — multi-currency budget (EUR/USD/CNY via _currency.py), trip date computation (_trip_dates.py for outbound/return/checkin/checkout), state-aware tool factory (closure-based auto-fill prevents supervisor from asking for known info). Specialists deferred (see note below).
   - 3.7 ✅ /ws WebSocket dual-lane routing — type=plan → Lane 1, type=chat → Lane 2, session state per connection, backward-compat shim for raw TripRequest.
   - Note: search_web.py (Tavily/DuckDuckGo) remains stubbed — tour_agent uses LLM only. Not blocking.
4. **Phase 4 — Frontend migration** — Move prototype to Next.js, connect WebSocket to backend. Chat input box as first-class entry point alongside GP grid + form.
5. **Phase 5 — Polish + deploy** — Security baseline, error handling, persistence, deploy.

### Specialist vs Supervisor — Open Design Question (Phase 3.6)

The original plan called for specialist sub-agents (Hotel Specialist, Transport Specialist, Budget Specialist) under the supervisor. After completing Phase 3.5, an honest reassessment:

**The supervisor already does what specialists were supposed to do.** When a user says "I want Marriott hotels near the circuit", the supervisor directly calls `search_hotels_tool(brand="Marriott", near="circuit")` — it doesn't need a Hotel Specialist as an intermediary. The tools' rich parameter signatures (brand, stars, max_price, near, excluded_ids) already give the supervisor enough fine-grained control.

**When specialists WOULD be needed:**
- When the supervisor's tool list exceeds ~15-20 tools (context overload → worse routing decisions)
- When a domain needs multi-step reasoning that's too complex for a single prompt (e.g., "find the cheapest multi-stop route through 3 European GPs with stopover visa considerations")
- When different domains need different LLM models/temperatures (routing = smart model, data extraction = cheap model)

**Current decision:** Phase 3.6 focused on supervisor hardening instead of adding specialists.

What was actually implemented in 3.6:
- Multi-currency budget (EUR/USD/CNY) — _currency.py + recompute.py
- Trip date computation — _trip_dates.py (outbound/return/checkin/checkout from gp_date)
- State-aware tool factory — supervisor auto-fills parameters from existing plan (code-level guardrail)
- Round-trip flight handling — ROUNDTRIP tag + recompute support

What was NOT implemented (deferred):
- Multi-turn conversation memory (supervisor creates fresh agent per call, no chat history across turns)
- Budget tradeoff suggestions (supervisor reports over-budget but doesn't proactively suggest swaps)
- "Change GP entirely" / "start over" via chat intent (only via type=plan on /ws)
- Specialists deferred to Phase 5 when validated by real usage patterns

This is a reversible decision. The architecture supports adding these later.

---

## How to Run

```bash
cd backend
pip install -r requirements.txt
# requirements.txt includes: google-search-results (SerpAPI), firecrawl-py, and all other deps

# Configure LLM provider (copy and edit)
cp .env.example .env
# At minimum set: OPENAI_API_KEY=... (or ANTHROPIC_API_KEY with LLM_PROVIDER=anthropic)
# For real flight/hotel data:  SERPAPI_API_KEY=...
# For real ticket data:        FIRECRAWL_API_KEY=...
# Optional general search:     TAVILY_API_KEY=...
# Without these keys the agents fall back to mock data gracefully.

# CLI test (Lane 1)
PYTHONIOENCODING=utf-8 python graph.py

# Interactive REPL (Lane 1 + Lane 2)
PYTHONIOENCODING=utf-8 python -i graph.py
>>> from refine import refine_plan
>>> state, reply = refine_plan(result, "only Marriott hotels near the circuit")
>>> print(reply)

# API server
uvicorn main:app --reload    # API on :8000
```

---

## For Claude Code / Cowork

Read this file first. It contains all context from the original design conversation plus all subsequent architecture decisions.

Priorities when working on this project:
1. Make existing code run without errors first
2. Follow phase order — check the phase list above for current status
3. Keep mock data as permanent fallback when real APIs fail (graceful degradation)
4. All 7 agents follow the same internal pattern: tools-first -> mock-fallback -> source-tag
5. The tools layer is shared between Lane 1 (graph.py) and Lane 2 (refine.py)
6. Think big in architecture, ship small in code — one tool/specialist at a time
7. See `docs/phase3-architecture-decision.md` for the full two-lane architecture reasoning, open questions, and phased rollout plan
8. User prefers honest pushback over agreement. Frame decisions by product impact.
9. No `Co-Authored-By` or AI attribution in commit messages.
