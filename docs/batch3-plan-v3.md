# Batch 3 Implementation Plan — v3

Date: 2026-04-16
Status: Awaiting final reviewer approval before Phase 1 implementation

## Background

Batch 3 addresses two cross-cutting user-facing limitations that emerged in real demo usage:

1. **Currency inconsistency**: frontend budget in EUR, but supervisor reply and some displays mix USD. Root cause — no per-session currency binding across the plan → recompute → refine → display chain.
2. **Date rigidity**: users can only control return via an `extra_days` slider. Cannot arrive earlier (Wednesday instead of Friday) or stay shorter than the weekend.

Design went through 3 iterations. v1 missed 5 cross-cutting points. v2 closed those but missed API boundary error handling + 4 frontend/chat edge cases. v3 below is the final version.

## Design Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | **Front-load validation** at API boundary — agents see only empty or valid dates | Prevents deep-stack ValueErrors from crashing Lane 1 or WS sessions |
| 2 | **No silent fallback** on explicit invalid input | User expects their input to be respected; silent fallback produces plausible-but-wrong plans |
| 3 | **Hard check + soft warning** layering | Hard-block only format/ordering errors; allow legitimate non-typical trips (Saturday arrival, day-trip, long stay) with soft hints |
| 4 | **Display layer never crashes** | `_format_state` and similar present-layer code must degrade on unexpected state rather than raise |
| 5 | **Card currency: plan A** — cards show source currency, summary/reply shows selected currency | Smallest change footprint, easiest to debug, doesn't pollute raw data |
| 6 | **Copy-on-write state mutation** in refine | Half-updated state on exception must not persist in session |

## Scope — Currency (B.1)

### Files affected (7)

| File | Change |
|------|--------|
| `backend/state.py` | TypedDict adds `currency: str` |
| `backend/main.py` | TripRequest adds `currency: str = "EUR"`; POST `/plan` + `_handle_plan` wrap errors (400 / ws error) |
| `backend/graph.py` | `plan_trip` writes `currency` into `initial_state`; CLI test default `"EUR"` |
| `backend/refine.py` | `_format_state` + `_apply_tool_updates` logger use `state["currency"]`; `MODE_REFINE` prompt injects currency; display helpers degrade on error |
| `backend/tools/recompute.py` | `recompute_budget` accepts `target_currency` from state; items + savings_tip + BudgetSummary.currency all use target |
| `backend/agents/__init__.py` | `budget_agent` status message uses dynamic currency (not hardcoded `EUR`) |
| `frontend/prototype.jsx` | Form adds currency selector (3 buttons); plan payload includes currency; budget card label dynamic; `ResultCard` `€{selectedTotal}` chip handling (see below) |

### Open UI decision — ResultCard selectedTotal chip

The per-zone chip at `prototype.jsx:165` shows `€{selectedTotal}` by summing raw `pv` values across items. Under plan A, flights may be USD while tickets are EUR — summing raw values and prefixing `€` is factually wrong.

**Chosen approach**: remove the chip for transport / hotel / tour zones (multi-item), keep it only for same-currency contexts. Show "N selected" text instead when mixed-currency.

Alternative (rejected for now): introduce `display_price/display_currency` fields — too close to plan B complexity.

### Currency selector UX semantics

When user toggles EUR ↔ USD ↔ CNY with a budget already entered:

- **No auto-conversion.** The numeric value stays; only the unit changes.
- Label next to input clarifies: "Budget amount interpreted in selected currency"

Rationale: auto-conversion introduces a whole class of edge cases (rate precision, which rate table, when to refresh). Keep the selector semantically simple.

## Scope — Dates (B.2)

### Files affected (8)

| File | Change |
|------|--------|
| `backend/state.py` | TypedDict adds `depart_date: str`, `return_date: str` (empty-string default) |
| `backend/main.py` | TripRequest adds two string fields; POST `/plan` + `_handle_plan` call `validate_trip_dates` and short-circuit on failure |
| `backend/graph.py` | `initial_state` carries new fields; CLI default leaves them empty (falls through to old `extra_days` path) |
| `backend/tools/_trip_dates.py` | Add `validate_trip_dates(gp_date, depart, return) -> (ok, reason)`; extend `compute_trip_dates` signature to accept new fields; when both empty use old logic; when both set use them directly |
| `backend/agents/__init__.py` | `_trip_days(state)` now checks new fields first; `_hotel_mock` calls `_trip_days` instead of inlining `3 + extra_days`; transport/hotel agents pass new fields into `compute_trip_dates` |
| `backend/tools/recompute.py` | `trip_days` derivation via `_trip_days` / `compute_trip_dates`, not raw `extra_days` |
| `backend/refine.py` | `_format_state` shows "Trip: depart → return (N nights)" instead of "Extra days: N"; `_build_tools` calls `compute_trip_dates` with new fields; all date-dependent display wrapped in try/except |
| `frontend/prototype.jsx` | Remove `extraDays` slider; `departDate`/`returnDate` inputs become editable; client-side hard-check (format + depart ≤ return); soft warnings for unusual combinations; error handler for WS `type=error` allowing retry without page reload |

### Validation rules

**Hard check (blocks submission):**
- Both dates must be set (if either is set, both required)
- ISO format `YYYY-MM-DD`
- `depart_date ≤ return_date`

**Soft warnings (non-blocking):**
- `depart_date > gp_date` → "You'll arrive after the race starts"
- `return_date < gp_date` → "You'll leave before race day"
- `return_date - depart_date > 14` → "Over 14 days, confirm?"

### Error handling flow

```
User submits dates
  ↓
Frontend hard-check
  ├─ Pass → build payload → ws/http send
  └─ Fail → inline error, disable submit, no send
  ↓
Backend _handle_plan / POST /plan
  ↓
validate_trip_dates(gp_date, depart, return)
  ├─ (False, reason) → 400 / ws error(reason) → user can fix and retry
  └─ (True, _)       → plan_trip(state)
                       ↓
                       compute_trip_dates uses validated dates
                       (or falls back to extra_days if both empty)
```

### Chat path (refine) — copy-on-write

Current `_apply_tool_updates` mutates `state` in place. If an exception fires mid-update, session's `plan_state` is half-written.

New flow in `_handle_chat`:

```python
import copy
snapshot = copy.deepcopy(session["plan_state"])
try:
    updated_state, reply = refine_plan(snapshot, user_message, history)
    session["plan_state"] = updated_state   # only on success
    ...
except ValueError as e:  # known recoverable
    await ws.send_json({"type": "error", "data": str(e)})
    # session["plan_state"] unchanged
except Exception:
    logger.exception("_handle_chat unexpected")
    await ws.send_json({"type": "error", "data": "Internal chat error"})
    # session["plan_state"] unchanged
```

## Task Table

| ID | Phase | Task | File(s) | Depends on |
|----|-------|------|---------|------------|
| 3.1.1 | 1 | Add `currency` to state + TripRequest | `state.py`, `main.py` | — |
| 3.1.2 | 1 | Plumb `currency` through `plan_trip` initial_state + CLI default | `graph.py` | 3.1.1 |
| 3.1.3 | 1 | `recompute` target_currency support + items + savings_tip + BudgetSummary.currency | `tools/recompute.py` | 3.1.1 |
| 3.1.4 | 1 | `budget_agent` status message dynamic currency | `agents/__init__.py` | 3.1.3 |
| 3.1.5 | 1 | `refine._format_state` + `_apply_tool_updates` logger use state currency; MODE_REFINE prompt injects currency | `refine.py` | 3.1.1 |
| 3.1.6 | 1 | Frontend currency selector + plan payload + budget label dynamic + chip rule | `prototype.jsx` | 3.1.1 |
| 3.1.V | 1 | Verify: compileall, npm build, mock plan in EUR/USD/CNY | — | 3.1.1–6 |
| 3.2.1 | 2 | Add `depart_date`, `return_date` to state + TripRequest | `state.py`, `main.py` | 3.1 done |
| 3.2.2 | 2 | `validate_trip_dates()` + extended `compute_trip_dates` signature | `tools/_trip_dates.py` | 3.2.1 |
| 3.2.3 | 2 | POST `/plan` + WS `_handle_plan` call validator, return 400 / ws error | `main.py` | 3.2.2 |
| 3.2.4 | 2 | `graph.py` initial_state + CLI default | `graph.py` | 3.2.1 |
| 3.2.5 | 2 | `_trip_days` helper update; `_hotel_mock`, transport/hotel agents use new fields | `agents/__init__.py` | 3.2.2 |
| 3.2.6 | 2 | `recompute.trip_days` via helper | `tools/recompute.py` | 3.2.5 |
| 3.2.7 | 2 | `refine._format_state` date label; `_build_tools` pass new fields; try/except wrap displays | `refine.py` | 3.2.2 |
| 3.2.8 | 2 | `_handle_chat` copy-on-write guard | `main.py` | 3.2.7 |
| 3.2.9 | 2 | Frontend: remove slider, editable dates, hard+soft validation, ws error handler | `prototype.jsx` | 3.2.2 |
| 3.2.V | 2 | Verify: compileall, npm build, 6 scenarios (default, early arrival, invalid dates, stale state chat, etc.) | — | 3.2.1–9 |

## Out of Scope (deferred)

- Dynamic exchange rates (stays with fixed table in `_currency.py`)
- Timezone library integration (all dates stay naive ISO strings)
- Server-side persistence (session remains ws-lifetime only)
- Frontend framework migration to Next.js
- Real circuit layout images (rights uncertain)
- PWA / mobile responsive (Phase 4.2)
- Mock data multi-currency variants (documented as EUR-sourced; plan A semantics make this acceptable)
- Unit test baseline (`backend/tests/` missing; will be a separate ticket)

## Verification Matrix

### Phase 1 exit criteria
- [ ] `python -m compileall backend` green
- [ ] `npm run build` green
- [ ] Plan with `currency=EUR` works end-to-end; summary shows EUR; cards show source
- [ ] Plan with `currency=USD`: budget summary in USD, supervisor reply in USD
- [ ] Plan with `currency=CNY`: same
- [ ] Refine flow: supervisor uses selected currency per MODE_REFINE prompt
- [ ] `budget_agent` status message matches summary currency

### Phase 2 exit criteria
- [ ] `python -m compileall backend` green
- [ ] `npm run build` green
- [ ] Plan with empty depart/return: falls back to old `extra_days` path correctly
- [ ] Plan with valid depart (race - 4) / return (race + 1): dates respected across agents + budget
- [ ] Plan with `depart > return`: POST returns 400; WS sends error message; socket stays open; user can fix and retry
- [ ] Plan with malformed date string: same as above
- [ ] Chat after plan with valid state: normal refine works
- [ ] Chat with session that has stale invalid dates: `_format_state` degrades, refine doesn't crash, socket stays open
- [ ] Exception in `_apply_tool_updates` mid-update: session `plan_state` unchanged; error returned to client

## Rollout

1. Feature-flag not needed — changes are additive and backward-compatible
2. No schema migrations (no persistence)
3. Commit per sub-phase: one for 3.1 code, one for 3.1 docs; same for 3.2
4. Push after each Phase's verification matrix is green
