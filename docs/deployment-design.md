# Deployment Design

> **Status: IMPLEMENTED as of Phase 4.7 (enterprise floor).** This was originally
> a design doc; the design has since been built. `vercel.json`, `railway.json`,
> and `.github/workflows/deploy-smoke.yml` are committed, and the enterprise
> floor went further than this doc's original "no accounts / no database" scope:
> Clerk OAuth, Postgres (SQLAlchemy + Alembic), Sentry, `/healthz` + `/readyz`,
> and CSP/HSTS all shipped. The authoritative, step-by-step deploy runbook now
> lives in the README **"Deploy from scratch (Vercel + Railway + Clerk + Sentry)"**
> section and in
> `docs/superpowers/specs/2026-05-27-enterprise-floor-design.md`. This document is
> retained as the predecessor rationale (target comparison, CORS/Origin, token
> model, concurrency, disk-state limits) plus the new backup/restore section
> ([Section 13](#13-database-backup-pitr-and-restore)). Sections that described
> the pre-enterprise-floor state are annotated inline where they are now
> superseded.
>
> _Deploy-gate verification is still pending: the `T-001` deterministic-E2E review
> and the `T-DEPLOY-VERIFY` gate are in progress, so treat the deploy as
> "config shipped, end-to-end gate verification pending" rather than fully signed
> off._

_This document is the production-readiness design for getting the F1 Paddock Club out of a local demo and onto public hosting._

_中文版在 [`deployment-design.zh-CN.md`](./deployment-design.zh-CN.md)。_

The original scope was deliberately narrow (search-provider expansion, mobile/PWA polish, session persistence, and user accounts were all deferred; see [Out of scope](#12-out-of-scope)). **Note:** the enterprise floor (Phase 4.7) has since added user accounts (Clerk OAuth) and persistence (Postgres-backed saved trips), so those two "out of scope" items are now implemented — the [Out of scope](#12-out-of-scope) list is annotated accordingly.

## 1. Current runtime assumptions

> **Superseded note.** This section describes the *pre-enterprise-floor* runtime.
> Since Phase 4.7 the system additionally has Clerk auth, a Postgres database
> (SQLAlchemy ORM in `backend/models.py`, Alembic migrations, CRUD in
> `backend/repository.py`), Sentry + structured logging (`backend/observability.py`),
> `/healthz` + `/readyz` probes, a CORS **allowlist** (not `["*"]`), and CSP/HSTS
> middleware in production. Read the items below as the historical baseline; the
> corrections are called out inline.

The system as it runs today. The design below either preserves or replaces each of these cleanly.

### Processes

- **Backend**: FastAPI + Uvicorn on `127.0.0.1:8001`. Two surfaces — `/plan` (HTTP POST), `/ws` (WebSocket). State lives per WebSocket connection in in-process memory (`session = create_session()` in `main.py`). _**Superseded:** a Postgres database now backs saved trips and user profiles (`backend/db.py`, `backend/models.py`, `backend/repository.py`); per-WebSocket in-memory state is still used for the live planning session, but durable saved trips persist to Postgres._
- **Frontend**: Vite dev server on `localhost:3000`, serving `prototype.jsx` as a React app. Production build (`npm run build`) emits a plain static bundle in `frontend/dist/`.

### Dev-time topology — implicit same-origin

The frontend has no notion of "which backend to talk to":

```js
const API_BASE = "";
const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;
```

Calls go to the same host that served the page. In development this works because `vite.config.js` proxies `/api/*` and `/ws` to the backend. The assumption breaks the moment frontend and backend are hosted on different origins; [Section 4](#4-runtime-url--topology-assumptions-production-critical) explicitly addresses that.

### Secrets

`backend/.env` holds `OPENAI_API_KEY`, `SERPAPI_API_KEY`, `FIRECRAWL_API_KEY`, `LLM_PROVIDER`. It is gitignored. `backend/.env.example` documents the expected variables. No frontend-side secrets exist today.

### CORS

> **Superseded:** CORS is no longer `["*"]` in production. `backend/main.py` now
> reads an explicit allowlist from `ALLOWED_ORIGINS`, falls back to
> `http://localhost:3000` only in local dev, and a non-local deploy
> **fails fast** (refuses to start) if `ALLOWED_ORIGINS` is empty. The design
> below is what was built.

The original local default was wide open in `backend/main.py`:

```python
CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
```

The `tighten in production` comment was the debt this document paid down — now realized as the allowlist in [Section 6](#6-cors-and-websocket-origin).

### WebSocket message loop

The handler is a serial receive loop:

```python
while True:
    raw = await ws.receive_text()
    if msg_type == "plan":
        await _handle_plan(ws, msg_data, session)
    elif msg_type == "chat":
        await _handle_chat(ws, msg_data, session)
```

Because `_handle_plan` is awaited before the next `receive_text`, **a single WebSocket connection cannot process two plans in parallel**. Any second `plan` message waits in the socket buffer until the first finishes. This is relevant to [Section 8](#8-concurrency-and-rate-limiting).

### Disk-backed state

Two directories are written to local disk during normal operation:

- `backend/logs/backend_YYYY-MM-DD.log` — runtime logs
- `backend/tools/.cache/` — time-bound caches for SerpAPI / Firecrawl results

Both are gitignored. Both sit on whatever filesystem the backend process runs on — fine on a developer laptop, **ephemeral on the platforms this design targets**. Section 9 covers what that means.

### Concurrency today

No rate limiting. No per-session lock. No global concurrency cap. The only inbound-size limit is `MAX_WS_MESSAGE_SIZE = 16 * 1024`. A single user holding an open WebSocket can issue as many `plan` messages as they want (though they run sequentially; see above).

## 2. Deployment target comparison

Three realistic options, compared against seven productization criteria.

| Criterion | Vercel (frontend) + Railway (backend) | Fly.io single platform | Self-managed VPS |
|---|---|---|---|
| Static frontend hosting | Native; global CDN, instant | Possible via static services | Manual (Nginx or similar) |
| WebSocket long connection | Backend on Railway is native; Vercel's own functions impose limits | Native; persistent processes | Native; configure Nginx `proxy_read_timeout` |
| Python backend deploy friction | Railway auto-detects `requirements.txt`; `git push` deploys | Dockerfile required; `fly launch` generates one | Full stack to write (Dockerfile, systemd, TLS cert) |
| Env / secret management | Two dashboards — Vercel env vars for frontend, Railway secrets for backend | One dashboard | Manual `.env` files, secret injection via CI or operator |
| Logs / rollback / observability | Each platform ships a log viewer and per-revision rollback | Same on one platform | Ship your own (journalctl + SSH, or Grafana/Loki) |
| Cold start on free tier | Vercel never cold-starts static; Railway Hobby keeps a small service continuously running as long as included usage isn't exceeded | Fly has scale-to-zero; wake-up is 1–5 s | Always warm if the VM is on; you also always pay |
| Operational cognitive load | Two platforms, but each simple | One platform, slightly more concepts | Highest — OS patches, cert renewal, monitoring are yours |

### Recommendation

**Vercel + Railway** is the chosen target for this phase.

Reasons:

1. The shape matches the app — static React on a CDN, long-running FastAPI behind HTTPS with native WebSocket support.
2. Free-tier economics are realistic for a portfolio-stage project. Vercel's static tier is essentially unlimited; Railway's Hobby plan includes $5 of usage per month, which is likely enough for a small continuously-running demo. **Actual consumption depends on CPU, memory, and egress — monitor usage during the first week after deploy; do not treat $5 as an indefinite guarantee.**
3. `git push` triggers platform-side build and deploy on both, with per-deploy rollback available from the dashboard.

**Fly.io** is a legitimate alternative — one platform, a good free tier, a cleaner mental model. The only reason it is not the first pick is the Dockerfile / `fly.toml` learning curve, which is extra complexity this repo doesn't need today. If Railway pricing ever becomes a problem, migrating to Fly is a week-sized job.

**Self-managed VPS** is rejected for this phase. The operational surface (TLS renewal, OS updates, log shipping, monitoring) is not something worth taking on while the product itself is still moving.

## 3. Minimum deployment architecture

```
┌────────────────────┐       HTTPS (static)       ┌─────────────────────────┐
│  User browser      │ ─────────────────────────▶ │  Vercel CDN             │
│                    │                            │  (prototype.jsx build)  │
│                    │                            └─────────────────────────┘
│                    │       HTTPS: POST /plan    ┌─────────────────────────┐
│                    │ ─────────────────────────▶ │  Railway                │
│                    │         WSS: /ws           │  FastAPI + Uvicorn      │
│                    │ ─────────────────────────▶ │  (backend process)      │
└────────────────────┘                            └─────────────────────────┘
                                                         │
                                                   (outbound)
                                                         │
                                                         ▼
                                          OpenAI / SerpAPI / Firecrawl
```

- Frontend bundle served by Vercel's CDN.
- Backend is a single Railway service running `uvicorn main:app`. Same-process FastAPI serves both REST `/api/*` routes and the WebSocket at `/ws`. _**Superseded:** the Railway start command now runs `alembic upgrade head` before `uvicorn`, applying migrations against the live Postgres at deploy time._
- All external-provider traffic (OpenAI, SerpAPI, Firecrawl) flows outbound from Railway. The frontend never sees or embeds those keys.
- _**Superseded:** the enterprise floor added a Railway **Postgres addon** for durable saved trips + user profiles. The original "no database" assumption held only for the pre-4.7 demo; per-WebSocket in-process state still drives the live planning session, but saved trips now persist. There is still no separate cache layer or queue._

## 4. Runtime URL / topology assumptions (production-critical)

### Problem

The current frontend derives the backend URL from its own page host:

```js
const WS_URL = `${...}://${window.location.host}/ws`;
```

In production the frontend is at something like `f1-paddock-club.vercel.app` and the backend is at `f1-paddock-club-backend.up.railway.app`. The page cannot talk to its own host for the API; it has to address the backend explicitly.

### Decision

Introduce two build-time environment variables for the frontend:

- `VITE_BACKEND_URL` — e.g. `https://f1-paddock-club-backend.up.railway.app`
- `VITE_WS_URL` — e.g. `wss://f1-paddock-club-backend.up.railway.app/ws`

At runtime the frontend prefers these when set, and falls back to the current `window.location` derivation for local development:

```js
const BACKEND =
  import.meta.env.VITE_BACKEND_URL ||
  window.location.origin;          // dev: Vite proxy handles /api/*

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

fetch(`${BACKEND}/api/calendar`);
new WebSocket(WS_URL);
```

Vercel sets these two variables at build time; they land in the emitted JS bundle. **They are public values, not secrets** — exposing them in the bundle is expected and safe.

### Why not a Vercel rewrite proxy?

Vercel can rewrite `/api/*` on the edge to Railway, which would preserve the same-origin illusion. Rejected because:

- Rewrite rules don't proxy `wss://` — WebSockets would still need a direct URL.
- It adds a hop with no meaningful benefit at this scale.

Direct cross-origin is simpler and more honest about the topology.

### Dev vs production

| | Dev | Production |
|---|---|---|
| Backend URL | Vite proxy to `127.0.0.1:8001` | Explicit `VITE_BACKEND_URL` |
| WS URL | Same host + Vite ws proxy | Explicit `VITE_WS_URL` |
| Origin | `http://localhost:3000` | `https://<vercel-domain>` |
| CORS on backend | Permissive `["*"]` | Strict allowlist (Section 6) |

## 5. Environment, secrets, and configuration

### Inventory

| Variable | Where it lives | Who reads it | Secret? |
|---|---|---|---|
| `OPENAI_API_KEY` | Railway env | backend (`llm.py`) | **Yes** |
| `ANTHROPIC_API_KEY` | Railway env | backend (`llm.py`) | **Yes** |
| `SERPAPI_API_KEY` | Railway env | backend (`tools/search_*.py`) | **Yes** |
| `FIRECRAWL_API_KEY` | Railway env | backend (`tools/search_tickets.py`) | **Yes** |
| `LLM_PROVIDER` | Railway env | backend | No |
| `LOG_LEVEL` | Railway env | backend | No |
| `ALLOWED_ORIGINS` | Railway env | backend (`main.py` CORS / Origin check) | No |
| `DEMO_ACCESS_TOKEN` | Railway env | backend (demo token gate, Section 7) | **Yes** |
| `VITE_BACKEND_URL` | Vercel build env | frontend bundle | No; public by design |
| `VITE_WS_URL` | Vercel build env | frontend bundle | No; public by design |
| `VITE_DEMO_TOKEN` | Vercel build env | frontend bundle | No; intentionally baked into public bundle (see Section 7) |

### Rules

1. **Secrets never enter the frontend bundle.** Anything prefixed `VITE_` is, in effect, published — only non-secret values go there.
2. **Secrets never enter the git repository.** `.env` is gitignored; `.env.example` documents shape without values.
3. **Dev and production do not share secrets.** The OpenAI key on Railway is a production-only key; developer machines use their own `.env`.
4. **Config hierarchy**: `backend/.env.example` (in git, documents shape) → `backend/.env` (local, gitignored) → Railway environment (production).

## 6. CORS and WebSocket Origin

### CORS

Today's `allow_origins=["*"]` becomes an allowlist in production, read from env:

```python
import os

_ALLOWED = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED or ["http://localhost:3000"],  # dev fallback
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

Production `ALLOWED_ORIGINS` is set to exactly the Vercel frontend URL. Anything else is rejected at the CORS layer before reaching the handlers.

### WebSocket Origin check

CORS does not automatically protect WebSockets. The browser sends an HTTP `Origin` header during the WS handshake (RFC 6455 §4.2.1), but the application has to inspect it:

```python
@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    if _ALLOWED and origin not in _ALLOWED:
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    ...
```

**This is advisory browser-origin protection, not authentication.** Browsers send `Origin` honestly. A scripted client (curl, Python `websockets`, etc.) can send any value. Origin gating raises the cost of casual cross-site abuse but does not stop a determined adversary that knows the backend URL. It is a hygiene layer, not a security boundary. The access control that actually matters to the backend is [Section 7](#7-minimum-access-baseline).

## 7. Minimum access baseline

This phase does **not** introduce user accounts, JWT, OAuth, or password login. Those belong to a later multi-user phase.

It also does not leave the backend unprotected. A fully open `/ws` and `/plan` plus the agent chain that burns OpenAI + SerpAPI credits per request is a real cost-abuse surface. The frontend-side Vercel Deployment Protection does **not** solve this on its own — the Railway backend URL is a separate origin that browsers call directly, so anyone who learns the backend URL bypasses the frontend gate entirely.

The baseline for this phase is therefore a **two-layer gate**:

### Layer 1: frontend — Vercel Deployment Protection

Enable Vercel's built-in deployment protection on the project. This prompts any visitor to the Vercel URL for a password before the page renders. Zero application code; concrete scope and options depend on the Vercel plan, and Hobby-plan behavior is narrower than team plans. Treat this layer as "keep away the casually curious", not "secure the backend".

### Layer 2: backend — shared demo token

A single `DEMO_ACCESS_TOKEN` lives in Railway env. The backend accepts a request only when the token is presented correctly. Token mechanism differs between HTTP and WebSocket, because browser APIs differ.

**HTTP `/plan`** — standard bearer token:

```python
@app.post("/plan")
async def plan(request: TripRequest, authorization: str = Header(None)):
    if authorization != f"Bearer {settings.DEMO_ACCESS_TOKEN}":
        raise HTTPException(status_code=401)
    ...
```

The frontend reads `VITE_DEMO_TOKEN` from the build env and sends it in `Authorization: Bearer <token>` on every `/plan` call.

**WebSocket `/ws`** — token as query parameter:

```python
@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    token = ws.query_params.get("demo_token", "")
    if token != settings.DEMO_ACCESS_TOKEN:
        await ws.close(code=1008)
        return
    # origin check, then accept
```

Why a query parameter rather than an `Authorization` header: the browser `WebSocket` constructor is `new WebSocket(url, protocols?)` (MDN). There is no parameter for arbitrary request headers. A query parameter is the only mechanism a pure-browser client can use to pass a credential on the initial handshake.

### Trade-offs of a query-parameter WS token

- **Token may appear in server access logs and browser history.** Mitigate by rotating the token if it leaks, keeping `LOG_LEVEL` at `INFO` (don't log raw URLs at `DEBUG`), and not sharing browser history on the demo device. Acceptable for a demo; not acceptable for a production auth system, which is why this is a demo baseline and not Phase 5's real auth.
- **A single token is shared across all demo users.** Compromise of one friend's clipboard equals compromise of all visitors. This is explicitly a "trusted small demo group" model.
- **Rotation is manual.** Change `DEMO_ACCESS_TOKEN` on Railway, change `VITE_DEMO_TOKEN` on Vercel, redeploy both. Documented in the README runbook.

### Alternatives that were considered and deferred

- **Cookie-based WS auth**: requires same-origin or CORS with credentials; adds friction for a demo-stage split-origin deployment.
- **First-message auth (WS-level handshake after `accept`)**: cleaner in principle but requires a gating state machine to reject business messages before authentication. More code than a query param, for equivalent protection against the realistic threat model.
- **`Sec-WebSocket-Protocol` subprotocol carrying a token**: works but is a semantic abuse of subprotocols. Not chosen.
- **No token, rely only on origin + rate limit**: accepts cost-abuse risk if the backend URL leaks. Not chosen for this phase.

### Explicit non-goals for this layer

- Per-user identity. This is a shared-secret gate, not user authentication.
- Role-based access. There is one level of access.
- Auditability. Who made which request is not a question this layer can answer.

These live in a later multi-user phase.

## 8. Concurrency and rate limiting

Four layers, from application-local to network-edge.

### Layer A: per-connection serial handling (already in place)

The WebSocket handler in `main.py` awaits each message handler before reading the next message:

```python
while True:
    raw = await ws.receive_text()
    await _handle_plan(...)   # must complete
    # next receive_text only after handler returns
```

So **a single connection already processes plans serially** without any added locking. The correct product behavior on top of this:

- Frontend disables the "Plan" button while a plan is in flight.
- If a client somehow fires a second `plan` before the first returns (e.g., a scripted client), it waits in the socket buffer and runs after the first. No error, no race.

No design change is needed here. The earlier draft's "second plan immediately rejected" is not how the current architecture behaves and is not a useful behavior for 4.3a to introduce. The semaphore in Layer B covers the real risk (cross-connection parallelism).

### Layer B: global concurrency cap

A module-level `asyncio.Semaphore(N)` guards `plan_trip` invocations across the entire backend process. `N` is read from `MAX_CONCURRENT_PLANS` env, default 5.

```python
_plan_semaphore = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT_PLANS", "5")))

async def _handle_plan(ws, data, session):
    try:
        async with asyncio.timeout(5):
            await _plan_semaphore.acquire()
    except TimeoutError:
        await ws.send_json({"type": "error", "data": "server busy, try again"})
        return
    try:
        await asyncio.to_thread(plan_trip, data)
    finally:
        _plan_semaphore.release()
```

This prevents a burst of connections from pinning the single Railway process or draining LLM quota in the same instant.

### Layer C: HTTP rate limit (library)

For the HTTP `/plan` endpoint: `slowapi` with a per-IP limit (e.g., 10 per minute).

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/plan")
@limiter.limit("10/minute")
async def plan(request: Request, ...):
    ...
```

`slowapi` is chosen over writing this ourselves because HTTP limiting is a well-understood pattern with a decent library. **`slowapi` does not currently support WebSocket endpoints**, which is why the next layer is hand-rolled.

### Layer D: WebSocket rate limit (application-local, hand-rolled)

Because `slowapi` does not cover WebSockets, a small in-memory sliding-window limiter runs on the WS accept path:

```python
class IPRateLimiter:
    def __init__(self, max_per_window: int, window_seconds: int):
        self.max = max_per_window
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        events = self._events[ip]
        cutoff = now - self.window
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self.max:
            return False
        events.append(now)
        return True

_ws_connect_limiter = IPRateLimiter(max_per_window=20, window_seconds=60)

@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    ip = ws.client.host if ws.client else "unknown"
    if not _ws_connect_limiter.allow(ip):
        await ws.close(code=1008)
        return
    # origin check, token check, then accept
```

Explicit limitations written into the design:

- **Single-instance only.** The limiter state is in-process memory. If the backend ever scales to multiple Railway instances, per-IP counts are split across instances and the limit becomes weaker than advertised. A Redis-backed limiter (or moving to edge-layer rate limiting) is the natural next step — and a real Phase-5 concern once multi-instance is a thing.
- **No global cap.** This limits one IP's connection rate, not overall concurrency. That is Layer B's job.
- **Minimal surface.** Same-IP `plan` message rate on top of the connection rate is not separately limited in this phase — the global semaphore plus the connection rate is deemed sufficient for a demo. If a single IP opens 20 connections and fires 20 plans, Layer B's semaphore gates the execution anyway.

### Layer E: payload size (already in place)

`MAX_WS_MESSAGE_SIZE = 16 * 1024`. Unchanged. Rejects oversize messages before processing.

## 9. Production limits of disk state (logs and caches)

Both file-based paths the backend writes to — logs and tool cache — behave very differently on a developer laptop versus on managed platforms.

### File logs

`backend/logs/backend_YYYY-MM-DD.log` is a file on disk. On Railway, Render, and Fly, the container filesystem is ephemeral:

- On redeploy, the filesystem is rebuilt from scratch. Log files do not persist across deploys.
- On restart or autoscale, the same erasure happens.
- On multi-instance deployments (not this phase but foreseeable), each instance writes to its own local file; there is no unified log view.

Implications for this phase:

- **File logs are short-term in-process diagnostics only.** They help when SSH-ing or `railway run`-ing into a live container to inspect recent behavior. They do not replace platform log aggregation.
- **STDOUT / STDERR is the canonical log destination in production.** Railway captures it, Fly captures it, Vercel captures it. Every `logger.*(...)` call already reaches STDOUT through the root logger's default handler, so the platform already sees everything.
- **The file handler stays in place** for simplicity — no refactor required — but it is understood to be a convenience, not a reliability layer.

Structured log shipping (Logtail, Better Stack, self-hosted Loki) becomes interesting in a later phase when platform-native logs stop being sufficient.

### Tool cache

`backend/tools/.cache/` stores time-bound caches for SerpAPI and Firecrawl results (`_cache.py` decorator). Same ephemeral property:

- Cache is lost on every redeploy.
- Cache is lost on restart.
- Across multiple instances, caches don't share.

Implications:

- **The cache is a best-effort performance optimization, not a source of truth.** A cache miss simply re-hits the upstream provider.
- **The cache must never be treated as state or as a persistence layer.** Any code that assumes cached data has survived across deploys is wrong on a managed platform.
- **Multi-instance cache consistency is not a goal for this phase.** If and when the app runs more than one Railway instance, a shared cache (Redis) is the right answer, and it belongs to that phase.

A production-grade cache (Redis or equivalent) is a reasonable Phase-5 addition if cache hit rate becomes worth paying for. It is not needed now.

## 10. CI/CD and rollback

### CI (already in place)

`.github/workflows/ci.yml` runs on every push and pull request:

- `backend`: `python -m compileall -q .`
- `frontend`: `npm ci` + `npm run build`

This verifies the two things that must hold before anything ships. Future additions (tests, linting, security scans, deploy jobs) slot in as new steps without restructuring.

### CD for this phase — no repository-controlled CD

> **Implemented as described.** Vercel and Railway auto-deploy on push to `main`;
> there is no repository-controlled deploy job. A separate manual-trigger
> `.github/workflows/deploy-smoke.yml` runs the post-deploy smoke checks
> (`/healthz`, `/readyz`, calendar gating, bundle secret scan) — it is a
> verification workflow, not a deploy pipeline.

Vercel and Railway both run their own automatic deployments on `git push` to the configured branch. **This is "CD" in the practical sense**, just not CD controlled from a workflow file inside the repo.

This phase does **not** add a deploy job to GitHub Actions. The reasons:

1. Tag-gated deploys, preview environments, staging branches, and rollback policies are interesting but premature before the app has a real usage pattern.
2. Relying on platform-native deploy keeps the failure surface small and legible. One git push, one platform build log, one deploy.
3. A homegrown `actions/deploy@…` job would need platform secrets in the Actions environment — extra secret management for no immediate gain.

Later phases can reintroduce a repository-controlled deploy workflow with specific goals: tag-gated production deploy (only on `v*.*.*`), preview URLs on pull requests, coordinated multi-service deploys. None are needed yet.

### Operational runbook (lives in README, written for humans)

The README — not a workflow file — documents the ship flow:

1. Merge PR to `main` after CI is green.
2. Vercel builds and promotes automatically; the new static bundle is live in roughly 60 seconds.
3. Railway builds and deploys automatically; the new backend is live in roughly 2–3 minutes. The previous revision stays in the dashboard for one-click rollback.
4. Verify via the smoke path in [Section 11.1](#111-post-deploy-smoke-check).

### Rollback

Both platforms expose a per-revision rollback button. Post-rollback:

- Pull the commit locally (`git checkout <sha>`), confirm the problem is actually the new commit and not a config / env issue.
- Re-run the smoke path in [Section 11.1](#111-post-deploy-smoke-check) against the rolled-back URL.
- If rollback happens in production, record it in `CHANGELOG.md` under the next `[Unreleased]` entry so the history stays honest.

## 11. Acceptance criteria

Everything below has to be demonstrable before this phase can be called done.

### 11.1 Post-deploy smoke check

1. `curl https://<railway-domain>/api/calendar` with the right `Authorization: Bearer <DEMO_ACCESS_TOKEN>` → `200 OK` with the 2026 GP list.
2. The same request without the header → `401`.
3. Opening `https://<vercel-domain>` in a browser after passing Vercel Deployment Protection renders the form; the network tab shows the calendar fetch hitting Railway with the bearer token.
4. Starting a plan from the UI opens a WebSocket to `wss://<railway-domain>/ws?demo_token=…`, receives at least one `message` event within 3 seconds, and completes a full `result → done` for a simple GP.
5. A plan for a non-default GP (e.g. Azerbaijan) with explicit depart/return dates completes without crashing, even if an upstream provider (SerpAPI, Firecrawl) hits a limit — the three-tier fallback covers it.

### 11.2 Backend-direct access protection

1. `curl https://<railway-domain>/api/calendar` **without** the bearer token → `401`. Confirms the backend is not reachable by scripted clients who know the URL but not the token.
2. `wscat -c "wss://<railway-domain>/ws"` (no `demo_token` query param) → server closes with code 1008. Confirms WS gate works independently of Vercel protection.
3. `wscat -c "wss://<railway-domain>/ws?demo_token=<WRONG>"` → server closes with code 1008.
4. `wscat -c "wss://<railway-domain>/ws?demo_token=<CORRECT>" --origin https://unknown.example.com` → server closes with code 1008 (origin check is independent of the token).

### 11.3 Security hygiene

1. `ALLOWED_ORIGINS` env is set on Railway; `CORSMiddleware` reads it; no `["*"]` in production.
2. `grep -r "OPENAI_API_KEY\|SERPAPI_API_KEY\|FIRECRAWL_API_KEY\|DEMO_ACCESS_TOKEN" frontend/dist/` returns nothing. Only `VITE_BACKEND_URL`, `VITE_WS_URL`, and `VITE_DEMO_TOKEN` appear (which are public by design).
3. Platform-level access baseline (Vercel Deployment Protection) is enabled on the Vercel project.

### 11.4 Concurrency protection

1. Global semaphore: with `MAX_CONCURRENT_PLANS=2` set, opening 5 WebSocket connections and submitting `plan` on each simultaneously results in at most 2 backend `plan_trip` runs active at any moment; the rest wait or receive the "server busy" message after the 5-second acquire timeout.
2. HTTP rate limit: 12 `/plan` POSTs from the same IP within 60 seconds — the 11th and 12th return `429`.
3. WS connection rate: 22 WebSocket connection attempts from the same IP within 60 seconds — the last two are closed with code 1008.
4. Payload size: sending a 20 KB message over an accepted WebSocket → server rejects with the existing oversize error.

### 11.5 Production limits acknowledged (no code, but verified)

1. After a Railway redeploy, `backend/logs/` is empty on the new revision — confirming file logs don't cross deploys. Platform log viewer still shows the STDOUT history.
2. After a redeploy, `backend/tools/.cache/` is also empty — confirming the cache is purely best-effort.
3. These are explicitly documented in the README deploy runbook as expected behavior, not bugs.

### 11.6 Rollback drill

1. Deploy a deliberately broken commit (e.g., a syntax error in a status message).
2. Roll back via the Railway dashboard to the previous revision.
3. Re-run Section 11.1 smoke; all items pass on the rolled-back version.
4. Record the drill outcome as a one-line note in `CHANGELOG.md` under `[Unreleased]`.

## 12. Out of scope

Explicit list of what this design does not cover and does not pretend to. Each is deferred to a named later phase. _**Update:** items marked **IMPLEMENTED (4.7)** below were delivered by the enterprise floor after this design was written._

- **User accounts, JWT, OAuth, password login** — ~~multi-user phase~~ **IMPLEMENTED (4.7):** Clerk OAuth + JWT verification (JWKS, per-identity isolation, fail-closed on misconfig).
- **Session persistence across reconnects** — the live per-WebSocket planning state is still in-memory and a reconnect starts fresh, **but** saved trips now persist to Postgres (**IMPLEMENTED (4.7)**) so a user can reload a saved trip across sessions.
- **Per-user quotas / attribution / audit** — partially deferred. Per-identity attribution (each saved trip is owned by a Clerk identity) shipped in 4.7; per-user storage quotas and an audit log remain Phase 5 work.
- **Preview / staging environments** — one production environment is enough at this stage.
- **Custom domain** — Vercel and Railway default subdomains are fine for the first deploy; a `.com` is a 15-minute dashboard task later.
- **Tavily / `search_web` provider adapter** — separate design, separate phase.
- **PWA manifest, mobile-responsive CSS, touch polish** — separate design, separate phase.
- **Mobile distribution strategy** — an orthogonal product decision. To be evaluated in a later dedicated document; this deployment design intentionally makes no assumption about mobile form factor.
- **Repository-controlled CD pipeline** — deferred until tag-gated deploy or preview environments become worth building.
- **Structured log shipping / APM / distributed tracing** — platform log viewers are sufficient for now.
- **Redis or any shared cache / state store** — revisit when multi-instance is actually needed.
- **Production-grade WS rate limit across instances** — same as above.

## 13. Database backup, PITR, and restore

The enterprise floor (Phase 4.7) added a Railway **Postgres** addon that stores
durable user data: `user_profiles` (including each user's email) and
`saved_trips` (the saved plan snapshots). This is real user data, so it needs a
documented backup, point-in-time-recovery (PITR), and restore procedure — not
just an implicit "Railway probably backs it up". This section is the canonical
record of that procedure until it is automated.

### What is at risk

- `user_profiles` — one row per Clerk identity, lazily created on first
  persistence op; holds `clerk_user_id` and `email`.
- `saved_trips` — one row per SAVE; holds the JSON plan snapshot, GP slug, and
  dates, scoped to a `user_profiles` row by FK (`ondelete=CASCADE`).

Loss scenarios this procedure must cover:

1. **Accidental destructive migration** (e.g. a `DROP`/`ALTER` that loses data).
2. **Operator error** (a bad manual SQL statement against prod).
3. **Platform-side data loss** (Railway Postgres volume failure).

### RPO / RTO targets

For a portfolio-stage single-instance deploy, the agreed targets are deliberately
modest and honest about the platform tier:

| Metric | Target | Rationale |
|---|---|---|
| **RPO** (max acceptable data loss) | **≤ 24h** with daily snapshots; **≤ a few minutes** if Railway PITR is enabled on the plan | A lost day of saved trips is acceptable for a demo; PITR tightens it when available. |
| **RTO** (max acceptable time to restore) | **≤ 1h** | Restore is a manual dashboard/`pg_restore` step, not an automated failover. |

These are best-effort targets for a one-person project, not a contractual SLA.

### Backup configuration (Railway Postgres)

1. **Enable automated backups** on the Railway Postgres service (Database →
   Backups). Railway's managed Postgres offers scheduled snapshots; on plans that
   support it, enable PITR for sub-day RPO. Record in the Railway project notes
   whether PITR is actually enabled, because the RPO target above depends on it.
2. **Set a retention window** of at least 7 days so a bad migration discovered a
   few days later is still recoverable.
3. **Keep one off-platform copy.** Once a week, take a logical dump and store it
   off Railway (so a whole-project loss is still recoverable):

   ```bash
   # DATABASE_URL is the Railway-injected connection string (bare postgresql://…).
   pg_dump "$DATABASE_URL" --format=custom --no-owner \
     --file="f1pc-$(date +%F).dump"
   ```

   Store the resulting `.dump` somewhere durable (encrypted cloud storage or a
   password manager attachment for a demo-scale dataset). The dump contains user
   emails — treat it as sensitive and do not commit it to git.

### Pair every destructive migration with a verified backup

Because migrations run inline in the Railway start command (see the deploy
runbook), a destructive Alembic migration would execute against live data on the
next deploy. Rule:

- **Before deploying any migration that drops/renames a column/table or rewrites
  data,** take an on-demand backup first (Railway Database → Backups → "Back up
  now", or the `pg_dump` above) and confirm it completed.
- Note the backup id / dump filename in the PR description and in the
  `CHANGELOG.md` `[Unreleased]` entry for that migration.

### Restore procedure

**From a Railway snapshot / PITR:**

1. In the Railway dashboard, Database → Backups → choose the snapshot (or PITR
   timestamp) just before the data loss.
2. Restore into a **new** database service first (do not overwrite prod blind),
   point a scratch backend at it, and verify the data looks right.
3. Once verified, cut prod over to the restored database (swap `DATABASE_URL`)
   and redeploy.

**From an off-platform logical dump:**

```bash
# Restore into a fresh database, then verify before cutting prod over.
pg_restore --clean --no-owner --dbname="$TARGET_DATABASE_URL" f1pc-YYYY-MM-DD.dump
```

After any restore, run `alembic current` against the restored database to confirm
the schema revision matches the deployed code (`alembic heads`); if it lags, run
`alembic upgrade head`.

### Restore drill (do this at least once, then quarterly)

A backup that has never been restored is not a backup. The drill:

1. Take a fresh backup of prod (snapshot or `pg_dump`).
2. Restore it into a throwaway database (new Railway service or local Postgres).
3. Confirm row counts for `user_profiles` and `saved_trips` match prod, and that
   a known saved trip loads correctly through a scratch backend pointed at the
   restored DB.
4. Tear down the throwaway database.
5. **Record the drill outcome** (date, snapshot id, row counts, pass/fail) as a
   one-line note in `CHANGELOG.md` under `[Unreleased]`, the same way rollback
   drills are recorded ([Section 11.6](#116-rollback-drill)).

Until this drill has been run at least once, the backup story is "configured but
unverified" — track it the same way the deploy gate is tracked as pending.

## Summary of decisions

| # | Decision | Choice |
|---|---|---|
| Deployment target | Vercel (frontend) + Railway (backend) | ✅ |
| Alternative considered | Fly.io single-platform — viable, not the first pick | — |
| Rejected | Self-managed VPS — operational load not worth it at this phase | ❌ |
| Production URL strategy | `VITE_BACKEND_URL` + `VITE_WS_URL` at build; `window.location` only in dev | ✅ |
| CORS | Explicit allowlist via `ALLOWED_ORIGINS`; no `["*"]` in production | ✅ |
| WebSocket Origin gate | `Origin` header check on handshake; advisory, not authentication | ✅ |
| Access baseline — frontend | Vercel Deployment Protection (plan-dependent) | ✅ |
| Access baseline — backend | `DEMO_ACCESS_TOKEN`: `Authorization: Bearer` on HTTP, query param on WS | ✅ |
| Per-connection behavior | Rely on current serial receive loop; frontend disables duplicate submit | ✅ |
| Global concurrency cap | `asyncio.Semaphore(N)` at module scope, `N` from env | ✅ |
| HTTP rate limit | `slowapi` per-IP on `/plan` | ✅ |
| WS rate limit | Hand-rolled in-memory per-IP sliding window on WS accept | ✅ |
| CD in this repo | Not in this phase — platform-native auto-deploy is the production path | ✅ |
| Rollback | Platform per-revision rollback + README runbook + drill | ✅ |
| Logging | File handler kept for convenience; STDOUT is canonical on managed platforms | ✅ |
| Tool cache | Best-effort only; not persistence, not source of truth | ✅ |
| DB backup / PITR / restore | Railway snapshots + weekly off-platform `pg_dump`; RPO ≤24h (≤min with PITR), RTO ≤1h; restore drill recorded in CHANGELOG ([Section 13](#13-database-backup-pitr-and-restore)) | ✅ |
| Mobile distribution | Orthogonal product decision, evaluated in a later dedicated document | — |
