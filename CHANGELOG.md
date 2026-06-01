# Changelog

All notable user-visible changes to this project live here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Enterprise floor (Phase 4.7).** Real OAuth sign-in via Clerk (`@clerk/clerk-react`), Postgres-backed saved trips with SQLAlchemy + Alembic, Sentry error tracking on both backend and frontend, `/healthz` + `/readyz` endpoints, CSP/HSTS middleware in production, `railway.json` + `vercel.json` deploy configs, `gitleaks` secret-scan CI, and a fresh-machine deploy runbook in the README. The frontend falls back to demo-token mode for local dev when `VITE_CLERK_PUBLISHABLE_KEY` is unset, so existing E2E lanes keep running without external credentials.
- Selection-aware WebSocket quote previews. Choosing ticket, flight, or hotel cards now recomputes a selected total without mutating the saved plan.
- Quote completeness metadata. Unpriced selections produce an incomplete amber quote with pending categories instead of a false within-budget result.
- Structured `active_constraints` memory for direct-only flights, hotel brands, dietary needs, accessibility, avoid-luxury, and budget strategy.
- Persistent itinerary and tour refinement tools, so Schedule and Explore card edits can be written back to state.
- Provider/link metadata (`provider`, `link_type`, `booking_confidence`) for tickets, flights, and hotels.
- "Why this card?" explainability for ticket, flight, and hotel cards, including reasons, matched constraints, source path, and trade-offs.
- Backend feature-completion tests and CI execution of `python -m unittest discover -s tests -v`.
- Maintainer architecture map in `docs/architecture-map.zh-CN.md`, covering state flow, memory layers, quote semantics, hard constraints, explainability, and module boundaries.
- Synced, compact `AGENTS.md` / `CLAUDE.md` guidelines with a drift check script, tracked git hook templates, project skill install script, and Playwright browser smoke coverage.

### Changed
- Booking buttons now describe the real link type with the normalized `deeplink` / `search` / `homepage` contract, and arbitrary hotel websites are medium-confidence external provider sites rather than high-confidence booking links.
- Unpriced ticket/flight/hotel options are selectable, but selecting them marks the quote incomplete rather than treating missing price as zero.
- Lane 2 constraints now live outside the rolling conversation history, so hard constraints can survive multi-turn refinement.
- Explainability copy now says "source path" instead of implying a complete runtime attempt log.
- Frontend prototype structure is split into `components/` and `domain/` modules while preserving the current Vite + React app behavior.
- Backend planning agents are split into per-domain modules under `backend/agents/`, with `agents/__init__.py` kept as the public import facade.
- Refinement helpers are split so itinerary/tour editing and hard-constraint reconciliation no longer live inline inside `refine.py`.
- Saved-trip database operations now run off the event loop via `asyncio.to_thread`, so a slow Postgres round-trip no longer stalls other WebSocket sessions on the single-process backend.

### Fixed
- Quote validation rejects malformed selections, unknown categories, numeric strings, nulls, negative indexes, and out-of-range indexes while keeping the WebSocket open.
- Itinerary/tour update tools no longer accept LLM-supplied current-state JSON; they edit only the server-side session state captured by the tool closure.
- If the WebSocket is disconnected, frontend card selection no longer silently changes the UI budget; it shows a visible restart-planning message.
- Native date inputs now update React state on both input and change events, so automated and manual edits reliably trigger date validation before submit.
- Hard-constraint reconciliation now runs only when constraints change or transport/hotel data changes, avoiding unrelated chat turns that silently refresh result cards.
- Hotel brand filtering now uses canonical brand aliases rather than broad substring matching.
- Duplicate selected card indices are deduped before budget recomputation, and WebSocket `selections: null` is rejected explicitly.
- Transport quote selection no longer undercounts fallback one-way legs; mock fallback emits a single round-trip flight card and stale `LOCAL`-only transport selections are rejected.
- Plan input validation now rejects non-positive budgets and legacy `extra_days` values outside the 0-27 range.
- Direct-flight filtering now distrusts contradictory structured `stops: 0` fields when the visible card text says `1 stop`, `via`, `connection`, or `layover`.
- Extracted date inputs now capture event values before React state updates, preventing a `currentTarget` null crash during Browser Use/manual date edits.
- English Explore-card replacements using `Replace X with Y` now target the named tour item and put the replacement in the card title instead of only appending a note.
- Dev scripts now resolve `.venv/bin/python`, `python3.12`, `python3.11`, or `python3` instead of assuming a `python` executable exists.
- Refinement helper code is split out of `backend/refine.py` into state-update and deterministic-reply modules while preserving existing helper imports.
- `start.sh` is now a true one-command launcher with configurable ports, health checks, and child-process cleanup.
- **Railway deploy no longer crashes on boot.** `db.py` rewrites Railway's bare `postgresql://` `DATABASE_URL` to the installed psycopg3 driver (`postgresql+psycopg://`), so the engine builds instead of raising `ModuleNotFoundError: psycopg2`.
- **Database migrations now run at deploy time, not build time.** `railway.json` runs `alembic upgrade head` in the start command against the live Postgres; the build phase has no `DATABASE_URL`, where a migration would have silently targeted a throwaway SQLite and left production unmigrated.
- **Clerk sign-in works under the production CSP.** `worker-src 'self' blob:` and `https://challenges.cloudflare.com` (script-src + frame-src) are allowed in both `vercel.json` and the backend CSP, so the Cloudflare Turnstile bot-challenge and Clerk's web worker are no longer blocked.
- **Honest budget on a one-way-only flight set.** The baseline budget marks Flights incomplete when an outbound leg has no priced return, instead of showing a green within-budget total for a half-priced trip.
- **Honest budget when a hard constraint empties a category.** If a direct-only or hotel-brand constraint removes every priced flight/hotel, the quote is marked incomplete rather than reporting a green within-budget total with that category priced at 0.
- **Constraint extraction no longer misfires on neutral wording.** "What is my budget?" or mentioning the "Paddock Club" / a "premium ticket" no longer flips `avoid_luxury` / `budget_strategy`; only intent-bearing phrases do.
- **"Replace X with Y" no longer corrupts an unrelated card.** When the named target is absent from the itinerary/tour, the cards are left untouched instead of overwriting the first card and falsely reporting success.
- **Parallel provider search keeps partial results on timeout.** A single slow provider hitting the global deadline no longer discards already-completed results into a full mock fallback.
- **Saved trips restore the Schedule card.** The reload path reads the itinerary under its real `plan` zone key, so the Schedule card is no longer silently dropped on load.
- **WebSocket recovery.** A clean mid-plan disconnect now surfaces an honest message and unblocks the UI instead of leaving it stuck on "running"; a connect race can no longer open a second leaked socket or trip a false "Connection lost" on a healthy connection.
- **Stale selected quote no longer overwrites the restored baseline** after all cards are deselected.
- **Calendar grid degrades honestly.** A non-OK or non-array `/api/calendar` response is no longer stored verbatim (which left the grid stuck on "is backend running?").

### Security
- **Auth fails closed on misconfiguration.** A non-local deploy with neither Clerk nor a demo token configured now returns 503 instead of silently admitting every request as `demo-user`.
- **Transient Clerk JWKS outages return 503, not 500.** JWKS fetch failures serve a stale cached key when available, and otherwise surface a clean 503 (HTTP) / close (WS) instead of an unhandled 500 / handshake error.
- **Saved trips are isolated per identity on real deploys.** The shared `demo-user` sentinel can no longer own persisted trips in a non-local environment (backend guard + the frontend hides SAVE / MY TRIPS when Clerk is absent), preventing cross-visitor read and delete.
- **Rate limiting hardened.** Per-IP limits key off the trusted right-most `X-Forwarded-For` hop (a forged left-most hop can no longer mint fresh buckets) and run before authentication so failed-auth floods are counted.
- **Fail-fast on missing `ALLOWED_ORIGINS`.** A non-local deploy refuses to start with an empty origin allowlist instead of silently breaking frontend CORS while disabling the WebSocket Origin gate.
- **Interactive API docs disabled on real deploys.** `/docs`, `/redoc`, and `/openapi.json` are off outside local dev — no unauthenticated schema exposure and no CSP-broken blank pages.

## [0.3.0] — 2026-04-20

First tagged release. Captures everything shipped from the initial multi-agent demo through the hardening round that made the product trustworthy end-to-end.

### Added

#### Planning and refinement
- **Currency selector** on the planning form with three choices — EUR, USD, CNY. The selected currency drives the budget breakdown, the estimated total, and supervisor replies. Individual result cards keep the source currency returned by each provider (e.g. a flight quoted in USD stays labeled USD), which preserves traceability to the external booking source.
- **Editable depart / return date pickers**. Users can pick any valid arrival and departure date; the old "extra days after race" slider has been removed. Client-side validation blocks impossible input (depart on/after return, >30 nights, bad format) and warns about unusual choices (arriving after the race, leaving before it).
- **Grounded refine replies**. After any chat action that runs a tool, the reply is built deterministically from the final saved plan and budget — never from the language model's self-report. Users no longer see claims like "new total USD 349" when the real budget is 2441.
- **Debug mode** (`?debug=1` URL flag). Enables a copy-able trace panel that receives backend events (`state_apply`, `tool_fail`, `budget_final`) so developers can see exactly what happened during a planning or refine run.

#### Data and display
- Per-zone **ticket search disambiguation** (22 F1 circuits) so Austrian GP no longer gets confused with Australian GP.
- Unpriced flight and hotel options now show **"Price not provided"** with an optional "Check →" link to the provider instead of a misleading "USD 0". They are excluded from the budget total and surfaced in a footnote like "2 options without prices excluded".
- Fallback mocks for transport and itinerary **respect the real trip context** — the user's actual city, dates, and trip length — so when a real API fails the user doesn't see Milan/Monza content for a Baku trip.

#### Operations
- **Continuous integration** on GitHub Actions — backend compile and frontend build run on every push and pull request, structured so tests / lints / deploy can be added as new steps later without a rewrite.
- **Dated log files** (`backend/logs/backend_YYYY-MM-DD.log`) replace the single `backend.log`.
- **Two-terminal dev workflow scripts** under `scripts/` (start backend, start frontend, stop, status) that work under Windows Git Bash.
- Dev server ports unified to `8001` (backend) and `3000` (frontend with strictPort).
- FastAPI lifespan-driven logging — library imports no longer create log files as a side effect.

### Changed
- Flights are now single-select. Activities / sightseeing are display-only. Both were previously multi-select; the actual booking links didn't support per-item bookings, so the old UI was misleading.
- Form text fields consolidated: the separate "Stops along the way" input was merged into a single special-requests textarea that accepts stops, dietary notes, accessibility, and experience preferences together.
- Day-trips (same-day depart and return) are rejected at both client and API boundary with a clear message. At least one night is required until a first-class day-trip mode is added.
- Public docs and code comments no longer contain internal review vocabulary.

### Fixed
- Refine replies no longer invent or misstate budget numbers or declare changes that didn't persist.
- `_handle_chat` now uses copy-on-write for the session plan state, so an exception mid-refine can no longer leave the session with a half-updated plan.
- Invalid input (unsupported currency, non-object payloads, reversed or malformed dates) returns a clean 400 / WebSocket error without closing the socket, so users can correct and retry.
- `frontend/package-lock.json` refreshed so `npm ci` (which CI uses) resolves cleanly on Linux — the previous lockfile was missing a WASM runtime transitive dep and had a stale root package name that passed `npm install` but failed `npm ci`.

## [0.2.0]

### Added
- Real external data sources: SerpAPI Google Flights and Google Hotels, Firecrawl for F1 ticket pages, with graceful three-layer fallback (real API → LLM estimation → mock).
- Supervisor agent for chat-based refinement (Lane 2), routed through `/ws` alongside the fixed planning DAG (Lane 1). Session-level conversation memory keeps multi-turn context separate from plan state.
- Disk-backed cache with time-to-live for external tool calls.

## [0.1.0]

### Added
- Initial multi-agent planning graph (seven agents, parallel fan-out) with all agents returning mock data end-to-end.
- FastAPI backend and a React prototype frontend.
- First pass of the F1 Paddock Club UI theme — dark palette, pixel-art concierge, per-station accent colors.

[Unreleased]: https://github.com/f4dszz/f1-paddock-club/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/f4dszz/f1-paddock-club/releases/tag/v0.3.0
