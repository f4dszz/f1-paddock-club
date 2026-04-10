# Architecture Lessons — F1 Paddock Club

_A complete teaching reference for the design decisions behind this project. Written in the style of a senior AI agent architect teaching a junior engineer. Each lesson explains: what we did, why, what the alternatives were, and when you'd choose differently._

_This document is meant to be read after looking at the code. It doesn't replace reading the source — it explains the WHY that the source code can't convey._

---

## Table of Contents

1. [Project structure: why tools/ and agents/ are separate](#1-project-structure)
2. [The decorator pattern: @cached and why it saves you](#2-decorator-pattern)
3. [Callable TTL: when a config value should be a function](#3-callable-ttl)
4. [The cascade pattern: multi-source fallback](#4-cascade-pattern)
5. [Parallel multi-source: ThreadPoolExecutor, not multiprocessing](#5-parallel-multi-source)
6. [Degradation as first-class data, not a log side-effect](#6-degradation-reporting)
7. [Mock fallback is permanent, not temporary](#7-permanent-mock)
8. [Lazy imports inside try blocks](#8-lazy-imports)
9. [Raise, don't return empty: fail loudly, recover gracefully](#9-raise-dont-return-empty)
10. [Interface stability: why graph.py never changes](#10-interface-stability)
11. [Validate at system boundaries, not upstream](#11-boundary-validation)
12. [Search query quality: the pipeline's input bottleneck](#12-query-quality)
13. [When NOT to add a source: noise vs signal](#13-noise-vs-signal)
14. [Structured output with raw JSON fallback](#14-structured-output-fallback)
15. [Function signatures: design for future callers](#15-future-proof-signatures)
16. [DRY extraction: recompute_budget as shared logic](#16-dry-extraction)
17. [Two-lane architecture: fixed graph + agentic supervisor](#17-two-lane)
18. [Know when to stop optimizing](#18-stop-optimizing)

---

## 1. Project structure: why tools/ and agents/ are separate {#1-project-structure}

```
backend/
├── agents/    ← Decision layer: knows WHEN to do what
└── tools/     ← Execution layer: knows HOW to get data
```

**What we did**: Separated "decision logic" (agents — which run in what order, what to do on failure) from "data logic" (tools — how to call SerpAPI, how to parse the response).

**Why**: They evolve at different speeds and for different reasons.
- `agents/hotel_agent` changes when we alter the **business flow** (e.g., "on budget retry, ask for cheaper hotels")
- `tools/search_hotels` changes when the **external API** changes (e.g., SerpAPI updates its response format)

If they lived in the same function, changing the API parsing would risk breaking the business flow, and vice versa.

**The real test**: Lane 2 (the supervisor agent) also needs to call `search_hotels`. If the search logic was inside `hotel_agent`, the supervisor would have to import an "agent function" to use as a "tool" — semantically wrong and creates a dependency from Lane 2 → Lane 1. With the split, both lanes import from `tools/` independently.

**When you'd do it differently**: If you have exactly 1 agent and 1 data source and no plans for a second consumer, keeping them together is fine. Split when you see a second caller emerging.

---

## 2. The decorator pattern: @cached {#2-decorator-pattern}

```python
@cached(ttl=3600)
def search_flights(...):
    # Just the API call logic. No caching code here.
```

**What we did**: Built a `@cached` decorator in `_cache.py` that wraps any function with disk-backed caching. The function itself doesn't know it's being cached.

**Why**: Five tool functions all need the same caching behavior (check disk → call API → store result → return). Without a decorator, you'd write the cache logic 5 times:

```python
# WITHOUT decorator — repeated in every function:
def search_flights(...):
    key = hash(args)
    if key in cache and not expired:
        return cache[key]
    result = actual_api_call()
    cache[key] = result
    return result
```

With a decorator, the caching logic exists in ONE place (`_cache.py`). Change the cache format → change one file → all 5 functions updated.

**When you'd do it differently**: If each function needed radically different caching behavior (different storage backends, different key strategies), a decorator might be too rigid. But ours all use the same pattern: disk JSON + TTL expiration + MD5 key.

---

## 3. Callable TTL: when a config value should be a function {#3-callable-ttl}

```python
@cached(ttl=_ticket_ttl)  # _ticket_ttl is a FUNCTION, not a number

def _ticket_ttl(gp_name, year, **kwargs):
    days_until = (race_date - today()).days
    if days_until < 60: return 3 * 3600    # 3 hours
    return 24 * 3600                        # 1 day
```

**What we did**: Made the `@cached` decorator accept either a fixed number OR a callable that computes the TTL from the function's arguments.

**Why**: Ticket data volatility depends on context (how close is the race?). A fixed TTL is wrong in both directions: too long near race day (stale data), too short far from it (wasted API calls).

**The principle**: When the correct value of a configuration depends on runtime context, promote it from a value to a function. This lets the same decorator handle both "flights = always 3h" and "tickets = depends on race date".

**When you'd do it differently**: If your cache backend natively supports per-key TTL (like Redis `SETEX`), you could set TTL at write time instead of computing it at decoration time. But for our JSON file cache, computing at decoration time is the simplest path.

---

## 4. The cascade pattern: multi-source fallback {#4-cascade-pattern}

```
search_tickets internal flow:

  Parallel sources (Firecrawl + Google Search)
      → success → merge text → LLM extraction → return
      → ALL FAIL →
          LLM estimation (training data)
              → success → return (marked _degraded=True)
              → FAIL →
                  raise RuntimeError → agent catches → mock fallback
```

**What we did**: Each tool function tries multiple data sources in priority order. Each layer is progressively lower quality but higher reliability.

**Why**: No single data source is 100% reliable. SerpAPI has outages. Firecrawl hits Cloudflare. LLMs hallucinate. By layering sources, the system degrades gracefully instead of crashing.

**Key design**: Each layer either returns data or raises/returns empty. The next layer only runs if the previous one failed. This is a **linear chain**, not a tree — simple to reason about, simple to debug (just read the log: "firecrawl failed, trying google_search, google_search failed, trying llm_estimate...").

**Comparison with parallel**: We use BOTH patterns together. Parallel runs multiple sources simultaneously (Firecrawl + Google Search at the same time). Cascade runs fallback layers sequentially (parallel layer → LLM estimation → mock). Parallel is for complementary sources at the same quality tier. Cascade is for different quality tiers.

---

## 5. Parallel multi-source: ThreadPoolExecutor {#5-parallel-multi-source}

```python
with ThreadPoolExecutor(max_workers=len(sources)) as pool:
    future_to_name = {pool.submit(fn): name for name, fn in sources.items()}
    for future in as_completed(future_to_name, timeout=20):
        # process results as they arrive
```

**What we did**: Built `_parallel.py` with `query_parallel()` that fires multiple API calls simultaneously using `ThreadPoolExecutor`.

**Why ThreadPoolExecutor, not ProcessPoolExecutor?**

Our workload is **IO-bound** (waiting for HTTP responses). During an HTTP wait, Python threads release the GIL (Global Interpreter Lock), allowing other threads to run. So 3 threads waiting for 3 different APIs = true parallelism for IO.

`ProcessPoolExecutor` creates separate OS processes — useful for **CPU-bound** work (math, image processing) where the GIL would block true parallel computation. For API calls, processes add ~100ms startup overhead and inter-process serialization cost for zero benefit.

**Why `as_completed`, not `map`?**

`ThreadPoolExecutor.map()` returns results in submission order. `as_completed()` returns results in **completion order** — whoever finishes first gets processed first. If Google Maps responds in 0.5s but Google Hotels takes 3s, we start processing Maps data immediately. For user-facing latency, this matters.

**Why not asyncio?**

Asyncio is theoretically even more efficient (no thread overhead, cooperative scheduling). But SerpAPI's Python SDK is synchronous. Using asyncio would require switching to `httpx.AsyncClient` and calling the REST API directly instead of using the SDK. More code, more maintenance, same result. ThreadPoolExecutor gives us parallelism with zero SDK changes.

---

## 6. Degradation as first-class data {#6-degradation-reporting}

```python
# Each result carries its own source + degradation flag:
{"name": "Hotel XYZ", "price": 120, "_source": "google_hotels", "_degraded": False}
{"name": "Hotel ABC", "price": 135, "_source": "llm_estimate",  "_degraded": True}
```

```python
# query_parallel returns a DegradationReport alongside results:
results, report = query_parallel(sources)
if report.any_failed:
    msg = f"sources: {report.succeeded} | FAILED: {report.failed}"
```

**What we did**: Every result item carries `_source` and `_degraded` fields. The parallel framework returns a `DegradationReport` summarizing which sources succeeded/failed.

**Why per-item, not per-request?** A single search might partially degrade: Google Hotels returned 5 results (good), but Google Maps failed (bad). Per-request flagging would say "this entire search is degraded" — misleading. Per-item flagging lets the frontend show a warning icon only on the items from the failed source.

**Why a structured DegradationReport, not just log lines?** Because three different consumers need the information:
1. **Log file** → for debugging (already covered by logger.info/warning)
2. **User-facing message** → "Found 5 hotels (google_hotels + google_maps)" or "Found 3 hotels (google_hotels only — google_maps failed)"
3. **Supervisor agent** → needs to know source quality to make decisions ("should I retry with different parameters?")

A log line only serves consumer #1. A structured report serves all three.

---

## 7. Mock fallback is permanent {#7-permanent-mock}

**What we did**: Every agent has a `_xxx_mock()` function that returns hardcoded data. Even with real APIs wired, the mock stays.

**Why**: Mock serves four roles that never go away:
1. **API outage resilience**: SerpAPI down? System still works (degraded, but functional)
2. **Quota exhaustion**: Free tier used up? Mock keeps the demo running
3. **Development mode**: No API key? `python graph.py` still runs end-to-end
4. **Testing determinism**: Automated tests can run without external dependencies

**This is called Graceful Degradation**: the system never fully breaks; it downgrades service quality instead. Airlines call it "operating in degraded mode" — the plane still flies, just without autopilot.

---

## 8. Lazy imports inside try blocks {#8-lazy-imports}

```python
def ticket_agent(state):
    try:
        from tools.search_tickets import search_tickets  # ← inside try
        tickets, summary = search_tickets(...)
    except:
        tickets = _ticket_mock(state)
```

**What we did**: Import tool modules inside the function body, inside a try block, not at the top of the file.

**Why**: Two reasons.

**Reason 1: Import might fail.** If `tools/search_tickets.py` imports `firecrawl` and that package isn't installed, the import itself throws `ImportError`. At the top of the file, this would crash the entire `agents/__init__.py` — even mock wouldn't work. Inside try, the import failure is caught and mock takes over.

**Reason 2: Lazy loading.** Tool modules import heavy SDKs (SerpAPI, Firecrawl, LangChain models). Loading them at import time slows down application startup. Lazy importing defers this cost to the first function call.

**When NOT to do this**: For imports you're 100% sure will succeed (stdlib, your own guaranteed-present modules). Those belong at the top for clarity.

---

## 9. Raise, don't return empty {#9-raise-dont-return-empty}

```python
# Tool functions raise on complete failure:
raise RuntimeError("All flight data sources exhausted")

# Agent functions catch and fall back:
except Exception:
    logger.exception("tool failed, using mock")
    data = _mock(state)
```

**What we did**: Tool functions raise exceptions when they can't provide data. They never return `[]` pretending everything is fine.

**Why**: If `search_flights` returned `[]`, the agent would display "No flights found" to the user — implying there genuinely are no flights. The truth is "all APIs failed, we don't know if there are flights." These are different situations requiring different responses.

Raising forces the caller to explicitly decide: show mock? retry? tell the user? Returning empty lets the caller silently display nothing, which is a lie.

**The principle**: **Fail loudly, recover gracefully.** Tools fail loudly (raise). Agents recover gracefully (catch → mock → log → inform user).

---

## 10. Interface stability: why graph.py never changes {#10-interface-stability}

**What we did**: Through all of Phase 2 and Phase 3, `graph.py` (the LangGraph orchestrator) was modified exactly once — to add logging. The graph structure itself never changed.

**Why**: The graph defines topology (who runs after whom, what's parallel). Agent functions define behavior (what data to fetch, how to handle failures). We changed behavior drastically (mock → real APIs → parallel multi-source → LLM estimation fallback) without touching topology.

This works because agent functions maintain a stable interface:
```python
def ticket_agent(state: TravelPlanState) -> dict:
    # Input: full state
    # Output: {"tickets": [...], "messages": [...]}
    # This contract NEVER changed, even though internals went from
    # 3 lines of hardcoded data to 200 lines of parallel API calls.
```

**The principle**: Separate WHAT from HOW. Graph says WHAT runs. Agents say HOW. When HOW changes, WHAT doesn't need to know.

---

## 11. Validate at system boundaries {#11-boundary-validation}

```python
# _date_util.py: normalize at the tool layer, not upstream
normalize_date("Sep 7")           → "2026-09-07"
normalize_date("September 7, 2026") → "2026-09-07"
normalize_date("2026-09-07")       → "2026-09-07"
```

**What we did**: Date normalization happens in `_date_util.py`, called by tool functions right before sending data to external APIs.

**Why not normalize in graph.py or agents?** Because:
1. User input format is unpredictable ("Sep 7", "2026-09-07", "September 7, 2026")
2. Internal code doesn't care about format — it just passes strings around
3. External APIs (SerpAPI) have strict format requirements (ISO only)

The tool layer is the **system boundary** — where internal flexibility meets external strictness. Normalizing here means all upstream code stays flexible, and all external calls get clean data.

**The principle**: Don't force internal code to conform to external requirements. Translate at the boundary.

---

## 12. Search query quality: the pipeline's input bottleneck {#12-query-quality}

**What we learned**: A web search query is the first link in the data chain: query → search results → LLM context → output. If the query is bad, everything downstream is bad. No amount of LLM sophistication can extract good flight data from Flight Simulator search results.

**Three optimization principles we applied**:
1. **Specific terms > generic terms**: "airline tickets" not "flights" (avoids flight simulator noise)
2. **Intent signal keywords**: "price", "book", "airfare" tell the search engine this is a purchase query
3. **Use identifiers**: IATA codes ("JFK", "MXP") not city names ("New York", "Milan") for precision

**What we tested**: Three rounds of Bing experiments proved that query optimization helps but can't fix a fundamentally mismatched engine. Bing returned flight simulators (v1), booking homepages (v2), and Chinese social media (v3) — all because of locale and intent-matching differences vs Google.

---

## 13. When NOT to add a source {#13-noise-vs-signal}

**What we learned**: We tested adding Bing as a parallel source for flights and tickets. Result: pure noise.

**The litmus test**: "If this source's data was the ONLY data shown to the user, would they accept it?" If the answer is "no", it's not a source — it's a noise generator.

**Adding a bad source actively hurts**:
- Wastes API quota (one call per search, zero useful data)
- Adds merge complexity (now you have to filter out its noise)
- Can mislead the LLM (if you feed Bing's flight simulator snippets as context, LLM might extract nonsense)

**The distinction**: Not all "second sources" are equal. Google Hotels + Google Maps are **genuinely independent** (different backends, different data). Google Flights + Google Search are **one real source + one supplementary** (same company, but Search gives web pages not structured data).

---

## 14. Structured output with raw JSON fallback {#14-structured-output-fallback}

```python
# Strategy 1: with_structured_output (best quality)
try:
    structured = llm.with_structured_output(TicketOptionList)
    result = structured.invoke(messages)
except:
    # Strategy 2: raw JSON (works with any provider)
    raw = llm.invoke(messages_with_json_instruction)
    result = json.loads(raw.content)
```

**What we did**: Ticket extraction tries `with_structured_output` first, falls back to asking the LLM for raw JSON text and parsing it with `json.loads()`.

**Why two strategies?** `with_structured_output` uses OpenAI's function calling / JSON mode API. This requires the provider to return a `parsed` field in the response. Some proxies (like duckcoding.ai) don't relay this field → the call crashes.

Raw JSON fallback doesn't use any special API feature — it just asks the LLM to output JSON as text. Any LLM that can produce text can do this. Less reliable (might include markdown fences, might have wrong field names), but universally compatible.

**The principle**: Never depend on a single provider's special capability as your only path. Always have a standards-based fallback.

---

## 15. Function signatures: design for future callers {#15-future-proof-signatures}

```python
def search_hotels(city, checkin, checkout,
                  brand=None, stars=None, max_price=None,
                  near=None, excluded_ids=None):
```

**What we did**: Tool function signatures include parameters that NO CURRENT CALLER uses. Lane 1's `hotel_agent` only passes `city, checkin, checkout`. But `brand`, `stars`, `near`, `excluded_ids` are there from day one.

**Why**: Because Lane 2's Hotel Specialist WILL use them:
- User says "only Marriott" → `brand="Marriott"`
- User says "not those hotels" → `excluded_ids=[previous hotel ids]`
- User says "near the circuit" → `near="Autodromo"`

Adding a parameter with a default value is backward-compatible (existing callers don't break). Changing a signature later is a breaking change that requires updating all callers.

**The principle (Open-Closed)**: Functions should be open for extension (new optional params) and closed for modification (don't change existing params). Design the signature for your next caller, not just your current one.

---

## 16. DRY extraction: recompute_budget {#16-dry-extraction}

**What we did**: Extracted budget calculation from `budget_agent` into `tools/recompute.py`. Both Lane 1 (`budget_agent` node) and Lane 2 (supervisor's `recompute_budget_tool`) call the same function.

**Why**: Budget logic needed to handle real API data (filter INFO items, pick cheapest per category, multiply hotel by nights). If this logic existed in two places, a bug fix in one would need to be replicated in the other.

**When it happened**: The extraction was triggered by a real bug — `budget_agent` was summing ALL flight options ($2974) instead of picking the cheapest. If the logic had already been shared, we'd have fixed it once. Instead, we fixed it AND extracted it in the same commit.

**The principle**: If two callers need the same logic, put it in a third place. Don't let business logic live "inside" a specific agent — it belongs in the tools layer where anyone can call it.

---

## 17. Two-lane architecture {#17-two-lane}

```
Lane 1 (fixed graph):  parse → ticket → (transport || hotel) → (itinerary || tour) → budget
Lane 2 (supervisor):   user message → supervisor decides → call specific tool(s) → update state
```

**What we did**: Initial planning runs through a fixed LangGraph DAG (deterministic, parallel, fast). User refinement goes through a ReAct supervisor agent (flexible, agentic, targeted).

**Why not supervisor-only?** Three reasons:
1. **Parallelism**: Lane 1 runs transport + hotel simultaneously. A ReAct agent typically calls tools sequentially (think → call → observe → think...). Initial planning would be 3-4x slower.
2. **Reliability**: A fixed graph can't "forget" to search for hotels. An LLM might skip a step if the prompt isn't perfect.
3. **Cost**: Lane 1 uses LLM only for itinerary + tour (2 calls). A supervisor would use LLM for every routing decision (6+ calls).

**Why not fixed-graph-only?** Because user refinement is inherently open-ended. "Only Marriott hotels" requires understanding intent → choosing the right tool → passing the right parameters. This is exactly what LLM agents are good at.

**The evolution path**: If parallel tool calling becomes reliable (some models support it), the supervisor could eventually replace Lane 1 too. We designed for this: both lanes share the same tools and state, so switching is a one-file change.

---

## 18. Know when to stop optimizing {#18-stop-optimizing}

**What happened**: We spent 3 rounds testing Bing as a source (flight simulator noise → booking homepages → Chinese social media). Each round taught us something, but the conclusion was "don't use Bing." The user said: "先能够供用户使用比多一些消息源重要" (making it usable for users matters more than adding sources).

**The principle**: Optimization has diminishing returns. The first source gives you 0→80% quality. The second source gives you 80→95%. The third source gives you 95→97%. At some point, the time spent adding source #3 is better spent on the next major feature (supervisor, frontend, deployment).

**How to decide**: Ask "what's the highest-impact thing I could be doing right now?" If the answer is "add a marginally better source" and the alternative is "build the feature that lets users interact with the system" — build the feature.

**This is NOT an excuse to ship garbage**. Two working sources + robust fallback + degradation reporting is a solid foundation. "Stop optimizing" means "this foundation is good enough to build on", not "this foundation is perfect."

---

## Summary: the design philosophy in one sentence

> **Make change cheap. Make failure visible. Make quality measurable.**

- **Change is cheap** when tools/ and agents/ are separate, when interfaces are stable, when functions have extensible signatures.
- **Failure is visible** when tools raise (not return empty), when DegradationReport tracks every source, when logs capture every fallback.
- **Quality is measurable** when every result carries `_source` and `_degraded`, when the user sees "sources: google_flights + google_search", when the budget computation handles real data correctly.

---

_This document is updated as new lessons emerge. Last update: Phase 3.3 completion (real data from all three tools, parallel multi-source, query optimization experiments)._
