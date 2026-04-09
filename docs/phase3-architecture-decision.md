# Phase 3 Architecture Decision — Multi-Agent with Supervisor Pattern

_This document captures the architecture discussion for Phase 3 (real external data tools + refinement capabilities). It represents the plan after a back-and-forth about tradeoffs. The project owner set the final direction; this file is the written-down version so the conversation can continue on the web interface._

---

## Context — why this decision matters now

Phase 1 delivered a static LangGraph DAG with 7 mock agents. Phase 2 plugged real LLM calls into two of them (`itinerary_agent`, `tour_agent`). Phase 3 needs to do three things at once:

1. Replace the remaining mock data sources (tickets, flights, hotels) with real ones
2. Enable **interactive refinement** — the user changing their mind after seeing the first plan ("only Marriott hotels", "give me direct flights", "swap day 3 for Lake Como")
3. Pick an architecture that survives the long-term vision

The temptation was to scope this as "replace mock data first, worry about refinement later". The decision was to **reject that scoping**: the data layer and the interaction model are coupled (the handlers we write for data today become the tools the specialist agents call tomorrow), so we design for both from day one.

---

## The three positions we aligned on

### 1. Use existing open-source tools. Don't write our own scrapers.

**Agreed, no pushback.**

The realistic tool landscape for this project:

| Purpose | Tool | Cost |
|---|---|---|
| Flights + hotels structured data | **SerpAPI** (Google Flights engine, Google Hotels engine) | Free 100 searches/month, key already being applied for |
| Scrape F1 official ticket pages behind Cloudflare / JS | **Firecrawl** — managed service that handles anti-bot, returns LLM-ready markdown | Free 500 pages/month |
| General web search for tour/attraction info or unknown locations | **Tavily** or **DuckDuckGo** | Tavily: free 1000 queries/month; DuckDuckGo: completely free, no key |
| F1 ticket data (no public API exists) | **Firecrawl** (primary) → DuckDuckGo (fallback) → mock. Results cached with dynamic TTL based on distance-to-race. | Firecrawl free 500/month; DuckDuckGo free |

**Our job is to write _handlers_, not scrapers.** Each file under `backend/tools/` is a thin wrapper that:

- Calls the appropriate external service
- Normalizes the response into our state shapes (`TicketOption`, `TransportLeg`, `HotelOption`)
- Handles failures by raising or returning empty, so agents can fall back to mock
- Takes **rich parameters** (brand, max_price, stars, stops, near, excluded_ids, etc.) so refinement calls have something to work with

Total code expected: 200–300 lines across the tool files. No maintained crawler network.

**OpenClaw postscript (for the record):** OpenClaw and similar tools (browser-use, Skyvern) are L3 browser automation — they drive a real Chromium via CDP with an LLM deciding where to click. They _are_ technically scrapers, just very sophisticated ones that handle Cloudflare, JS, and multi-step flows. For our use case they're overkill: Firecrawl gives us "scraping as a service" without the infra burden, and that's enough.

### 2. LangGraph Supervisor pattern for multi-agent collaboration.

**Agreed on pattern. Partial pushback on scope — start with 2–3 specialists, not all 7 at once.**

#### Why supervisor pattern is the right call

- The project's stated identity is "multi-agent travel assistant". A single ReAct agent with 20 tools internally would undermine that identity.
- Our existing 7 logical roles (ticket, transport, hotel, itinerary, tour, budget, concierge) are a natural fit for specialization — each has its own domain knowledge, its own prompts, its own decision tradeoffs.
- User refinement input is genuinely open-ended ("I hate both hotels", "only Marriott", "swap day 3 for Como", "tickets too expensive, cut a day"). A supervisor reasoning about intent and delegating to the right specialist is cleaner than one generalist agent juggling all tools.
- LangGraph natively supports this pattern (either with `langgraph-supervisor` prebuilt helper or by hand with `StateGraph` + routing).
- Each specialist can be tested in isolation with its own prompt-tuning loop, without affecting the others.

#### Why I'm pushing back on scope

- Building 7 specialist agents + 1 supervisor _at once_ means 8 prompt-tuning exercises before anything works end-to-end. That's a recipe for a 3-week "nothing works" valley.
- Each specialist call adds latency (supervisor → specialist → supervisor aggregate) and cost (3× LLM calls per interaction minimum). We should validate the pattern with a small subset first, then expand.
- The refinement use cases cluster around a few hot spots. By expected frequency, users will want to change: hotels (most), flights, budget, then itinerary, tour, tickets. That's a natural ordering for rolling out specialists.

#### Proposed specialist rollout order

1. **Hotel Specialist** — most refinement requests hit hotels (brand, area, price range)
2. **Transport Specialist** — second most common (stops, time of day, class)
3. **Budget Specialist** — needed to reason about tradeoffs when the other two change; acts as the "rules enforcer" for every update
4. _(Later)_ Itinerary Specialist, Tour Specialist, Ticket Specialist as demand shows up

### 3. Think big (architecturally), ship small (implementation).

**Agreed on architecture, pushback on pace.**

**Think big** means:
- Design the two-lane architecture from day one (see the diagram below)
- Tool signatures are rich enough from the first commit that future specialists don't need to change them
- State schema supports the refinement flow without breaking the initial-planning flow
- Supervisor prompt has placeholders for intents we haven't implemented yet

**Ship small** means:
- Lane 1 (initial planning) keeps its current LangGraph. We don't rewrite what works.
- Lane 2 (supervisor + specialists) starts with 1 supervisor + 2-3 specialists, proven end-to-end, then grows.
- One tool file at a time, one specialist at a time. Each commit ships something testable on its own.
- Mock fallbacks stay in place permanently — they're not a bug, they're how we stay demoable when external APIs hiccup.

---

## The Phase 3 architecture we're going with

### Two lanes, one state, shared tools

```
                        ┌─────────────────────────┐
                        │     TravelPlanState      │
                        │  (single shared state)   │
                        └────────────┬────────────┘
                                     │
             ┌───────────────────────┼──────────────────────────┐
             ▼                                                   ▼
┌────────────────────────────┐                    ┌────────────────────────────┐
│   LANE 1: Initial planning │                    │   LANE 2: Refinement loop   │
│                            │                    │                             │
│   (existing LangGraph)     │                    │   Supervisor Agent           │
│   parse_input              │                    │       │                     │
│     → ticket_agent         │                    │       ├─ Hotel Specialist    │
│     → (transport ∥ hotel)  │                    │       ├─ Transport Specialist│
│     → (itinerary ∥ tour)   │                    │       ├─ Budget Specialist   │
│     → budget_agent         │                    │       └─ (more over time)    │
│                            │                    │                             │
│   Runs once on first       │                    │   Runs on every chat        │
│   request. Fast, parallel, │                    │   message after the first   │
│   deterministic.           │                    │   plan exists.              │
└──────────────┬─────────────┘                    └──────────────┬──────────────┘
               │                                                 │
               └────────────────────┬────────────────────────────┘
                                    ▼
                    ┌────────────────────────────┐
                    │   Shared tools layer       │
                    │                            │
                    │   search_flights (SerpAPI) │
                    │   search_hotels  (SerpAPI) │
                    │   search_tickets (JSON +   │
                    │     Firecrawl + DuckDuckGo │
                    │     fallback chain)        │
                    │   search_web (Tavily /     │
                    │     DuckDuckGo)            │
                    │   recompute_budget         │
                    └────────────────────────────┘
```

### Lane 1 behaviour

Unchanged from Phase 2 conceptually, plus:
- `ticket_agent` / `transport_agent` / `hotel_agent` get their data from the new tools layer instead of returning mock literals
- Mock data stays as fallback when tools fail (consistent with Phase 2 pattern)

### Lane 2 behaviour

New in Phase 3. A LangGraph supervisor graph:

- Supervisor LLM receives the user's chat message + a compact summary of current state
- Decides which specialist(s) to invoke (or whether it can answer directly without delegating)
- Specialists are themselves small ReAct agents with a narrow tool subset:
  - **Hotel Specialist**: tools = `[search_hotels, recompute_budget]`
  - **Transport Specialist**: tools = `[search_flights, recompute_budget]`
  - **Budget Specialist**: tools = `[recompute_budget, suggest_tradeoffs]`
- Each specialist returns an update proposal (what changes to state they suggest)
- Supervisor applies the update, runs `recompute_budget` as a guard, sends a reply down the `/ws` WebSocket

### Tools layer (the concrete file structure)

```
backend/tools/
├── __init__.py
├── data/
│   └── .cache/                 # disk-backed query cache (gitignored)
├── search_flights.py           # SerpAPI wrapper, returns TransportLeg[]
├── search_hotels.py            # SerpAPI wrapper, rich params (brand, stars, max_price, near, excluded_ids)
├── search_tickets.py           # JSON lookup → Firecrawl → DuckDuckGo cascade
├── search_web.py               # Tavily/DuckDuckGo wrapper for general info
└── recompute.py                # pure-function helpers: recompute_budget, validate_plan
```

Every tool function is independent of Lane 1 vs Lane 2 — both lanes call the same functions.

---

## Phased rollout inside Phase 3

Each step is small enough to commit independently. Any step can be paused without breaking what shipped before it.

1. **Phase 3.0 — Tools skeleton.** Write the tool files in mock mode (real signatures, mock return values — same data as the current agents). No external API keys required yet. Lane 1 agents refactored to call the tools. CLI stays green.

2. **Phase 3.1 — Cache layer.** Build `backend/tools/_cache.py` disk-backed cache decorator with callable TTL support. Apply `@cached(ttl=...)` to every tool function. Verify cache HIT/MISS behaviour with mock data. TTLs: flights 3h, hotels 3h, tickets dynamic (3h–1d by distance-to-race), web 1d.

3. **Phase 3.2 — SerpAPI integration.** Once the key is ready, `search_flights` and `search_hotels` call SerpAPI for real. Keep mock fallback in place. Verify with a few live scenarios (same Singapore / Monaco / Italian test cases from Phase 2).

4. **Phase 3.3 — Firecrawl integration for ticket fallback.** `search_tickets` cascade completed. Verify that an un-curated GP (say, Miami) returns reasonable data from the Firecrawl path.

5. **Phase 3.4 — Supervisor agent skeleton.** Start the Lane 2 graph. Implement supervisor prompt + routing logic, even if it only delegates to one specialist at first.

6. **Phase 3.5 — Hotel Specialist.** First specialist end-to-end. Test with "only Marriott", "not one of these, different options", "somewhere near the circuit under €400/night". Validate the refinement loop actually works.

7. **Phase 3.6 — Transport + Budget Specialists.** Second and third specialists. Test cross-cutting refinements ("direct flight only, stay within budget, I'll cut activities if needed").

8. **Phase 3.7 — `/ws` chat routing.** First message → Lane 1. Subsequent messages → Lane 2. Plumb the messages through so the frontend sees a coherent conversation.

Beyond Phase 3.7, add more specialists on demand (itinerary, tour, ticket) when the frontend shows we actually need them.

---

## Open questions for you (when you come back)

1. **Firecrawl free tier is 500 pages/month.** For ticket fallback only, that's way more than we need. Agreed to use it?
2. **Supervisor prompt language: English or bilingual (中英)?** The user-facing chat might be in Chinese sometimes. Should the supervisor be prompted to match the user's language, or always reply in English?
3. **How aggressive should Lane 2 be about re-running Lane 1?** If the user says "start over with a different GP", should the supervisor clear state and kick off Lane 1 again, or should the supervisor be read-only and only allow targeted updates? My default would be: supervisor can trigger a full Lane 1 re-run, but only when it detects a truly fresh-start intent.
4. **Per-GP ticket JSON ownership.** I can seed it with 5-6 GPs from public data (Monzanet, tickets.formula1.com, F1 Experiences). Do you want to review the seed before we use it, or trust the draft and correct what's wrong later?
5. **Security baseline timing.** Phase 2.5 security was explicitly deferred to deployment. But once Lane 2 is wired to `/ws` and specialists can spend tokens on every message, an open `/ws` + agentic tools = easy abuse vector. **Suggestion:** slip Phase 2.5 in between Phase 3.6 and Phase 3.7 (before the chat routing goes live). Acceptable?
6. **Model choice for supervisor vs specialists.** A smart supervisor (Claude Sonnet 4.5 / GPT-4o) is worth it for routing decisions. Specialists can go cheaper (gpt-4o-mini). Agreed, or do you want one model across the board?

---

## What I can do next while you rest / tomorrow

### Safe to do without your input

- **(a)** Draft the skeleton of `backend/tools/search_flights.py`, `search_hotels.py`, `search_tickets.py` in mock mode, so Lane 1 compiles against the new structure without any real API key
- **(b)** ~~Create ticket JSON~~ DONE — replaced by `_cache.py` disk cache. No manual data curation needed.
- **(c)** Sketch the supervisor + Hotel Specialist code as a separate file not yet wired into `main.py`, so you can review the shape before it goes live
- **(d)** Run another Phase 2 stability test on a different GP (say, Las Vegas) to make sure the recent bug fix holds across more scenarios
- **(e)** Update `CLAUDE.md` Phase description to reflect the two-lane architecture decision

### Need your input before doing

- Applying real SerpAPI / Firecrawl keys (waiting on you to decide which providers)
- Seeding the full ticket JSON with actual 2026 prices (you might want to review source sites first)
- Touching `main.py` to route WebSocket messages between Lane 1 and Lane 2 (architectural change)
- Phase 2.5 security work (you explicitly deferred it, but open question #5 above proposes slipping it in)

---

## Pushback summary, in one table

| Topic | Your position | My position | Landed on |
|---|---|---|---|
| Use existing tools vs write our own | "Use existing, handlers only" | Same | **Agreed** |
| F1 ticket data quality | "Must be accurate, otherwise meaningless" | "Tools as primary source + disk cache, no manual data files" | **Agreed. Dropped the JSON curation approach entirely. Firecrawl → DuckDuckGo → mock cascade, results cached with dynamic TTL (3h–1d based on distance-to-race).** |
| Multi-agent collaboration via supervisor | "Yes, think big" | "Yes on pattern, 2-3 specialists first not 7" | **Agreed, rollout order proposed above** |
| Agents must think for themselves | "Yes, it's the point" | "Yes, ReAct loop + rich tools = real autonomy within scope" | **Agreed** |
| Implementation pace | "Think big" | "Think big in design, ship small in code" | **Agreed, 8 micro-phases proposed** |
| Open-source tools — should you search them? | "Is there a list or do I search?" | "I'll give you the list" | **Listed: SerpAPI, Firecrawl, Tavily, DuckDuckGo, browser-use, Crawl4AI, MCP servers** |

---

_Written down during a break so we can continue from the web interface. The plan is committed to git; read when rested, poke holes in it, come back with edits to any section. If you want to strike any of the "safe to do without your input" items from the pre-approved list, just say so in the next session._
