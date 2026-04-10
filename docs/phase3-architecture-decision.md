# Phase 3 Architecture Decision — Multi-Agent with Supervisor Pattern

_This document captures the architecture discussion for Phase 3 (real external data tools + refinement capabilities). It represents the plan after a back-and-forth about tradeoffs. The project owner set the final direction; this file is the written-down version so the conversation can continue on the web interface._

_Last updated: Phase 3.3 complete. Sections marked **[DONE]** reflect what was actually built; sections marked **[PLAN]** are the forward-looking design still in progress._

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
| Flights + hotels structured data | **SerpAPI** (Google Flights engine, Google Hotels engine, Google Maps engine) | Free 100 searches/month |
| Scrape F1 official ticket pages behind Cloudflare / JS | **Firecrawl** — managed service that handles anti-bot, returns LLM-ready markdown | Free 500 pages/month |
| General web search for tour/attraction info or unknown locations | **Tavily** or **DuckDuckGo** | Tavily: free 1000 queries/month; DuckDuckGo: completely free, no key |
| F1 ticket data (no public API exists) | **Firecrawl** (primary) → Google Search (fallback) → LLM extraction → mock. Results cached with dynamic TTL based on distance-to-race. | Firecrawl free 500/month |

**Our job is to write _handlers_, not scrapers.** Each file under `backend/tools/` is a thin wrapper that:

- Calls the appropriate external service
- Normalizes the response into our state shapes (`TicketOption`, `TransportLeg`, `HotelOption`)
- Handles failures by raising or returning empty, so agents can fall back to mock
- Takes **rich parameters** (brand, max_price, stars, stops, near, excluded_ids, etc.) so refinement calls have something to work with

**Note on Bing:** Bing was evaluated as a second source for both flights and hotels (via SerpAPI's Bing engine). After three separate tests it was found to be low quality for our use case: it returned locale-dependent noise (flight simulator results, Chinese social media pages) and failed to understand the purchase intent of queries like "flights NYC to Monza October 2026". The decision was made to not use Bing for any tool. Google Search is used instead as the second source where a second source is needed, because its organic snippets are cleaner and more intent-aligned than Bing's for travel queries.

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
                    │   search_flights           │
                    │     (google_flights +      │
                    │      google_search)        │
                    │   search_hotels            │
                    │     (google_hotels +       │
                    │      google_maps)          │
                    │   search_tickets           │
                    │     (firecrawl +           │
                    │      google_search →       │
                    │      LLM extraction)       │
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
├── __init__.py             # re-exports all public functions
├── .cache/                 # disk-backed query cache (gitignored)
├── _cache.py               # @cached(ttl=...) decorator (stdlib only, no deps)
├── _parallel.py            # query_parallel() + DegradationReport
├── _date_util.py           # normalize_date(), compute_checkout()
├── search_flights.py       # google_flights + google_search (parallel via ThreadPoolExecutor)
├── search_hotels.py        # google_hotels + google_maps (parallel via ThreadPoolExecutor)
├── search_tickets.py       # firecrawl + google_search → LLM extraction
├── search_web.py           # Tavily → DuckDuckGo (general tour/attraction queries)
└── recompute.py            # recompute_budget (pure function, handles real + mock data)
```

Every tool function is independent of Lane 1 vs Lane 2 — both lanes call the same functions.

---

## What was actually built (Phase 3.0–3.3)

### `_cache.py`

Disk-backed cache decorator. Key design choices:
- Zero external dependencies (stdlib: `hashlib`, `json`, `pathlib`, `time`)
- One JSON file per tool function in `.cache/` — human-inspectable, tool-deletable
- Cache key = MD5 of serialized `(args, kwargs)` with `sort_keys=True` — same logical call always hits the same key regardless of dict ordering
- Atomic writes via `Path.write_text()` — safe enough for single-process FastAPI
- `ttl` can be a number (fixed) or a callable that receives the same args as the wrapped function (dynamic, used by `search_tickets`)
- `clear_cache(name=None)` utility for manual invalidation during dev/testing

### `_parallel.py`

`query_parallel(sources, timeout)` fires all source callables simultaneously using `ThreadPoolExecutor` + `as_completed`. Design notes:
- `ThreadPoolExecutor` not `ProcessPoolExecutor`: workload is IO-bound (HTTP to SerpAPI), threads release the GIL on IO, processes would add startup cost for zero gain
- `as_completed` not `map`: results processed as they arrive, so a fast source (0.5s) isn't blocked by a slow one (2s)
- Returns `(merged_results, DegradationReport)` so the caller has both "what data do I have" and "should I warn the user" in one shot
- Per-result `_source` and `_degraded` fields allow per-card UI degradation markers rather than blanket page warnings

### `_date_util.py`

`normalize_date(str)` → ISO `YYYY-MM-DD`. Handles all common date string formats a user might type or that might come from state. `compute_checkout(checkin, nights)` for hotel date math. Normalization lives here at the tool-layer boundary (system boundary principle) rather than scattered across agents.

### `search_flights.py`

3-layer fallback:
1. **Parallel real sources** (if `SERPAPI_API_KEY` set): `google_flights` + `google_search` via `query_parallel`. Google Flights returns structured airline/price/duration data. Google Search returns organic snippets with price ranges as cross-references.
2. **LLM estimation** (if parallel fails): uses `with_structured_output(FlightEstimate)` to generate contextual route-specific estimates. Results tagged `_degraded=True`.
3. **Raise** — agent falls back to mock.

Returns `(list[dict], degradation_summary_str)` so agents can embed the summary in user-facing status messages.

Includes `_CITY_TO_IATA` mapping for all 24 F1 host cities and major departure hubs. SerpAPI's google_flights engine requires IATA codes; users type city names.

### `search_hotels.py`

Same 3-layer pattern as flights:
1. **Parallel**: `google_hotels` + `google_maps`. Google Hotels gives booking-oriented data (prices, availability). Google Maps gives location-oriented data (ratings, addresses, real reviews) — useful when Google Hotels can't find results for small cities, since Maps always has local business data.
2. **LLM estimation**: `with_structured_output(HotelEstimate)` with real property names.
3. **Raise** → agent mock.

Rich filtering parameters: `brand`, `stars`, `max_price`, `near`, `excluded_ids` — designed for refinement use from day one.

### `search_tickets.py`

Different pattern from flights/hotels because there is no structured "google_tickets" engine. Uses a retrieve-then-extract (light RAG) approach:

1. **Parallel text gathering**: `firecrawl` (scrapes official ticket page → markdown) + `google_search` (price snippets). Both sources return raw text, not structured data.
2. **LLM extraction**: combined text fed to `_extract_with_llm()` which calls `with_structured_output(TicketOptionList)`. Fallback within this step: if `with_structured_output` fails (some LLM proxies don't relay the parsed field), a second attempt asks for raw JSON and parses it manually.
3. **LLM estimation** (no real data available): falls back to training knowledge to produce circuit-specific grandstand names and realistic EUR prices.
4. **Raise** → agent mock.

Dynamic TTL via `_ticket_ttl()`: 3h when race is within 60 days, 1d otherwise (ticket prices change less when the race is far out). TTL callable receives the same args as the wrapped function.

Known official ticket URLs are seeded for 6 GPs (`_TICKET_URLS`). All others fall back to `tickets.formula1.com`.

### `recompute.py`

`recompute_budget(state)` updated for real API data. Mock data had fixed-shape arrays; real API data has mixed result types (structured results + INFO supplementary links with `price=0`). The function now:
- Filters out `tag="INFO"` items and zero-price items before summing
- Picks cheapest OUT + cheapest RET flight (not sum-all)
- Picks cheapest hotel and multiplies by trip nights (with fallback logic when the API returns per-night pricing with `nights=1`)

### `search_web.py`

Skeleton implemented with correct signature and fallback chain (Tavily → DuckDuckGo). Inner functions stubbed; wiring deferred to Phase 3.2+ when tour_agent is refactored to use real web data.

---

## Phased rollout inside Phase 3

Each step is small enough to commit independently. Any step can be paused without breaking what shipped before it.

1. **Phase 3.0 — Tools skeleton.** [DONE] Tool files written with real signatures. Lane 1 agents refactored to call the tools layer. CLI stays green. Cache decorator built and applied.

2. **Phase 3.1 — Cache layer.** [DONE] `_cache.py` disk-backed cache with fixed and callable TTL. `_parallel.py` `ThreadPoolExecutor`-based parallel query framework with `DegradationReport`. Applied to all tool functions. `_date_util.py` date normalization utility. Cache HIT/MISS behaviour verified with mock data.

3. **Phase 3.2 — SerpAPI integration.** [DONE] `search_flights` calls `google_flights + google_search` in parallel. `search_hotels` calls `google_hotels + google_maps` in parallel. Both have LLM estimation fallback. Bing was evaluated and rejected (3 tests, consistently low quality: locale confusion, intent misunderstanding). `recompute_budget` updated to handle real API response shapes.

4. **Phase 3.3 — Firecrawl integration for ticket fallback.** [DONE] `search_tickets` cascade completed: `firecrawl + google_search` parallel text gathering → LLM extraction (with raw JSON fallback for proxy-incompatible providers) → LLM estimation → raise. Dynamic TTL implemented. Known official ticket URLs seeded for 6 GPs.

5. **Phase 3.4 — Supervisor agent skeleton.** [PLAN] Start the Lane 2 graph. Implement supervisor prompt + routing logic, even if it only delegates to one specialist at first.

6. **Phase 3.5 — Hotel Specialist.** [PLAN] First specialist end-to-end. Test with "only Marriott", "not one of these, different options", "somewhere near the circuit under €400/night". Validate the refinement loop actually works.

7. **Phase 3.6 — Transport + Budget Specialists.** [PLAN] Second and third specialists. Test cross-cutting refinements ("direct flight only, stay within budget, I'll cut activities if needed").

8. **Phase 3.7 — `/ws` chat routing.** [PLAN] First message → Lane 1. Subsequent messages → Lane 2. Plumb the messages through so the frontend sees a coherent conversation.

Beyond Phase 3.7, add more specialists on demand (itinerary, tour, ticket) when the frontend shows we actually need them.

---

## Open questions for you (when you come back)

1. ~~**Firecrawl free tier is 500 pages/month.**~~ **RESOLVED — yes, using it.** Firecrawl is the primary source for `search_tickets`. For ticket fallback only, 500 pages/month is more than enough. The dynamic TTL (3h near race, 1d far out) and disk cache further reduce actual scrape calls.

2. **Supervisor prompt language: English or bilingual (中英)?** The user-facing chat might be in Chinese sometimes. Should the supervisor be prompted to match the user's language, or always reply in English?

3. **How aggressive should Lane 2 be about re-running Lane 1?** If the user says "start over with a different GP", should the supervisor clear state and kick off Lane 1 again, or should the supervisor be read-only and only allow targeted updates? My default would be: supervisor can trigger a full Lane 1 re-run, but only when it detects a truly fresh-start intent.

4. ~~**Per-GP ticket JSON ownership.**~~ **RESOLVED — no manual JSON curation.** The hand-curated JSON approach was dropped entirely. Firecrawl scrapes the official page at query time and results are cached with dynamic TTL. No maintenance burden. `_TICKET_URLS` in `search_tickets.py` is a lightweight lookup table (not a data file) that just maps GP names to known official URLs — this is the only "curation" needed, and it's a one-liner per GP.

5. **Security baseline timing.** Phase 2.5 security was explicitly deferred to deployment. But once Lane 2 is wired to `/ws` and specialists can spend tokens on every message, an open `/ws` + agentic tools = easy abuse vector. **Suggestion:** slip Phase 2.5 in between Phase 3.6 and Phase 3.7 (before the chat routing goes live). Acceptable?

6. **Model choice for supervisor vs specialists.** A smart supervisor (Claude Sonnet 4.5 / GPT-4o) is worth it for routing decisions. Specialists can go cheaper (gpt-4o-mini). Agreed, or do you want one model across the board?

---

## What I can do next while you rest / tomorrow

### Safe to do without your input

- **(a)** ~~Draft the skeleton of `backend/tools/search_flights.py`, `search_hotels.py`, `search_tickets.py` in mock mode~~ — DONE in Phase 3.0–3.3.
- **(b)** ~~Create ticket JSON~~ — DROPPED. Replaced by `_cache.py` disk cache + Firecrawl. No manual data curation.
- **(c)** Sketch the supervisor + Hotel Specialist code as a separate file not yet wired into `main.py`, so you can review the shape before it goes live
- **(d)** Run another Phase 2 stability test on a different GP (say, Las Vegas) to make sure the recent bug fix holds across more scenarios
- **(e)** Update `CLAUDE.md` Phase description to reflect the two-lane architecture decision
- **(f)** Wire `search_web.py` inner functions (Tavily / DuckDuckGo stubs are present, just need the actual library calls)

### Need your input before doing

- Applying real SerpAPI / Firecrawl keys (SerpAPI key was applied; confirm Firecrawl key status)
- Touching `main.py` to route WebSocket messages between Lane 1 and Lane 2 (architectural change)
- Phase 2.5 security work (you explicitly deferred it, but open question #5 above proposes slipping it in)

---

## Pushback summary, in one table

| Topic | Your position | My position | Landed on |
|---|---|---|---|
| Use existing tools vs write our own | "Use existing, handlers only" | Same | **Agreed** |
| F1 ticket data quality | "Must be accurate, otherwise meaningless" | "Tools as primary source + disk cache, no manual data files" | **Agreed. Dropped the JSON curation approach entirely. Firecrawl → Google Search → LLM extraction cascade, results cached with dynamic TTL (3h–1d based on distance-to-race).** |
| Multi-agent collaboration via supervisor | "Yes, think big" | "Yes on pattern, 2-3 specialists first not 7" | **Agreed, rollout order proposed above** |
| Agents must think for themselves | "Yes, it's the point" | "Yes, ReAct loop + rich tools = real autonomy within scope" | **Agreed** |
| Implementation pace | "Think big" | "Think big in design, ship small in code" | **Agreed, 8 micro-phases proposed** |
| Open-source tools — should you search them? | "Is there a list or do I search?" | "I'll give you the list" | **Listed: SerpAPI, Firecrawl, Tavily, DuckDuckGo, browser-use, Crawl4AI, MCP servers** |
| Bing as second source | N/A | "Try it as second source for flights and hotels" | **Rejected after testing. 3 tests across flights and hotels: locale issues, intent misunderstanding. Google Search used instead.** |

---

_Written down during a break so we can continue from the web interface. The plan is committed to git; read when rested, poke holes in it, come back with edits to any section. If you want to strike any of the "safe to do without your input" items from the pre-approved list, just say so in the next session._
