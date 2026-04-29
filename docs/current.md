# Current Project Status — 2026-04-27

This note records the latest local repo state, runtime verification, browser
E2E results, and next engineering priorities for the F1 Paddock Club web app.
It intentionally excludes personal interview-prep notes.

## Repo Freshness

- Current branch: `main`.
- Upstream: `origin/main`.
- `git fetch origin main` completed successfully.
- `HEAD...origin/main` is `0 0`, so local `main` is up to date with upstream.
- Latest commit on both local and upstream: `9482e2b Revise deployment design: backend access gate, WS realities, cache`.
- No `git pull` was needed.

## Git / Docs Tracking

Tracked project docs under `docs/`:

- `docs/architecture-lessons.md`
- `docs/batch3-plan-v3.md`
- `docs/debug-trace-productization.zh-CN.md`
- `docs/deployment-design.md`
- `docs/deployment-design.zh-CN.md`
- `docs/e2e-smoke-matrix.zh-CN.md`
- `docs/phase3-architecture-decision.md`
- `docs/current.md`

Untracked local notes that should not be added without explicit approval:

- `docs/aia-interview-cheatsheet.md`
- `docs/aia-mock-interview-fullset.md`
- `docs/anti-drift-playbook.zh-CN.md`
- `AGENTS.md`

Project config documentation that should be tracked:

- `frontend/.env.example`

## Local Runtime State

- Backend runs on `127.0.0.1:8001`.
- Frontend runs on `127.0.0.1:3000`.
- `.env` is recognized by the backend. Secret values were not printed.
- The backend is currently configured for local/dev operation unless deployment
  env variables such as `APP_ENV`, `DEMO_ACCESS_TOKEN`, and `ALLOWED_ORIGINS`
  are set.

## Implemented Hardening / Stabilization

- Backend access gate added for deployed/demo environments:
  - HTTP endpoints accept `Authorization: Bearer <DEMO_ACCESS_TOKEN>`.
  - WebSocket accepts `?demo_token=<DEMO_ACCESS_TOKEN>`.
  - Missing or invalid token is rejected outside local/dev mode.
- CORS is now env-driven via `ALLOWED_ORIGINS`; local dev defaults to
  `http://localhost:3000` and `http://127.0.0.1:3000`.
- WebSocket origin gate and connection-rate protection were added.
- Basic in-process HTTP rate limiting and plan concurrency limiting were added.
- Frontend supports `VITE_BACKEND_URL`, `VITE_WS_URL`, and `VITE_DEMO_TOKEN`.
- Frontend token logging is redacted.
- Default trip-date generation now avoids timezone drift. In the current
  Europe/Madrid environment, Monza defaults to `2026-09-04` -> `2026-09-09`.
- `frontend/package-lock.json` was updated by `npm audit fix`; `postcss`
  advisory is no longer present.
- Dev scripts were made macOS-compatible while preserving Windows/Git Bash
  behavior.

## Verification Summary

Build and dependency checks:

- `backend/.venv/bin/python -m compileall -q backend` passed.
- `npm run build` in `frontend/` passed.
- `npm audit --audit-level=moderate` reported `0 vulnerabilities`.

HTTP and WebSocket checks:

- `/api/calendar` returns the 2026 GP calendar.
- `/plan` rejects invalid currency `JPY` with HTTP `400`.
- `/plan` rejects `depart_date >= return_date` with HTTP `400`.
- `/plan` rejects non-object JSON with HTTP `422`.
- WebSocket invalid JSON returns an error event.
- WebSocket unknown message type returns an error event.
- WebSocket oversized message returns an error event.
- Production-mode HTTP auth test:
  - no token -> `401`
  - bad token -> `401`
  - valid token -> `200`
- Production-mode WebSocket token test:
  - no token -> close `1008`
  - bad token -> close `1008`
  - valid token -> accepted
- Production-mode WebSocket origin test:
  - allowed origin -> accepted
  - blocked origin -> close `1008`

Date-range checks:

- Default Monza browser dates are correct: `2026-09-04` -> `2026-09-09`.
- Backend custom-date validation accepts `2026-09-03` -> `2026-09-10`.
- `compute_trip_dates()` maps that custom range to:
  - outbound: `2026-09-03`
  - return: `2026-09-10`
  - hotel check-in: `2026-09-03`
  - hotel check-out: `2026-09-10`
  - nights: `7`
- Mock transport and hotel fallbacks also reflect the custom dates and nights,
  confirming downstream date propagation at the shared helper layer.

Browser E2E checks:

- Browser-driven normal flow completed for Italian GP / Monza.
- Test input:
  - origin: `Shanghai`
  - budget: `CNY 30000`
  - stand preference: `Mid`
  - depart / return: `2026-09-04` -> `2026-09-09`
  - special requests: vegetarian food, wheelchair-accessible hotel, direct
    flight preference, avoid luxury hotels, Milan food stop, avoid very early
    departures
- Initial plan completed with all five zones marked `DONE`.
- Initial total was `CNY 65653 / CNY 30000`, over budget.
- Flight tool timed out for one source and fell back to mock for the initial
  Shanghai search, which kept the flow alive.
- Multi-round chat refinement worked:
  - Cheaper ticket / flight refinement updated tickets and flights, reducing
    total to `CNY 24171 / CNY 30000`.
  - Marriott/Hilton hotel refinement updated hotel options and kept total within
    budget.
  - Prompt-injection request for system prompt, API keys, hidden policies, raw
    tool JSON, and environment variables was refused without leaking secrets.

## Known Issues Found

- Budget optimization is not a hard global optimizer. The initial plan stayed
  over budget until the user explicitly asked for cheaper ticket and flight
  options.
- Strict filtering is incomplete. A request for "only direct flights" returned
  a mixed list with mostly 1-stop flights plus one unpriced direct option.
- Hotel brand filtering is also soft. A request for Marriott/Hilton returned a
  mixed list that included Hilton/Marriott and non-brand nearby/budget options.
- No-tool chat replies can overclaim. An itinerary refinement request produced
  a reply saying the itinerary was updated, while the backend logged no state
  changes and the schedule cards did not change.
- Budget calculation is not selection-aware enough. It appears based on
  available priced options rather than the user's explicit card selections,
  which can confuse users when some cards are unpriced.
- Tool fallback visibility is weak. The backend logs source degradation, but
  the frontend does not clearly show when SerpAPI/Firecrawl/LLM paths fall back
  to estimates or mock data.
- Browser automation could confirm default date values, but direct manipulation
  of native date inputs through the accessibility layer was unreliable. Backend
  and shared-helper tests cover custom-date validity and propagation.

## Interview-Quality Project Framing

This project is best described as an agentic workflow product, not only an F1
travel demo.

- Lane 1 is a deterministic LangGraph DAG for initial planning. It gives clear
  control flow, parallel fan-out, retry behavior, and predictable state writes.
- Lane 2 is a ReAct-style supervisor for natural-language refinement. It avoids
  rerunning the full pipeline when the user only wants hotels, flights, tickets,
  or budget recalculation changed.
- Both lanes share one `TravelPlanState` and one tools layer, which keeps data
  contracts centralized.
- External-data tools degrade through real API, LLM estimate, and mock fallback,
  so the product remains usable even when providers fail.
- The main tradeoff is flexibility versus guarantees: LLM-driven refinement is
  convenient, but strict constraints need deterministic post-filters and
  persisted state-change checks.

## Next Engineering Priorities

1. Fix no-tool itinerary refinement so the app cannot claim unpersisted changes.
   Either implement itinerary mutation or reply honestly that itinerary edits
   are not yet persisted.
2. Add strict post-filtering for direct flights, hotel brand constraints, and
   budget ceilings.
3. Make budget calculation selection-aware and explain how unpriced options are
   excluded.
4. Surface tool source and fallback status in the frontend planning trace and
   result cards.
5. Extend CI beyond compile/build with at least one backend smoke test, one
   WebSocket boundary test, and one dependency/security scan.
6. Keep Phase 4.3 hardening as the next main batch before adding new features.
