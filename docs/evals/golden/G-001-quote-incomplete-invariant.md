---
id: G-001
title: Unpriced item must yield an incomplete quote, not a green total
mode_chain: audit -> verification
objective_check: frontend/e2e/quote_incomplete.spec.js
invariant: "Any selected unpriced item must produce an incomplete quote, not a green total."
---

# G-001 — Quote-incomplete invariant

## Goal

Confirm (audit) and then prove (verification) that selecting a ticket with
`price=0` forces the budget panel into the amber "Incomplete quote" state with
the missing price category named — never a green confirmed total. This is a core
trust invariant from `CLAUDE.md`.

## Mode chain exercised

`audit -> verification`. Audit reads the recompute path and frontend budget
rendering to locate where `quote_complete` is set and consumed. Verification runs
the deterministic E2E spec that exercises the real "i"-free selection flow.

## Input / material paths

- `frontend/e2e/quote_incomplete.spec.js` — the objective spec.
- `frontend/components/BudgetPanel.jsx` — amber pending-price tone (line ~39).
- `backend/tools/recompute.py` — sets `quote_complete=false` + `missing_price_categories`.
- `backend/agents/tickets.py` `_ticket_mock` — appends the `price=0`
  "Paddock Club (price on request)" option under `LLM_STUB_MODE=1`.
- `CLAUDE.md` Code Quality Rules — the invariant text.

## Objective acceptance (must pass)

The Playwright spec passes under the deterministic lane:

```bash
E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1 ./scripts/e2e-local.sh
```

(`playwright.config.js` ignores `quote_incomplete.spec.js` unless
`E2E_INCLUDE_REFINE=1`; the `price=0` option only exists under
`APP_ENV=test` + `LLM_STUB_MODE=1`.) The non-vacuous assertions are the positive
ones: budget panel shows "Incomplete quote" + "Tickets", and the debug trace
carries `"quote_complete":false`.

## Rubric dims to score

- A1 Correctness, A4 No over-promising (the invariant *is* an anti-over-promising
  rule), plus A2 Evidence quality.
- Part B: the spec above. Part C: tokens / rounds / wall-time.

## Non-goals

- Do not change `recompute.py` thresholds or the mock ticket set.
- Do not add new budget states; only the existing complete/incomplete contract.
- No network providers — deterministic lane only.
