# Current Project Status — 2026-04-29

This note records the latest project state after the Phase 4 functional
completeness batch. It intentionally excludes personal interview-prep notes.

## Repo / Tracking

- Current branch: `main`, tracking `origin/main`.
- Latest pushed baseline before this batch: `9ac482e`.
- Project docs tracked under `docs/`; personal AIA/interview notes,
  `docs/flaws.md`, `AGENTS.md`, real `.env`, and `.local_harness/` remain
  local-only unless separately approved.

## Implemented In This Batch

- Selection-aware quote flow:
  - Backend `recompute_budget(state, selections=None)` keeps the old baseline
    behavior when no selections are supplied.
  - WebSocket `type="quote"` recomputes a selected total without mutating
    `plan_state` or chat history.
  - Frontend now keeps baseline vs selected budget state and sends quote
    requests whenever ticket/flight/hotel selections change.
- Quote completeness:
  - Budget summaries include `basis`, `quote_complete`,
    `missing_price_categories`, and `selected_indices`.
  - Unpriced items can be selected, but the budget display turns amber and
    marks the quote incomplete instead of showing a false green within-budget
    state.
- Booking/link semantics:
  - Ticket, flight, and hotel items now carry `provider`, `link_type`, and
    `booking_confidence` metadata where available.
  - Frontend copy distinguishes official ticket pages, flight searches, hotel
    listings, maps listings, and generic provider/search pages.
- Persistent itinerary/tour refinement:
  - Lane 2 now exposes `update_itinerary_tool` and `update_tour_tool`.
  - The result-card state map includes `itinerary` and `tour`, so schedule and
    explore changes can persist to cards.
  - Update tools normalize structured/dict-like tool input into frontend-safe
    strings and target named days/items instead of leaking raw Python objects.
  - The no-tool guard remains: if no tool actually updates state, replies must
    not claim that result cards changed.
- Structured constraint memory:
  - `active_constraints` is part of plan state and client snapshots.
  - Constraints currently track direct-only flights, allowed hotel brands,
    dietary needs, accessibility, avoid-luxury, and budget strategy.
  - Constraints are initialized from plan inputs and updated on chat turns, so
    they survive beyond the short rolling conversation history.
  - Frontend renders constraint chips so users can see what the system is
    currently enforcing.
- CI now runs backend unit tests in addition to backend compile and frontend
  build.

## Verification Summary

- Backend compile passed: `backend/.venv/bin/python -m compileall -q backend`.
- Backend unit tests passed: `backend/.venv/bin/python -m unittest discover -s backend/tests -v` with 24 tests.
- Frontend production build passed: `npm run build`.
- Browser E2E passed for Monza planning, default dates
  `2026-09-04` -> `2026-09-09`, selected quote changes, incomplete unpriced
  quote, multi-round direct/brand constraints, itinerary card persistence, tour
  title replacement, debug trace, and backend/frontend `/api/calendar` health.

## Remaining Functional Gaps

- Itinerary/tour update tools are deterministic and safer than free-form
  promises, but still basic; a later version should use schema-validated LLM
  rewriting with diff/rollback guards.
- Selection-aware quoting is backend-authoritative over WebSocket, but there is
  no persisted user account/session store yet.
- `active_constraints` is in-memory per WebSocket session; it does not survive
  page reloads or backend restart.
- Budget is still not a full global optimizer. It is now more honest and
  selection-aware, but it does not search all tradeoff combinations.
- Frontend remains a single-file React prototype; component extraction is now
  increasingly valuable.

## Next Engineering Priorities

1. Add deterministic fixture-backed browser automation so quote/constraint
   E2E can run in CI instead of only through Browser Use.
2. Replace basic itinerary/tour text patching with schema-validated LLM
   rewriting and diff/rollback guards.
3. Add a real quote/session store when moving beyond demo mode.
4. Expand budget strategy from evaluator to tradeoff optimizer.
5. Split `frontend/prototype.jsx` into components once this functional batch is
   stable.

## Interview Framing

- The product now has two forms of memory: short rolling conversation history
  for pronoun/reference resolution, and structured `active_constraints` for
  durable business rules such as direct-only and approved hotel brands.
- Selection-aware quote flow separates immutable plan state from ephemeral UI
  quote state. That avoids corrupting the trip plan when a user clicks around.
- WebSocket still owns per-session state, while the backend plan semaphore and
  rate limits protect LLM/API cost. `quote` intentionally bypasses the plan
  semaphore because it is a lightweight pure recomputation.
- Copy-on-write refinement remains the state-safety rule: chat changes are
  applied to a working copy and committed only after success.
