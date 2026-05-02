# Current Project Status — 2026-05-02

This note records the current project state after the Round 2 feature-completion
and internal stabilization work. It intentionally excludes personal interview
notes, real `.env` files, and local harness records.

## Repo / Tracking

- Current branch: `main`, tracking `origin/main`.
- Latest pushed baseline before this working batch: `f2433af`.
- Current working tree contains uncommitted project changes for quote hardening,
  explainability, frontend/backend modularization, tests, and docs.
- Personal/local files remain excluded from git unless separately approved:
  `AGENTS.md`, `.env`, `.local_harness/`, `docs/flaws.md`, AIA/interview docs,
  and anti-drift notes.

## Implemented Functional Work

- Selection-aware quote flow:
  - WebSocket `type="quote"` recomputes selected ticket/flight/hotel totals
    without mutating the saved plan state or chat history.
  - `recompute_budget(state, selections=None)` keeps the old cheapest-baseline
    behavior when no selections are supplied.
  - Duplicate selected indices are deduped; malformed selections, unknown
    categories, numeric strings, negative indices, out-of-range indices, and
    `selections: null` are rejected cleanly.
- Quote completeness:
  - `BudgetSummary` includes `basis`, `quote_complete`,
    `missing_price_categories`, and `selected_indices`.
  - Unpriced selections are allowed but turn the budget amber/incomplete
    instead of pretending the trip is within budget.
- Booking/link semantics:
  - Ticket, flight, and hotel cards include `provider`, `link_type`, and
    `booking_confidence` metadata where available.
  - Frontend copy distinguishes official ticket pages, flight searches, hotel
    listings, maps listings, and generic provider/search pages.
- Persistent itinerary/tour refinement:
  - Lane 2 exposes `update_itinerary_tool` and `update_tour_tool`.
  - Tools now edit the server-side state captured by the closure; they no
    longer accept LLM-supplied current-state JSON.
  - If no tool actually updates state, replies cannot claim result cards were
    changed.
- Structured constraint memory:
  - `active_constraints` stores durable rules such as direct-only flights,
    allowed hotel brands, dietary needs, accessibility, avoid-luxury, and
    budget strategy.
  - Constraint extraction supports English and Chinese inputs, plus explicit
    clearing phrases such as “connections are OK” or “any brand is fine”.
  - A deterministic hard-constraint reconciler removes flights/hotels that
    contradict active constraints after tool output.
- Card explainability:
  - Ticket, flight, and hotel cards carry deterministic `_rationale` metadata.
  - Frontend cards expose a “Why this card?” panel with reasons, matched
    constraints, source path, and trade-offs.
  - Source path is a product data path inferred from final card source; it is
    not described as a full runtime attempt trace.

## Internal Stabilization Work

- Frontend structure:
  - `frontend/prototype.jsx` is now the application orchestrator: state,
    WebSocket, and page composition.
  - Pure display/domain rules moved into `frontend/domain/`.
  - Render-only UI moved into `frontend/components/`, including GP selection,
    welcome form, budget panel, chat panel, result card, explainability panel,
    and paddock visuals.
  - `prototype.jsx` has been reduced from a large single-file prototype to
    roughly 400 lines.
- Backend structure:
  - `backend/agents/__init__.py` is now a facade; individual graph agent nodes
    live in `backend/agents/*.py`.
  - `backend/refine_editing.py` owns itinerary/tour text update helpers.
  - `backend/refine_constraints.py` owns the hard-constraint reconciler.
  - `backend/refine.py` still owns the supervisor orchestration, but no longer
    contains all helper logic inline.
- Project understanding:
  - `docs/architecture-map.zh-CN.md` explains the current state flow, memory
    layers, quote contract, hard constraints, explainability, and module
    boundaries in maintainer-friendly language.

## Verification Summary

- Backend compile passed: `backend/.venv/bin/python -m compileall -q backend`.
- Backend unit tests passed: `backend/.venv/bin/python -m unittest discover -s backend/tests -v` with 41 tests.
- Frontend production build passed: `npm run build`.
- Frontend dependency audit passed: `npm audit --audit-level=moderate`.
- Browser Use E2E was rerun against restarted local services:
  - Singapore GP: default dates `2026-10-09` -> `2026-10-14`, normal planning,
    selected quote, unpriced incomplete quote, explainability panel, and debug
    trace.
  - Miami GP: normal planning, direct-only refinement, Chinese Marriott/Hilton
    brand constraint, itinerary persistence, tour persistence, and
    explainability panel.
  - Canadian GP: default dates `2026-05-22` -> `2026-05-27`, same-day rejection,
    >30-night rejection, and no new console errors during the date-boundary
    interactions.
- Browser testing found and fixed two regressions during this batch:
  - Direct-only refinement could keep a card whose text said `1 stop` when a
    bad structured field said `stops: 0`.
  - The extracted `WelcomeForm` date input used `e.currentTarget.value` inside
    an async state updater, which could null out and blank the page.

## Remaining Functional Gaps

- Itinerary/tour update tools are deterministic and safer than free-form
  promises, but still basic; a later version should use schema-validated LLM
  rewriting with diff/rollback guards.
- `active_constraints` and plan state are in-memory per WebSocket session; they
  do not survive page reloads or backend restarts.
- Budget is selection-aware and honest about missing prices, but it is not yet
  a full optimizer that searches all tradeoff combinations.
- Explainability currently covers ticket, flight, and hotel cards. Schedule and
  Explore explainability remain future work.
- Production readiness still needs auth, explicit CORS/origin policy, rate
  limiting, persistent storage, and CI browser automation.

## Next Engineering Priorities

1. Commit the current stabilization batch in labelled slices, keeping personal
   docs and local harness files out of git.
2. Add deterministic fixture-backed browser automation so quote/constraint E2E
   can run in CI instead of only through Browser Use.
3. Replace basic itinerary/tour text patching with schema-validated rewriting,
   diff preview, and rollback guards.
4. Add an Explainability panel v2 only if it can show true runtime attempt trace
   rather than inferred source path.
5. Add iCal export for the selected itinerary once state contracts are stable.
6. Add a real quote/session store before moving beyond demo mode.
7. Expand budget strategy from evaluator to tradeoff optimizer.

## Interview Framing

- The architecture separates deterministic workflow from flexible refinement:
  Lane 1 is a LangGraph DAG for fixed parallel planning; Lane 2 is a supervisor
  for localized natural-language edits.
- The product has two kinds of memory: rolling chat history for language
  context, and structured `active_constraints` for durable business rules.
- Quote preview is intentionally side-effect-free. It lets users compare card
  selections without corrupting the saved plan state.
- Copy-on-write refinement is the safety rule: update a working copy, commit
  only after successful tool application, and summarize from persisted state.
- Explainability is useful only if wording is honest. This project says
  “source path” unless a true runtime trace is available.
