# Plan Issues

This file records plan and architecture issues discovered after Phase 3 landed on `main`.
It lives next to `CLAUDE.md` so the project context and the known plan gaps stay together.

## Current Conclusion

`search_web.py` does **not** block the current Phase 4 frontend wiring work, because it is not in the active runtime path today:

- `tour_agent` currently uses LLM-or-mock output only.
- `refine.py` exposes hotel / flight / ticket / recompute tools, but not `search_web`.
- `/ws` can already produce a usable planning flow without general web search.

That said, several plan assumptions are now stale or misleading.

## Recorded Issues

### 1. Security is no longer safe to defer to Phase 5

This is the highest priority planning problem.

- `/ws` is already live.
- Chat-driven agentic tool use is already live.
- CORS is still fully open (`allow_origins=["*"]`).
- There is no auth, rate limiting, or abuse control around the WebSocket path.

The old architecture note already identified this risk and suggested moving the security baseline earlier, before chat routing went live. That warning is now reality, so keeping "security baseline" in Phase 5 is not a sound plan anymore.

## Required adjustment

Add a security checkpoint before or alongside Phase 4, not after it.

### 2. Chat-first frontend conflicts with current backend behavior

The current backend supports two different entry modes:

- `type=plan`: full Lane 1 pipeline, produces the complete 5/5 plan
- `type=chat` as the first message: supervisor planning mode, produces only tickets / flights / hotels / budget

This means the current chat-first path produces a **partial** plan without itinerary or tour.

So the Phase 4 idea of making chat a first-class entry point is not wrong by itself, but it is incomplete. If the frontend presents chat as an equal starting path, users can easily end up in a 3/5 result flow while expecting the full product.

## Required adjustment

Before shipping the frontend UX, decide one of these explicitly:

- chat-first is only a refinement / lightweight planning path
- chat-first must trigger the full 5/5 planning flow
- the UI must clearly separate "quick chat plan" from "full trip plan"

### 3. `search_web.py` is more deferred than the docs imply

`search_web.py` is currently:

- not wired into `tour_agent`
- not exposed to the supervisor
- missing real Tavily / DuckDuckGo implementation
- missing related dependencies in `backend/requirements.txt`

So it should not be described as "basically there" or "just waiting to be connected". It is a deferred capability, not an almost-finished tool.

There is also a behavior risk: the helper functions currently return empty strings instead of raising clear provider failures, so a future partial integration could silently accept empty search output.

## Required adjustment

Document `search_web` as explicitly deferred, or finish it properly before claiming web-backed tour search.

### 4. Documentation drift is already visible

The clearest example is `search_tickets.py` comments still referring to Bing in several places even though the implementation now uses Google Search.

This does not break execution, but it weakens architecture docs and future planning discussions because the repo starts arguing with itself.

## Required adjustment

When a phase lands, update the nearby implementation comments and architecture notes in the same pass.

## Practical Priorities

Given the current codebase, the most reasonable order is:

1. Keep Phase 4 frontend wiring as the product-facing next step.
2. Move a minimal security baseline forward so `/ws` is not left fully open.
3. Resolve the chat-first vs full-plan product behavior before frontend UX hardens around the wrong assumption.
4. Treat `search_web` as a later capability unless it becomes a concrete product requirement.
