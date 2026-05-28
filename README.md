# F1 Paddock Club — Multi-Agent Travel Assistant

> A LangGraph-orchestrated multi-agent system that plans your entire Formula 1 Grand Prix trip — tickets, flights, hotel, day-by-day itinerary, sights & food, and a live budget — all in one parallel pipeline.

[简体中文](./README.zh-CN.md) · English

![F1 Paddock Club demo](docs/demo.gif)

<!-- TODO: replace docs/demo.gif with a 5-second screen recording of:
     GP card click → calendar load → plan generated → first refine.
     Record at 1280x720, 8fps, ~3MB. -->

---

## Why this project

It started as a generic "I'm tired of manually triggering Claude / GPT / Gemini for each step of a task" problem. Then I was thinking like: why can't we just design our own agents and let them collaborate?
So I picked an opinionated, demo-friendly use case, also came from my personal interests — **planning a trip to a Formula 1 Grand Prix** — to showcase real multi-agent orchestration:

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
| Backend | **Python 3.12** (the version tested in CI; 3.13+ works but emits a Pydantic V1 deprecation warning from LangChain — not blocking) + **FastAPI** + **Uvicorn** |
| Streaming | **WebSocket** (`/ws`) for real-time agent status |
| Frontend | Vite + React prototype. `frontend/prototype.jsx` now orchestrates state/WebSocket flow, with UI split into `frontend/components/` and pure display rules in `frontend/domain/`. Next.js remains a future option, not a current dependency. |

---

## Current State (Phase 4 functional build in progress)

| Phase | Status | What's in it |
|---|---|---|
| **1 — Graph + mock data** | ✅ Done | Full LangGraph wired up, all 7 agents return mock data, CLI test runs end-to-end, FastAPI endpoints work. |
| **2 — Real LLM calls** | ✅ Done | `itinerary_agent` and `tour_agent` call real LLM via `with_structured_output`. Provider selectable (OpenAI/Anthropic). Mock fallback when no key. |
| **3 — External data + supervisor** | ✅ Done | SerpAPI (flights/hotels), Firecrawl (tickets), supervisor agent for chat refinement, `/ws` dual-lane routing, currency conversion (EUR/USD/CNY), trip date computation. See details below. |
| **4 — Frontend + trust layer** | 🟡 In progress | Hookup, hardening, currency/date controls, selected quote previews, structured constraints, itinerary/tour card edits, ticket/flight/hotel explainability, and the first frontend/backend file split are done. Next: strict E2E automation, iCal export, and deployment hardening. |
| **5 — Polish + deploy** | ⏳ Planned | Security baseline, persistence, production deployment, PWA/mobile polish. |

### Phase 3 — what was built

- **Tools layer** (`backend/tools/`): `search_flights` (SerpAPI google_flights + google_search), `search_hotels` (SerpAPI google_hotels + google_maps), `search_tickets` (Firecrawl scraping + google_search + LLM extraction). All with 3-layer fallback: real APIs → LLM estimation → agent mock. Disk-cached with TTL.
- **Supervisor agent** (`backend/refine.py`): Dual-mode — planning from natural language + refinement of existing plans. State-aware tool factory auto-fills parameters from existing plan context. Editing helpers and hard-constraint reconciliation now live in separate modules so `refine.py` stays focused on orchestration.
- **`/ws` dual-lane routing**: `type=plan` → Lane 1 (full parallel DAG), `type=chat` → Lane 2 (supervisor refinement). Session state maintained per connection.
- **Budget accuracy**: Multi-currency conversion (EUR/USD/CNY), correct trip date computation (outbound/return/checkin/checkout), round-trip flight handling.

---

## Project Layout

```
f1-paddock-club/
├── AGENTS.md / CLAUDE.md      # Synced, compact project agent guidelines
├── README.md                  # ← you are here
├── README.zh-CN.md            # 简体中文版
├── backend/
│   ├── main.py                # FastAPI: POST /plan, WS /ws
│   ├── graph.py               # LangGraph orchestrator + CLI test
│   ├── state.py               # TravelPlanState (typed shared state)
│   ├── llm.py                 # Pluggable LLM client wrapper (Phase 2)
│   ├── agents/                # Lane 1 agent nodes split by domain; __init__.py is a public facade
│   ├── refine.py              # Lane 2 supervisor orchestration
│   ├── refine_editing.py      # Itinerary/tour card update helpers
│   ├── refine_constraints.py  # Hard constraint reconciler after tool output
│   ├── refine_reply.py        # Deterministic post-state reply summarizer
│   ├── refine_state.py        # Tool-result → state apply + failure tracking
│   ├── _session.py            # WebSocket session manager (chat memory + plan state layered)
│   ├── tools/                 # External data tools (SerpAPI, Firecrawl, cache, currency, dates)
│   ├── logging_config.py      # File logger setup (writes to logs/)
│   ├── requirements.txt
│   └── .env.example           # Documents all supported env vars
├── frontend/
│   ├── prototype.jsx          # React app orchestrator (state, WebSocket, page composition)
│   ├── components/            # Render-only UI components
│   ├── domain/                # Pure display/transform/date/constraint rules
│   ├── src/main.jsx           # Vite entry point
│   ├── index.html             # HTML shell
│   ├── vite.config.js         # Vite dev server config (port 3000)
│   └── package.json           # React + Vite deps
├── skills/                    # Shared project skill source files; install locally when needed
├── .githooks/                 # Tracked hook templates; install with scripts/install-hooks.sh
├── scripts/                   # Local lifecycle, verification, hooks, and E2E helpers
└── start.sh                   # Launch both backend + frontend
```

---

## Getting Started

### Quick start (both backend + frontend)

```bash
# One-time setup
cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && cp .env.example .env
# Optional: edit .env for real LLM/provider calls.
# Leaving keys empty still lets the first plan render estimate/mock cards.
cd ../frontend && npm ci
cd ..

# Launch both services
./start.sh
# Backend: http://localhost:8001
# Frontend: http://localhost:3000 (Vite may open a browser tab automatically depending on environment)
```

### Recommended: two-terminal dev workflow (macOS / Linux / Windows Git Bash)

`start.sh` is the one-terminal launcher and cleans up child processes on exit. For day-to-day development with separate logs, use the dedicated scripts in `scripts/`:

```bash
# Terminal 1: backend on :8001
./scripts/dev-backend.sh

# Terminal 2: frontend on :3000 (strictPort, no drift)
./scripts/dev-frontend.sh

# When done — kill any leftover processes on 3000/3001/8000/8001
./scripts/dev-stop.sh

# Check what's currently listening
./scripts/dev-status.sh

# Run the local verification bundle before pushing
./scripts/check-local.sh
```

### Local automation

```bash
# Check AGENTS.md / CLAUDE.md are byte-for-byte synced
./scripts/check-agent-doc-sync.sh

# Install tracked git hook templates into this clone
./scripts/install-hooks.sh

# Run backend + frontend + browser smoke, then clean up services
./scripts/e2e-local.sh

# Run only the Playwright tests against an already-running frontend
cd frontend && npm run e2e

```

### E2E test layout

`frontend/e2e/` has four spec files in two lanes:

- **Default lane** (`smoke.spec.js`, `explain.spec.js`) — no LLM keys. Runs locally with `./scripts/e2e-local.sh`. Covers initial planning, selection/quote, links, a date-input regression, and the "Why this card?" explainability panel content.
- **Stub-gated lane** (`refine.spec.js`, `quote_incomplete.spec.js`) — env-gated by `E2E_INCLUDE_REFINE=1` via `playwright.config.js` `testIgnore`, requires `LLM_STUB_MODE=1` against the backend. Covers refinement (direct-only constraint, English Explore-card replacement) and the unpriced/incomplete quote amber path (`backend/agents/tickets.py` appends a price=0 ticket under `APP_ENV=test + LLM_STUB_MODE=1`). The refine stub in `backend/refine.py` calls `_apply_constraint_filters` / `apply_line_update` directly — no real LLM, no `$` per run.

**CI gate** (`.github/workflows/ci.yml`): the `e2e` job runs the full lane (`E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 PYTHON_BIN=python ./scripts/e2e-local.sh`); the `bundled-check-local` job runs `./scripts/check-local.sh` to gate the same bundled contract contributors are told to trust. Both run on every push/PR; Playwright artifacts upload on failure.

```bash
./scripts/e2e-local.sh                                       # default lane (smoke + explain)
E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 ./scripts/e2e-local.sh  # full deterministic lane (4 specs)
```

The stub is gated by `APP_ENV=test + LLM_STUB_MODE=1`; production with empty keys still returns the honest `LLM not configured`.

Repo `skills/*` are shared source/reference files and belong in git. Installed local skills under `${CODEX_HOME:-~/.codex}/skills`, `.git/hooks/*`, and other machine state do not belong in git; this repo intentionally does not automate writing to `${CODEX_HOME:-~/.codex}`.

### Health check (verify both services are reachable)

```bash
# Backend direct
curl http://127.0.0.1:8001/api/calendar

# Backend through Vite proxy (must also return 200)
curl http://localhost:3000/api/calendar
```

If the second one fails but the first succeeds, the frontend is running but its proxy can't reach the backend — restart frontend with `dev-stop.sh` then `dev-frontend.sh`.

Frontend prerequisites:
- Node.js `^20.19.0 || >=22.12.0` (required by the installed Vite 8 toolchain)
- npm `11+`
- If you're on Windows PowerShell and `npm` is blocked by execution policy, use `npm.cmd` instead of `npm`

Local frontend verification commands:

```bash
cd frontend
npm ci
npm run build
npm audit --audit-level=moderate
```

On Windows PowerShell, the equivalent commands are:

```powershell
cd frontend
& 'C:\Program Files\nodejs\npm.cmd' ci
& 'C:\Program Files\nodejs\npm.cmd' run build
& 'C:\Program Files\nodejs\npm.cmd' audit --audit-level=moderate
```

### Manual setup

#### 1. Install backend dependencies

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

#### 2. (Optional) Configure an LLM provider

The browser can show an initial trip plan without external API keys. If you leave provider/LLM keys empty, the first "Plan trip" flow still renders five visible card groups, but they are placeholders/estimates, not destination-verified recommendations:

- Ticket cards — generic F1 ticket examples, not live GP availability.
- Transport cards — route/date estimates based on the selected destination.
- Hotel cards — generic stay placeholders; some labels use the selected city.
- Schedule / day-by-day plan — generic schedule text using the selected city and race date.
- Explore / sights and food — GP-aware sample recommendations via `_TOUR_MOCK_BY_GP` in `backend/agents/tour.py`. Italian GP and Singapore GP have region-specific entries; other GPs fall back to the Italian list.

The budget panel is computed from those visible cards. This no-key mode is useful for local smoke testing and demos of the first planning screen, but the data is not live availability and should not be treated as a real trip recommendation.

After the plan appears, the chat box for refinement requires a configured LLM. Without one, the frontend surfaces an error and existing cards stay unchanged. (A deterministic refinement stub gated by `APP_ENV=test + LLM_STUB_MODE=1` exists for E2E tests only — not a user-facing fallback.)

With a key, the LLM-powered parts of the app call a real model. The recommended way to configure this is a `.env` file:

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

#### 2b. Optional deployment/demo access gate

Local dev defaults to no token gate. In deployed environments, set a shared demo token and explicit origins so public traffic cannot burn API/LLM quota:

```ini
APP_ENV=production
ALLOWED_ORIGINS=https://your-frontend.example
DEMO_ACCESS_TOKEN=change-me
MAX_CONCURRENT_PLANS=5
HTTP_RATE_LIMIT_PER_MINUTE=60
WS_CONNECT_LIMIT_PER_MINUTE=20
```

For a split-origin frontend, copy `frontend/.env.example` to `frontend/.env.local` and set:

```ini
VITE_BACKEND_URL=https://your-backend.example
VITE_WS_URL=wss://your-backend.example/ws
VITE_DEMO_TOKEN=change-me
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
  [plan]      Created 5-day itinerary (OpenAI)
  [tour]      Curated 5 recommendations (OpenAI)
  [budget]    Total €2189 / €2500 — within budget ✓
```

The `(OpenAI)` / `(Anthropic)` / `(mock)` tag tells you which provider answered, or that the agent fell back to mock data.

### 4. Run the API server

```bash
# from backend/
uvicorn main:app --reload
# → http://localhost:8001
```

#### POST `/plan`

```bash
curl -X POST http://localhost:8001/plan \
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

**Preview the current card selection without mutating the plan:**
```json
{"type": "quote", "data": {"quote_id": 1, "selections": {"ticket": [0], "transport": [1], "hotel": [2]}}}
```

Server responses:
- `{"type": "message", "data": {"agent": "...", "text": "..."}}` — status updates
- `{"type": "result", "data": {...}}` — full state snapshot (after each lane completes)
- `{"type": "quote", "data": {"quote_id": 1, "budget_summary": {...}}}` — selected-card budget preview
- `{"type": "reply", "data": "..."}` — supervisor's text reply (Lane 2 only)
- `{"type": "error", "data": "..."}` — invalid input or recoverable request failure
- `{"type": "done"}` — current request finished

> **Backward compat:** raw TripRequest JSON (without `{type, data}` envelope) is auto-detected and routed to Lane 1.

> **Note:** the browser's first planning flow can render placeholder Ticket, Transport, Hotel, Schedule, and Explore cards without keys. Some placeholders are generic rather than GP-specific. Follow-up chat changes require an LLM key; without one, the existing cards stay unchanged and the UI shows an error.

#### 5. Run the frontend

```bash
cd frontend
npm ci        # clean install from package-lock.json
npm run dev   # → http://localhost:3000
```

Requirements:
- Node.js `^20.19.0 || >=22.12.0`
- npm `11+`
- Frontend dependencies installed in `frontend/node_modules` via `npm ci`

Windows PowerShell note:
- If `npm` fails with `npm.ps1 cannot be loaded because running scripts is disabled`, run `npm.cmd` instead.
- Example: `& 'C:\Program Files\nodejs\npm.cmd' run dev`

The frontend loads the GP calendar from `/api/calendar`, connects to `/ws` for live planning, and renders real agent results. Past GPs are dimmed in the selection grid. Result-card selections trigger `type=quote` previews, so the budget changes from a baseline estimate to "Your selected total" without mutating the saved plan. If a selected item has no price, the quote turns amber and stays incomplete instead of pretending the trip is within budget. Active constraints (direct flights, hotel brands, dietary, accessibility, budget strategy) appear as chips, and itinerary/tour chat edits can persist back to the Schedule and Explore cards. Ticket, flight, and hotel cards can also show a "Why this card?" panel with the reasons, matched constraints, source path, and trade-offs behind the recommendation. The source path is an explanation of the configured data ladder inferred from the final card source; it is not a full runtime attempt log.

### Logs

Every run writes a structured audit trail to `backend/logs/backend_YYYY-MM-DD.log` (UTF-8, append mode, one file per startup date). Each agent's status messages, LLM call boundaries, and any exceptions land there with timestamps and the originating module name. The pretty console output from the CLI test is untouched — file logs are additive, not a replacement.

```bash
tail -f backend/logs/backend_$(date +%F).log   # follow today's log
```

Bump verbosity with `LOG_LEVEL=DEBUG` in your `.env` (or `export`) to see LLM init details and prompts-related debug lines. `backend/logs/` is gitignored.

---

## Components at a Glance

The word "agent" is used loosely in the AI community, so here's the honest breakdown of what each component actually does. Only the Lane 2 supervisor is an agent in the strict sense — it picks its own next action, decides which tool to call, and reacts to tool output. Everything else in Lane 1 is a workflow node running on a fixed graph edge.

### Lane 1 — workflow nodes (fixed DAG)

Each node runs in a predetermined position in the LangGraph pipeline. There is no self-directed planning; the graph decides the order.

| Node | Input | Output | Data source |
|---|---|---|---|
| `parse_input` | user form | normalized state | deterministic |
| `ticket_agent` | gp, date, pref, budget | 3 grandstand options | **Firecrawl + LLM extraction** → LLM estimate → mock |
| `transport_agent` | origin, city, date, stops | flights + local | **SerpAPI google_flights** → LLM estimate → mock |
| `hotel_agent` | city, dates, budget left | 2–3 stays | **SerpAPI google_hotels + maps** → LLM estimate → mock |
| `itinerary_agent` | all prior + special requests | day-by-day lines | **LLM** (OpenAI / Anthropic, single structured call) → generic mock |
| `tour_agent` | city, days, special requests | sights + food | **LLM** (OpenAI / Anthropic, single structured call) → generic mock |
| `budget_agent` | all outputs | cost breakdown + over/under | deterministic |

The three "tool-backed" nodes (`ticket_agent`, `transport_agent`, `hotel_agent`) wrap the tools layer with a three-tier fallback (real API → LLM estimate → mock). The two "LLM workflow" nodes (`itinerary_agent`, `tour_agent`) make a single structured-output call to an LLM and fall back to a generic mock. The source folder is still `backend/agents/` because the names are entrenched in the LangGraph wiring; renaming is deferred until it buys more than it costs.

Ticket, transport, and hotel nodes attach a deterministic `_rationale` object to each user-visible card. This powers the "Why this card?" panel and stays deliberately simple: it explains visible data such as price, distance, provider, active constraints, and trade-offs against sibling cards. Tour and itinerary rationale are not fully productionized yet because those cards are still text-first LLM outputs.

### Lane 2 — supervisor agent

| Component | Input | Output | Data source |
|---|---|---|---|
| `refine.refine_plan` | existing plan state + user chat | updated plan state + short grounded reply | ReAct agent (LangGraph) with dynamic tool selection |

The supervisor is a real agent: it reads the conversation, chooses whether and which of the search/update tools to invoke, reasons over tool output, and decides when to stop. Replies are post-processed into a deterministic summary of what actually persisted, so the agent can never silently invent budget numbers. Durable hard constraints are stored in `active_constraints`, separate from short rolling chat history.

### Tools / providers (shared layer)

| Tool | Backed by | Used by |
|---|---|---|
| `search_flights` | SerpAPI Google Flights + Google Search (parallel) | `transport_agent`, supervisor |
| `search_hotels` | SerpAPI Google Hotels + Google Maps (parallel) | `hotel_agent`, supervisor |
| `search_tickets` | Firecrawl + SerpAPI Google Search + LLM extraction | `ticket_agent`, supervisor |
| `search_web` | Tavily / DuckDuckGo (provider adapter; currently stubbed) | future: tour_agent, supervisor |
| `recompute_budget` | pure function over state + optional selections | `budget_agent`, supervisor, `type=quote` |

---

## Deploy from scratch (Vercel + Railway + Clerk + Sentry)

The enterprise-floor design (`docs/superpowers/specs/2026-05-27-enterprise-floor-design.md`) targets Vercel for the static frontend and Railway for the FastAPI + Postgres backend. After completing the steps below, `git push` to `main` triggers an automatic deploy on both platforms.

### 0. Prerequisites — register external services

You will need accounts on these. Free tiers cover a portfolio demo.

| Service | Free tier signals | Why |
|---|---|---|
| **Clerk** (https://dashboard.clerk.com) | 10k MAU | OAuth IdP — sign-in UI + JWT issuance |
| **Sentry** (https://sentry.io) | 5k errors/mo | Backend + frontend error tracking |
| **Railway** (https://railway.app) | $5/mo Hobby credit | FastAPI process + Postgres addon |
| **Vercel** (https://vercel.com) | Hobby plan | Static frontend on global CDN |
| OpenAI (already in repo) | pay-as-you-go | LLM calls |
| SerpAPI (optional) | 100 searches/mo | flight + hotel search |
| Firecrawl (optional) | 500 pages/mo | F1 ticket pages |

### 1. Provision Clerk

1. Create a new Application in the Clerk dashboard.
2. Enable Google, GitHub, and Email auth providers (configurable later).
3. From "API Keys", copy `CLERK_SECRET_KEY` (secret) and `VITE_CLERK_PUBLISHABLE_KEY` (public).
4. From "JWT Templates" (or the default JWT settings), note the **issuer URL** — it looks like `https://your-app.clerk.accounts.dev`. The JWKS URL is `<issuer>/.well-known/jwks.json`.

### 2. Provision Sentry

1. Create two projects: one Python (named `f1-paddock-backend`), one React (`f1-paddock-frontend`).
2. Copy each project's DSN. The DSN is a URL — both DSNs are public, but only the *frontend* one is intentionally exposed in the bundle.

### 3. Provision Railway

1. New Project → "Deploy from GitHub repo" → connect this repo.
2. Add the **Postgres** addon to the project. Railway auto-injects `DATABASE_URL` into the backend service environment.
3. Set the following backend env vars on the Railway service (Variables tab):
   - `APP_ENV=production`
   - `ALLOWED_ORIGINS=https://<your-vercel-domain>`  (set after step 4)
   - `OPENAI_API_KEY=sk-...`
   - `SERPAPI_API_KEY=...` (optional)
   - `FIRECRAWL_API_KEY=...` (optional)
   - `CLERK_SECRET_KEY=sk_test_...`
   - `CLERK_JWT_ISSUER=https://your-app.clerk.accounts.dev`
   - `CLERK_JWKS_URL=https://your-app.clerk.accounts.dev/.well-known/jwks.json`
   - `SENTRY_DSN_BACKEND=https://...@oXXXXX.ingest.sentry.io/YYYYY`
   - `REQUIRE_CLERK_AUTH=true`
4. Railway reads `railway.json` from the repo root — it runs `alembic upgrade head` on every build, then `uvicorn main:app`. The `/healthz` endpoint serves the platform liveness probe.

### 4. Provision Vercel

1. New Project → Import Git Repository → select this repo.
2. Framework Preset: **Other**. The `vercel.json` at repo root supplies the build + headers config; no framework preset is needed.
3. Set the following frontend env vars in Vercel Project Settings → Environment Variables:
   - `VITE_BACKEND_URL=https://<your-railway-backend>.up.railway.app`
   - `VITE_WS_URL=wss://<your-railway-backend>.up.railway.app/ws`
   - `VITE_CLERK_PUBLISHABLE_KEY=pk_test_...`
   - `VITE_SENTRY_DSN_FRONTEND=https://...@oXXXXX.ingest.sentry.io/YYYYY`
   - `VITE_APP_ENV=production`
4. (Optional) Enable Vercel Deployment Protection on the project for an extra "keep away the curious" layer over the sign-in screen.

### 5. Push to main

`git push origin main` triggers automatic builds on both platforms. The backend takes ~2 minutes; the frontend ~1 minute.

### 6. Verify

Run the **Deploy smoke** workflow from the GitHub Actions tab (`Actions → Deploy smoke → Run workflow`). It checks `/healthz`, `/readyz`, that `/api/calendar` is gated, and that the frontend bundle does not leak any secret strings.

Then open `https://<vercel-domain>` in a browser:

1. Clerk sign-in page appears.
2. Sign in with Google → planner UI loads.
3. Plan a trip end-to-end → click **SAVE** → reload page → **MY TRIPS** → click **Load** → the saved trip is restored from Postgres.

### 7. Rollback

Both Vercel and Railway expose per-revision rollback in their dashboards. After a rollback, re-run the **Deploy smoke** workflow and record the drill outcome in `CHANGELOG.md` under `[Unreleased]`.

## Roadmap

- **Phase 4 (in progress)** — 4.0 prototype.jsx connected to `/ws` (done). 4.1 frontend hardening (done). 4.2 currency selector + editable trip dates + grounded refine replies + opt-in debug trace (done). 4.3 selection-aware quotes + structured constraints + editable itinerary/tour cards (done). 4.4 ticket/flight/hotel explainability panel (done). 4.5 internal stabilization/file split (done). 4.6 deterministic E2E in CI — full 4-spec lane runs in CI (smoke + refine + unpriced/incomplete quote + explainability), bundled `check-local.sh` job, stub-backed refinement and unpriced ticket via `APP_ENV=test + LLM_STUB_MODE=1`, tool cache bypassed under `APP_ENV=test`, outbound egress monkeypatched in unit tests (done). 4.7 enterprise floor — Clerk OAuth, Postgres-backed saved trips, Sentry, /healthz + /readyz, CSP/HSTS, gitleaks, Vercel + Railway deploy config (done).
- **Phase 5** — error budgets, per-user quotas, audit log, custom domain, mobile/PWA polish.

---

## License

TBD.
