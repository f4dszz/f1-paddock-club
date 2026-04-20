# Changelog

All notable user-visible changes to this project live here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet. Changes in progress will land here before the next tagged release._

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
