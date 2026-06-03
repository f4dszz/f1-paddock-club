---
id: G-002
title: Explainability rationale renders reasons and honest source path
mode_chain: verification
objective_check: backend/tests/test_rationale.py + frontend/e2e/explain.spec.js
invariant: "Expose honest source/degradation metadata; do not silently discard provider failures."
---

# G-002 — Explainability rationale

## Goal

Verify that every card carries a deterministic rationale (reasons + fallback
source chain), built at planning time without an LLM call, and that the "Why this
card?" affordance renders that rationale visibly — including the honest
`Mock data` source label on the terminal fallback.

## Mode chain exercised

`verification`. Both checks are positive assertions over already-built behavior:
a backend unit test on the rationale builders and a frontend E2E on the actual
"i" affordance.

## Input / material paths

- `backend/tests/test_rationale.py` — unit coverage of `build_*_rationale`,
  fallback chains, bounded trade-offs, and agent attachment.
- `frontend/e2e/explain.spec.js` — clicks the real `explain-button-ticket-2`
  affordance and asserts reasons + source path render.
- `backend/tools/_rationale.py` — builders and `_TICKET_SOURCE_CHAIN`.
- `frontend/components/ExplainabilityPanel.jsx` — panel rendering.

## Objective acceptance (must pass)

Backend (runs in the no-key lane, same discovery as `check-local.sh` step 3):

```bash
cd backend && python -m unittest tests.test_rationale -v
```

Frontend (default no-key E2E lane — no `LLM_STUB_MODE` needed; rationales are
deterministic):

```bash
./scripts/e2e-local.sh   # includes explain.spec.js by default
```

Non-vacuous anchors: backend asserts `fallback_chain == ["firecrawl",
"llm_estimate", "mock"]` for tickets and `card_type` on attached rationales; the
E2E asserts the panel shows "Tag: VIP", "Pit lane + podium", and "Mock data".

## Rubric dims to score

- A2 Evidence quality (source path is the evidence), A4 No over-promising
  (honest `Mock data` label), A1 Correctness.
- Part B: both checks above must pass. Part C: tokens / rounds / wall-time.

## Non-goals

- Do not introduce an LLM call into rationale building.
- Do not change the fallback chain ordering or source labels.
- Do not synthetically render the panel; the E2E must use the real affordance.
