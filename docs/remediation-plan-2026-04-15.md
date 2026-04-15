# Remediation Plan

Date: `2026-04-15`

## Scope

This plan covers the issues identified in the current project state:

- frontend dependency and local build setup are under-documented
- backend and frontend port defaults are inconsistent
- logging exists but is too thin and not operationally visible enough
- automated tests are effectively absent
- trip date selection and date derivation are too simplistic
- the current post-plan chat flow adds friction for users

## Current Confirmed State

- Frontend dependencies install successfully with `npm install`
- Frontend production build succeeds with `npm run build`
- The current Vite toolchain requires Node.js `^20.19.0 || >=22.12.0`
- README and `README.zh-CN.md` now document the frontend prerequisites and the Windows PowerShell `npm.cmd` workaround
- Port wiring is still inconsistent across `frontend/vite.config.js`, `backend/main.py`, and `start.sh`
- `backend/tests/` has no actual test coverage yet
- `backend/logging_config.py` creates `backend/logs/backend.log`, but logging is still single-file and low-context

## Priority Order

1. Stabilize local development and connectivity
2. Improve observability and diagnostics
3. Fix date correctness and user-facing trip-date behavior
4. Simplify chat interaction so the UI is less ambiguous
5. Add a minimal but real automated test baseline

## Planned Changes

### 1. Environment and Port Unification

Goal:
- remove the `8000` vs `8001` split so frontend, backend, scripts, and docs all agree

Changes:
- choose one backend default port for all entry points and scripts
- update `frontend/vite.config.js` proxy target to that single backend port
- update `backend/main.py` local run default to the same port
- update `start.sh` and `scripts/dev-backend.sh` to the same port contract
- document the final port map in both READMEs
- add one simple health-check step to the startup instructions

Expected outcome:
- no more “frontend and backend look up but cannot connect” caused by mismatched defaults

### 2. Logging and Diagnostics Upgrade

Goal:
- make failures debuggable without reading scattered console output

Changes:
- keep file logging, but add clearer startup logs for port, environment, and log path
- split operational context more explicitly in log lines:
  - request id or session id
  - WebSocket connect/disconnect
  - plan start/finish
  - chat start/finish
  - tool call start/finish/fallback
- add structured error logging around WebSocket message handling
- add a lightweight frontend-side logging strategy:
  - keep user-visible debug panel optional
  - standardize event names
  - reduce noisy duplicate messages
- document where logs live and what each log stream is for

Expected outcome:
- easier reproduction of connection, date, and refinement issues

### 3. Test Baseline

Goal:
- add a small but meaningful safety net before changing logic

Changes:
- add backend unit tests for:
  - `compute_trip_dates()`
  - race-calendar helpers
  - budget recomputation
  - WebSocket message routing helpers where practical
- add a frontend smoke check at minimum build level
- add a documented test command set in README
- if practical in this repo phase, add `pytest` configuration and at least one CI-friendly test entry point

Expected outcome:
- future fixes to dates, ports, and refinement behavior can be verified quickly

### 4. Date Logic Correction

Goal:
- stop treating trip dates as a rough slider-derived guess and make them explicit and correct

Current issues to address:
- the frontend only exposes derived read-only depart/return dates
- the current logic assumes arrival on Friday and return after `extraDays`, which is too rigid
- frontend date derivation is duplicated locally instead of relying on one canonical source
- chat/refinement does not clearly expose or preserve user-intended travel dates

Changes:
- make trip dates first-class values in state, not just derived display fields
- define a single contract for:
  - race weekend arrival date
  - hotel check-in/check-out
  - outbound and return flight dates
- move frontend date defaults to server-backed canonical logic where possible
- let the user explicitly adjust dates instead of only adjusting `extraDays`
- validate date ranges against the chosen GP date
- make backend tools consistently consume the same date object/fields

Expected outcome:
- date behavior becomes predictable, editable, and consistent across agents and tools

### 5. Chat UX Simplification

Goal:
- reduce hesitation and ambiguity after the first plan is generated

Current issues to address:
- the UI currently has a planning flow plus a separate refine chat area
- users may not know whether to restart, refine, or select from multiple interaction paths
- the current chat affordance is narrow and appears late in the flow

Changes:
- review whether the current “plan first, then refine in chat” split should become one clearer primary action path
- reduce secondary actions that force the user to choose between similar options
- improve empty-state and post-result copy so the user knows the next best action immediately
- tighten the backend reply flow so chat updates are clearer about what changed and what did not
- remove or demote UI elements that do not materially help user decisions

Expected outcome:
- one obvious next step for the user at each stage instead of multiple competing paths

### 6. Documentation Cleanup

Goal:
- keep setup and troubleshooting docs aligned with the actual repo state

Changes:
- keep the new frontend prerequisites in both READMEs
- add explicit Windows notes for `npm.cmd`
- document the unified port contract
- document test commands once tests exist
- add a short troubleshooting section for:
  - frontend cannot connect to backend
  - `npm.ps1` execution-policy issue
  - missing backend log file before first startup

## Implementation Sequence

### Phase A

- unify ports across code, scripts, and docs
- add startup and connection diagnostics
- verify manual local startup end-to-end

### Phase B

- add backend tests for dates and budget logic
- improve logging context around planning and chat

### Phase C

- refactor date handling into a canonical shared model
- update frontend date UI from read-only derived fields to editable validated fields

### Phase D

- simplify chat/refinement UX and related backend messaging
- trim or rework confusing secondary UI actions

## Acceptance Criteria

- frontend can be installed and built locally from documented steps
- frontend and backend connect reliably with one default port contract
- logs are created automatically and contain enough context to trace one user session
- backend has real tests covering date and budget logic
- users can understand and control trip dates without relying only on an `extraDays` slider
- the post-plan interaction has one clear primary refinement path

## Files Expected To Change In The Follow-Up Implementation

- `frontend/vite.config.js`
- `frontend/prototype.jsx`
- `frontend/package.json`
- `backend/main.py`
- `backend/logging_config.py`
- `backend/graph.py`
- `backend/refine.py`
- `backend/tools/_trip_dates.py`
- `backend/tools/_race_calendar.py`
- `scripts/dev-backend.sh`
- `start.sh`
- `README.md`
- `README.zh-CN.md`
- `backend/tests/*`

## Notes

- This document records the implementation plan only. It does not claim the functional fixes are already complete.
- `frontend/package-lock.json` changed locally during verification because dependencies were installed, but that is not part of this documentation-only plan commit.
