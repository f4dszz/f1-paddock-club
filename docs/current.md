# Current Project Status — 2026-06-03

This note is the canonical near-term status snapshot. `AGENTS.md` / `CLAUDE.md`
point coding agents here, so it must stay accurate: shipped-vs-pending status,
the real test count, and the genuinely-remaining gaps. It intentionally excludes
personal interview notes, real `.env` files, and local harness records.

It records the state after the Round 2 feature-completion work, the Round 3
stabilization work, and the **Phase 4.7 enterprise floor** (auth, persistence,
observability, deploy config, security baseline) — all of which have shipped.

## Repo / Tracking

- Working branch for the current audit sweep: `gap-audit-sweep`. The deploy
  branch is `main` (Vercel + Railway auto-deploy on push to `main`).
- `AGENTS.md` and `CLAUDE.md` are tracked, compact, and kept byte-identical by
  `scripts/check-agent-doc-sync.sh`. Personal/local files remain excluded from
  git unless separately approved: `.env`, `.harness/`, AIA/interview docs, and
  anti-drift notes.

## Shipped Functional Work

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
  - A one-way-only flight set or a hard constraint that empties a category marks
    the budget incomplete rather than reporting a green within-budget total.
- Booking/link semantics:
  - Ticket, flight, and hotel cards include `provider`, `link_type`, and
    `booking_confidence` metadata where available.
  - Frontend copy distinguishes official ticket pages, flight searches, hotel
    listings, maps listings, and generic provider/search pages — never implying
    a confirmed purchase.
- Persistent itinerary/tour refinement:
  - Lane 2 exposes `update_itinerary_tool` and `update_tour_tool`.
  - Tools edit the server-side state captured by the closure; they no longer
    accept LLM-supplied current-state JSON.
  - If no tool actually updates state, replies cannot claim result cards were
    changed.
- Structured constraint memory:
  - `active_constraints` stores durable rules such as direct-only flights,
    allowed hotel brands, dietary needs, accessibility, avoid-luxury, and
    budget strategy.
  - Constraint extraction supports English and Chinese inputs, plus explicit
    clearing phrases such as “connections are OK” or “any brand is fine”, and no
    longer misfires on neutral wording like “what is my budget?”.
  - A deterministic hard-constraint reconciler removes flights/hotels that
    contradict active constraints after tool output.
- Card explainability:
  - Ticket, flight, and hotel cards carry deterministic `_rationale` metadata.
  - Frontend cards expose a “Why this card?” panel with reasons, matched
    constraints, source path, and trade-offs.
  - Source path is a product data path inferred from the final card source; it is
    not described as a full runtime attempt trace.

## Enterprise Floor (Phase 4.7) — Shipped

These are the items earlier versions of this note listed as "remaining
production-readiness gaps". They have all shipped:

- **Auth.** Real OAuth sign-in via Clerk (`@clerk/clerk-react`), backend JWT
  verification against Clerk JWKS, per-identity isolation, and fail-closed
  behavior (a non-local deploy with neither Clerk nor a demo token configured
  returns 503 instead of admitting everyone as `demo-user`). Transient JWKS
  outages serve a stale cached key or return 503/close, not 500.
- **Persistence.** Postgres-backed saved trips via SQLAlchemy ORM
  (`backend/models.py`), CRUD in `backend/repository.py`, engine/session wiring
  in `backend/db.py` (which rewrites Railway's bare `postgresql://` URL to the
  psycopg3 driver), and Alembic migrations run at deploy time via `railway.json`.
  Saved trips are owner-scoped per Clerk identity; the shared `demo-user`
  sentinel cannot own persisted trips on a real deploy.
- **Observability.** Sentry error tracking on backend and frontend (DSN-gated),
  structured JSON logging, and per-request `request_id` binding
  (`backend/observability.py`).
- **Health probes.** `/healthz` (liveness) and `/readyz` (DB-aware readiness,
  503 when the DB is down).
- **Security baseline.** Explicit `ALLOWED_ORIGINS` CORS allowlist (fail-fast on
  empty in non-local), WebSocket Origin gate, CSP/HSTS middleware in production,
  per-IP rate limiting keyed off the trusted right-most `X-Forwarded-For` hop and
  run before auth, interactive API docs disabled on real deploys, and `gitleaks`
  secret-scan CI on every push/PR.
- **Deploy config.** `vercel.json` (static frontend + headers), `railway.json`
  (FastAPI + Postgres, migrations in the start command), and a
  `deploy-smoke` workflow. A fresh-machine deploy runbook lives in the README
  ("Deploy from scratch (Vercel + Railway + Clerk + Sentry)").
- **CI browser automation.** Deterministic Playwright E2E lanes run in CI (see
  Verification Summary).

The frontend gracefully falls back to demo-token mode for local dev when
`VITE_CLERK_PUBLISHABLE_KEY` is unset, so the E2E lanes keep running without
external credentials. The mock/estimate data path remains a permanent
graceful-degradation fallback.

## Deploy Verification Status (in progress)

Deploy **config** has shipped, but the end-to-end deploy **gate** is not yet
signed off. Per the harness control plane (`.harness/STATE.md`):

- **T-001** (deterministic E2E in CI) — R10 changes committed; **awaiting the
  reviewer's R10 verdict**.
- **T-DEPLOY-VERIFY** (deploy-gate verification + roadmap sync) — **planned, not
  started**; gated on T-001 closing.

Until those close, treat deploy as **"config shipped, end-to-end gate
verification pending"** rather than fully signed off. The README "Current State"
table, the README roadmap, and `docs/deployment-design.md` all carry the same
caveat so the docs and the harness agree.

## Internal Stabilization Work

- Frontend structure:
  - `frontend/prototype.jsx` is the application orchestrator: state, WebSocket,
    and page composition (~400 lines).
  - Pure display/domain rules live in `frontend/domain/`.
  - Render-only UI lives in `frontend/components/`, including GP selection,
    welcome form, budget panel, chat panel, result card, and explainability
    panel.
- Backend structure:
  - `backend/agents/__init__.py` is a facade; individual graph agent nodes live
    in `backend/agents/*.py`.
  - `backend/refine_editing.py` owns itinerary/tour text update helpers,
    `backend/refine_constraints.py` owns the hard-constraint reconciler, and
    `backend/refine_state.py` / `backend/refine_reply.py` own state-apply and
    deterministic-reply helpers split out of `backend/refine.py`.
  - The enterprise-floor modules `backend/db.py`, `backend/models.py`,
    `backend/repository.py`, and `backend/observability.py` own persistence and
    observability.
- Project understanding:
  - `docs/architecture-map.zh-CN.md` explains the current state flow, memory
    layers, quote contract, hard constraints, explainability, and module
    boundaries in maintainer-friendly language.

## Verification Summary

- Backend compile passes: `backend/.venv/bin/python -m compileall -q backend`.
- Backend unit tests pass: `backend/.venv/bin/python -m unittest discover -s
  backend/tests -v` — **131 tests, OK** (test_links, test_main_auth,
  test_main_trip_ws, test_outbound_egress, test_p0_trust_fixes, test_rationale,
  test_repository, test_security_headers, and the feature-completion suite).
- Frontend production build passes: `npm run build`.
- Frontend dependency audit passes: `npm audit --audit-level=moderate`
  (0 vulnerabilities).
- Local verification can be run with `./scripts/check-local.sh`, which bundles
  guideline sync, backend compile, backend tests, URL-normalizer skill tests,
  frontend `npm ci`, frontend build, and audit.
- Browser smoke can be run with `./scripts/e2e-local.sh`. The Playwright suite
  in `frontend/e2e/` has **five spec files / seven cases** across three lanes:
  - **Default lane** (`smoke.spec.js`, `explain.spec.js`) — no LLM keys; mock
    fallback selection/quote/links, a date-input regression, and the
    explainability panel content.
  - **Stub-gated refine lane** (`refine.spec.js`, `quote_incomplete.spec.js`) —
    `E2E_INCLUDE_REFINE=1` + `LLM_STUB_MODE=1`; direct-only refinement, English
    Explore-card replacement, and the unpriced/incomplete amber-quote path.
  - **Saved-trips lane** (`saved_trips.spec.js`) — `E2E_INCLUDE_SAVED=1` +
    `LLM_STUB_MODE=1`; the enterprise-floor save → reload → list → load
    round-trip against the SQLite-backed persistence layer.
- CI (`.github/workflows/ci.yml`) runs the full lane with
  `E2E_INCLUDE_REFINE=1 LLM_STUB_MODE=1` plus the bundled `check-local.sh` job;
  Playwright artifacts upload on failure. (The saved-trips lane is gated behind
  `E2E_INCLUDE_SAVED=1` and is one of the items T-DEPLOY-VERIFY will confirm runs
  in the gate.)
- `scripts/install-hooks.sh` enables `.githooks/pre-push`, which gates every push
  on `check-agent-doc-sync.sh` + `check-local.sh`.

## Remaining Functional Gaps

These are the genuinely-remaining items now that the enterprise floor has
shipped:

- Itinerary/tour update tools are deterministic and safer than free-form
  promises, but still basic; a later version should use schema-validated LLM
  rewriting with diff/rollback guards.
- The live per-WebSocket planning session (plan state + `active_constraints`) is
  in-memory and does not survive a reconnect; only explicitly **saved** trips
  persist to Postgres. Reusable per-user default constraints
  (`saved_constraints` table) are not yet wired to any handler.
- Budget is selection-aware and honest about missing prices, but it is not yet a
  full optimizer that searches all tradeoff combinations.
- Explainability covers ticket, flight, and hotel cards. Schedule and Explore
  explainability remain future work.
- Operate/scale items remain (Phase 5): error budgets, per-user storage quotas,
  audit log, custom domain, mobile/PWA polish, a Clerk `user.deleted` erasure
  webhook, scheduled uptime/alerting, and a cross-instance (Redis) rate limiter.
- Deploy-gate verification (T-001 / T-DEPLOY-VERIFY) is still pending; see the
  Deploy Verification Status section above.

## Next Engineering Priorities

1. Close the deploy gate: land the T-001 R10 verdict, then run T-DEPLOY-VERIFY
   (confirm the full E2E lane incl. saved-trips runs in CI, then drop the
   "verification pending" caveat from the README/roadmap/deployment-design).
2. Replace basic itinerary/tour text patching with schema-validated rewriting,
   diff preview, and rollback guards.
3. Add an Explainability panel v2 only if it can show a true runtime attempt
   trace rather than an inferred source path.
4. Begin the Phase 5 operate/scale items (per-user quotas, audit log,
   monitoring/alerting, account-deletion/erasure path).

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
