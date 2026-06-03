# F1 Paddock Club — Agent Guide

This file is the project-level guide for Codex, Claude Code, and other coding
agents. `AGENTS.md` and `CLAUDE.md` must stay byte-for-byte identical; run
`./scripts/check-agent-doc-sync.sh` before pushing.

## Purpose

F1 Paddock Club is a multi-agent travel assistant for Formula 1 race weekends.
It is also a portfolio/interview project for showing practical agent
orchestration:

- Lane 1: a fixed LangGraph DAG for initial planning.
- Lane 2: a ReAct supervisor for targeted refinements.
- Shared state and shared tools across both lanes.
- Graceful fallback to honest mock/estimate data when external APIs fail.

Historical design notes, long roadmaps, audit notes, and presentation material
belong in `docs/`, not in this file. Keep this guide compact and operational.

## Current Architecture

- Backend: Python, FastAPI, LangGraph, LangChain.
- Frontend: Vite + React.
- Data providers: SerpAPI, Firecrawl, LLM estimates, mock fallback.
- Streaming: FastAPI WebSocket at `/ws`.
- Frontend dev server: Vite on `:3000`, proxying `/api` and `/ws` to backend `:8001`.

Key backend entry points:

- `backend/main.py`: HTTP and WebSocket API boundary.
- `backend/graph.py`: Lane 1 planning DAG.
- `backend/refine.py`: Lane 2 supervisor orchestration.
- `backend/state.py`: shared state schema.
- `backend/tools/`: shared tool layer.
- `backend/agents/`: graph node agents.

Key frontend entry points:

- `frontend/prototype.jsx`: app orchestration, WebSocket handling, page composition.
- `frontend/components/`: render-focused UI pieces.
- `frontend/domain/`: pure transform/display/date rules.

## Run And Verify

One-time setup:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env

cd ../frontend
npm ci
cd ..
```

Start both services:

```bash
./start.sh
```

Day-to-day two-terminal workflow:

```bash
./scripts/dev-backend.sh
./scripts/dev-frontend.sh
```

Full local verification:

```bash
./scripts/check-local.sh
./scripts/e2e-local.sh
```

Useful service checks:

```bash
curl http://127.0.0.1:8001/api/calendar
curl http://localhost:3000/api/calendar
./scripts/dev-status.sh
./scripts/dev-stop.sh
```

## Agent Working Rules

- Make existing code run before adding new behavior.
- Follow the current phase order in `docs/current.md`.
- Keep mock data as a permanent graceful-degradation path.
- Prefer shared tools in `backend/tools/` over duplicating provider logic in agents.
- Keep Lane 1 and Lane 2 behavior consistent by sharing state and tool contracts.
- Accounts and persistence have shipped by user request (Phase 4.7 enterprise
  floor: Clerk OAuth + Postgres-backed saved trips). Do not add *new* surfaces
  of this kind — payments, broader account features, or additional persisted
  data — unless the user explicitly asks. Keep the existing scope minimal.
- `DEMO_ACCESS_TOKEN` is demo abuse gating; Clerk JWT verification is the real
  production authentication. The frontend falls back to demo-token mode for
  local dev when Clerk is unconfigured.
- No `Co-Authored-By` or AI attribution in commit messages.

## Code Quality Rules

- Use structured parsers and typed helpers where practical.
- Keep behavior changes small and covered by focused tests.
- Do not rewrite architecture when a targeted fix is enough.
- Do not silently discard provider failures; expose honest source/degradation metadata.
- UI booking links must not imply confirmed purchase. Search/homepage links need honest copy.
- Budget recomputation must be side-effect-free for quote previews.
- Any selected unpriced item must produce an incomplete quote, not a green total.

## Skills, Hooks, And Subagents

Repo-local `skills/` folders are shared source/reference files. They are not
loaded by Codex automatically from this repo, and this project does not write
to `${CODEX_HOME:-~/.codex}`. Install or sync local skills outside the repo only
when a developer explicitly wants that local machine state.

Git hook templates live in `.githooks/` and are versioned. They are active only
after running:

```bash
./scripts/install-hooks.sh
```

Subagents are a runtime capability, not a repo artifact. Do not encode a plan
that requires subagents unless the current host/user explicitly allows them.
When subagents are unavailable, use local code inspection and scripts instead.

## Documentation Growth Policy

This file should stay around 200-300 lines. Add only durable operating rules.
Do not append long project history, implementation diaries, interview notes, or
one-off audit logs here.

Use these destinations instead:

- `docs/current.md`: current status, verification summary, near-term gaps.
- `docs/architecture-lessons.md`: durable design lessons.
- `docs/phase3-architecture-decision.md`: historical architecture rationale.
- `docs/e2e-smoke-matrix.zh-CN.md`: regression matrix.
- `docs/intelligence-roadmap.md`: future intelligence features.
- `CHANGELOG.md`: shipped behavior changes.

## Current Priority

Phase 4 (including the 4.7 enterprise floor — Clerk OAuth, Postgres-backed saved
trips, Sentry, `/healthz` + `/readyz`, CSP/HSTS, gitleaks, and Vercel + Railway
deploy config) has shipped. The deploy **config** is committed but the end-to-end
deploy **gate** is still being verified (`T-001` awaiting reviewer verdict,
`T-DEPLOY-VERIFY` planned); treat deploy as "config shipped, verification
pending". The next milestone is closing that gate and the Phase 5 operate/scale
items — not a framework rewrite. See `docs/current.md` for the canonical
shipped-vs-pending breakdown.
