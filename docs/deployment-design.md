# Deployment Design

_This document is the production-readiness design for getting the F1 Paddock Club out of a local demo and onto public hosting. It is a design doc — no deploy workflow is implemented here. Implementation follows once this design is accepted._

Scope is intentionally narrow. Search-provider expansion (Tavily and friends), mobile/PWA polish, and session persistence are all deferred; see [Out of scope](#7-out-of-scope) for the explicit list.

## 1. Current runtime assumptions

The system as it runs today, which the design below has to either preserve or replace cleanly.

### Processes

- **Backend**: FastAPI + Uvicorn on `127.0.0.1:8001`. Two surfaces — `/plan` (HTTP POST), `/ws` (WebSocket). State lives per WebSocket connection in in-process memory (`session = create_session()` in `main.py`). There is no database.
- **Frontend**: Vite dev server on `localhost:3000`, serving `prototype.jsx` as a React app. Production build (`npm run build`) emits a plain static bundle in `frontend/dist/`.

### Dev-time topology — **implicit same-origin**

The frontend code currently has no notion of "which backend to talk to". It does:

```js
const API_BASE = "";
const WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;
```

Calls go to the same host the page was served from. In development this works because `vite.config.js` proxies `/api/*` and `/ws` to the backend:

```js
proxy: {
  "/api": { target: "http://127.0.0.1:8001" },
  "/ws":  { target: "ws://127.0.0.1:8001", ws: true, timeout: 120000 },
},
```

This assumption breaks the moment the frontend and backend are hosted at different origins — which is exactly what a Vercel + Railway split does. [Section 4](#4-runtime-url--topology-assumptions-production-critical) is about that.

### Secrets

`backend/.env` holds `OPENAI_API_KEY`, `SERPAPI_API_KEY`, `FIRECRAWL_API_KEY`, `LLM_PROVIDER`. It is gitignored. `backend/.env.example` documents the expected variables. There are no frontend-side secrets today.

### CORS

Currently set wide open in `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The `tighten in production` comment is the design debt this document pays down.

### Logging

Backend writes to `backend/logs/backend_YYYY-MM-DD.log` via `logging_config.setup_logging()`. One file per startup date, appended across restarts.

### Concurrency

No rate limiting. No per-session lock. No global concurrency cap. The only inbound-size limit is `MAX_WS_MESSAGE_SIZE = 16 * 1024`. A single user holding an open WebSocket can issue as many `plan` messages as they want; they run sequentially only because they go through the same connection's message loop.

## 2. Deployment target comparison

Three realistic options. Assessed against seven productization criteria, not vibes.

| Criterion | Vercel (frontend) + Railway (backend) | Fly.io single platform | Self-managed VPS (Hetzner / Oracle free) |
|---|---|---|---|
| Static frontend hosting | Native; global CDN, instant | Possible via static services | Manual — Nginx or similar |
| WebSocket long connection | Backend on Railway is native; Vercel limits WS on its own functions | Native; persistent processes | Native; configure Nginx `proxy_read_timeout` |
| Python backend deploy friction | Railway auto-detects from `requirements.txt`, `git push` deploys | Dockerfile required; `fly launch` generates one | Full stack to write (Dockerfile, systemd unit, HTTPS cert) |
| Env / secret management | Two dashboards — Vercel env vars for frontend, Railway secrets for backend | One dashboard | Manual — `.env` files, secret injection via CI or operator |
| Logs / rollback / observability | Each platform ships log viewer, one-click rollback per revision | Same idea on one platform | Ship your own (journalctl + SSH, or run Grafana/Loki) |
| Cold-start behaviour on free tier | Vercel never cold-starts static; Railway $5 credit keeps one small service warm indefinitely | Fly has scale-to-zero; wake-up is 1–5 s | Always warm if the VM is on; you also always pay |
| Operational cognitive load | Two platforms, but each simple | One platform, slightly more concepts (fly regions, machines) | Highest — you own OS patches, cert renewal, monitoring |

### Recommendation

**Vercel + Railway** is the chosen target for Phase 4.3a.

Reasons:

1. The shape matches the app — static React on a CDN, long-running FastAPI behind HTTPS with native WebSocket support.
2. Free-tier economics work for a portfolio project. Vercel's static tier is essentially unlimited; Railway's $5 monthly credit keeps one small web service continuously warm (the Render free tier's 15-minute idle spin-down would ruin first-impression demos).
3. `git push` triggers platform-side build and deploy on both, with per-deploy rollback available from the dashboard.

**Fly.io** is a legitimate alternative — one platform, also good free tier, cleaner mental model. The only reason it is not the first pick is the Dockerfile / `fly.toml` learning curve, which is extra complexity this repo doesn't need today. If Railway pricing ever becomes a problem, migrating to Fly is a single-week job.

**Self-managed VPS** is rejected for this phase. The operational surface (TLS renewal, OS updates, log shipping, monitoring) is not something we want to take on while the product itself is still moving.

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

- The frontend bundle is served by Vercel's CDN.
- The backend is a single Railway service running `uvicorn main:app`. Same-process FastAPI handles both the REST `/api/*` routes and the WebSocket at `/ws`.
- All API-key traffic (OpenAI, SerpAPI, Firecrawl) flows from Railway's backend outward — the frontend never sees or embeds those keys.
- No database, no cache layer, no queue in this phase. In-process Python state per WebSocket is sufficient.

## 4. Runtime URL / topology assumptions (production-critical)

This section exists because the dev-time same-origin assumption silently breaks in production. Making it explicit is the only way to avoid a landmine.

### Problem

Frontend code today derives the backend URL from the page's own host:

```js
const WS_URL = `${...}://${window.location.host}/ws`;
```

In production the frontend will be at `f1-paddock-club.vercel.app` and the backend at `f1-paddock-club-backend.railway.app` (or similar). The page cannot talk to its own host for the API — it has to address the backend explicitly.

### Decision

Introduce two build-time environment variables in the frontend:

- `VITE_BACKEND_URL` — e.g. `https://f1-paddock-club-backend.up.railway.app`
- `VITE_WS_URL` — e.g. `wss://f1-paddock-club-backend.up.railway.app/ws`

At runtime the frontend prefers these when set, and falls back to the current `window.location` derivation only for local development:

```js
const BACKEND =
  import.meta.env.VITE_BACKEND_URL ||
  window.location.origin;          // dev: Vite proxy handles /api/*

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

fetch(`${BACKEND}/api/calendar`);  // was: fetch(`${API_BASE}/api/calendar`)
new WebSocket(WS_URL);
```

Vercel sets these two variables at build time; they land in the emitted JS bundle. They are **public values**, not secrets — exposing them in the bundle is expected and safe.

### Why not a Vercel rewrite proxy?

Vercel can rewrite `/api/*` on the frontend edge to the Railway backend, which would preserve the same-origin illusion. It is rejected here because:

- It does not solve WebSockets — Vercel's rewrite rules don't proxy `wss://`.
- It adds one more hop in the request path with no real benefit at this scale.

Direct cross-origin to the backend is simpler and more honest about the topology.

### Dev vs production

| | Dev | Production |
|---|---|---|
| Backend URL | Vite proxy to `127.0.0.1:8001` | Explicit `VITE_BACKEND_URL` |
| WS URL | Same host + Vite ws proxy | Explicit `VITE_WS_URL` |
| Origin | `http://localhost:3000` | `https://<vercel-domain>` |
| CORS on backend | `["*"]` permissive | Strict allowlist (see [Section 6](#6-cors--websocket-origin--access-baseline)) |

## 5. Environment, secrets, and configuration

### Inventory

| Variable | Where it lives | Who reads it | Secret? |
|---|---|---|---|
| `OPENAI_API_KEY` | Railway env | backend (`llm.py`) | **Yes** |
| `ANTHROPIC_API_KEY` | Railway env | backend (`llm.py`) | **Yes** |
| `SERPAPI_API_KEY` | Railway env | backend (`tools/search_*.py`) | **Yes** |
| `FIRECRAWL_API_KEY` | Railway env | backend (`tools/search_tickets.py`) | **Yes** |
| `LLM_PROVIDER` | Railway env | backend (`llm.py`) | No (value is `openai` or `anthropic`) |
| `LOG_LEVEL` | Railway env | backend (`logging_config.py`) | No |
| `ALLOWED_ORIGINS` | Railway env | backend (`main.py` CORS) | No; see [Section 6](#6-cors--websocket-origin--access-baseline) |
| `VITE_BACKEND_URL` | Vercel build env | frontend bundle | No; public by design |
| `VITE_WS_URL` | Vercel build env | frontend bundle | No; public by design |

### Rules

1. **Secrets never enter the frontend bundle.** `VITE_*` variables are compiled into static JS at build time; anything prefixed `VITE_` is, in effect, published. Only non-secret URLs and flags go there.
2. **Secrets never enter the git repository.** `.env` is gitignored; `.env.example` documents the keys without values.
3. **Dev and production do not share secrets.** The OpenAI key used on Railway is a production-only key; developer machines use their own `.env`.
4. **Config hierarchy:** `backend/.env.example` (in git, documents shape) → `backend/.env` (local, gitignored) → Railway environment (production).

## 6. CORS + WebSocket Origin + access baseline

### CORS

Today's `allow_origins=["*"]` must become an allowlist in production.

```python
# main.py
import os

_ALLOWED = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED or ["http://localhost:3000"],  # dev fallback
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

Production `ALLOWED_ORIGINS` is set to exactly the Vercel frontend URL. Anything else is rejected at the CORS layer before it reaches our handlers.

### WebSocket Origin check

CORS does not automatically protect WebSockets. The browser still sends an `Origin` header during the WS handshake (see RFC 6455 §4.2.1), but it is just an HTTP header — our handler has to inspect it ourselves.

```python
# main.py
@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    origin = ws.headers.get("origin", "")
    if _ALLOWED and origin not in _ALLOWED:
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    ...
```

**This is advisory browser-origin protection, not authentication.** A browser will send `Origin` honestly. A scripted client (curl, Python `websockets`, etc.) can send any value it wants. Origin gating raises the cost of casual scraping and stops most CSRF-style abuse from other sites; it does not stop a determined adversary. Treat it as a low-cost hygiene layer, not a security boundary.

### Access baseline (not user accounts)

Phase 4.3a explicitly **does not** introduce user accounts, JWT, OAuth, or password login. Those belong to a later multi-user phase.

However, "no user accounts" must not be confused with "no access control at all". A fully open `/ws` plus an agent chain that burns OpenAI + SerpAPI credits per request is a real cost-abuse surface. The design evaluates three minimal gate options for deployment, and picks one as the recommended baseline:

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **A. Platform password protection** | Vercel "Deployment Protection" or Railway's env-gated basic auth on the public URL | Zero app code. You share the URL + a password with friends or hiring managers. | Only protects the entry surface; bots that already know the password don't slow down. |
| **B. Shared demo token** | Single token in a Railway env var; frontend reads a public flag from a small `/config` endpoint or hardcodes a prompt for the token on first visit; WS handshake and `/plan` check the `Authorization` header. | Still trivial to implement (~20 lines). Can rotate without touching user accounts. | Token shared across all demo users — compromise equals everyone; no per-user attribution. |
| **C. Pure origin gate + rate limit** | Nothing beyond Section 6's allowlist, plus Section 6's concurrency / rate limit below. | Minimum friction for legitimate visitors. | A curated bot that spoofs `Origin` and throttles below the rate limit can still drain API quota over time. |

**Recommendation:** start with **A** (platform password) for the first public deployment. Vercel's built-in Deployment Protection is a single toggle; no code changes. If and when the project moves to a wider demo audience, promote to **B** (shared demo token) so friends don't need to type a password every visit. **C** is the long-term target only once real per-user identity exists (which is a Phase 5 problem, not a 4.3a one).

This is a real decision, not a punt. `A` is what ships with the first deploy.

### Concurrency protection (layered)

Four layers, from inside-out. Everything except the outermost layer is pure application code — no new dependencies.

**1. Per-connection in-flight gate**
_Where: `_handle_plan` in `main.py`._
A single `asyncio.Lock` stored on the session dict. The same WebSocket cannot have two concurrent `plan` runs — the second message waits or is rejected with a clear error. This prevents a user double-clicking the Plan button from firing two LangGraph pipelines in parallel through the same session.

"Per-connection" is deliberate — the current session is one WebSocket, not a cross-device user identity. When a Redis-backed session store exists later, the lock will move accordingly; the interface does not change.

**2. Global concurrency cap**
_Where: module-level `asyncio.Semaphore(N)` in `main.py`._
Across the whole backend process, only N `plan_trip` invocations run simultaneously (N tunable via env, default 5). The N+1th request waits, or returns an explicit "server busy" message after a short timeout. Protects against a coordinated burst exhausting the LLM quota or pegging the single Railway process.

**3. Per-IP rate limit (application-side)**
_Where: `slowapi` middleware on `/plan` and on WS connection accept._
Bucket per client IP: maximum M new `plan` requests per minute. The browser's `X-Forwarded-For` from Railway's proxy is authoritative here. Returns HTTP 429 / WS `close 1008` on breach.

Application-side is chosen over edge / CDN rate limiting because we do not yet have a Cloudflare layer in front of Railway, and we do not want a design that presumes infra we haven't set up. If a Cloudflare front-door is added in a later hardening pass, per-IP limits can move there and the app-side slowapi becomes defense-in-depth or can be removed.

**4. Payload size limit**
Already in place — `MAX_WS_MESSAGE_SIZE = 16 * 1024`. Unchanged.

## 7. CI/CD decisions

### CI (already in place)

`.github/workflows/ci.yml` runs on every push and pull request:

- `backend`: `python -m compileall -q .`
- `frontend`: `npm ci` + `npm run build`

This verifies the two things that absolutely must hold before anything ships. Future additions (tests, linting, security scans, deploy jobs) slot in as new steps without restructuring.

### CD for 4.3a — do not build a repository-controlled CD pipeline

Vercel and Railway both run their own automatic deployments on `git push` to the configured branch. **This is "CD" in the practical sense**, just not CD controlled from a workflow file inside our repository.

Phase 4.3a does **not** add a deploy job to GitHub Actions. The reasons:

1. Tag-gated deploy, preview environments, staging branches, and rollback policies are interesting but premature before the app has a real usage pattern.
2. Relying on platform-native deploy for now keeps the failure surface small and legible. One git push, one platform build log, one deploy.
3. A homegrown `actions/deploy@…` job would need platform secrets in the Actions environment — an extra secret management problem for no immediate gain.

Later phases can reintroduce a repository-controlled deploy workflow with specific goals: tag-gated production (deploy only on `v*.*.*`), preview URLs for pull requests, or coordinated multi-service deploys. None of those are needed yet.

### Operational runbook (lives in README, written for humans)

The `README` — not a workflow file — documents the steps to ship a change:

1. Merge PR to `main` after CI is green.
2. Vercel builds and promotes automatically; the new static bundle is live in roughly 60 seconds.
3. Railway builds and deploys automatically; the new backend is live in roughly 2–3 minutes. The previous revision stays in the dashboard for one-click rollback.
4. Verify via the smoke path in [Section 9.1](#91-post-deploy-smoke-check).

### Rollback

Both platforms expose a per-revision rollback button. Post-rollback:

- Pull the commit locally (`git checkout <sha>`), confirm the problem is actually the new commit and not a config/env issue.
- Re-run the smoke path in [Section 9.1](#91-post-deploy-smoke-check) against the rolled-back URL.
- If rollback happens in production, record it in `CHANGELOG.md` under the next `[Unreleased]` entry so the history stays honest.

## 8. File logging limitations on managed platforms

A piece of reality that the design must acknowledge.

Today's `backend/logs/backend_YYYY-MM-DD.log` is a file on disk. On a developer laptop this is fine. On Railway, Render, and Fly, the container filesystem is ephemeral:

- On redeploy, the filesystem is rebuilt from scratch. Log files do not persist across deploys.
- On autoscale or restart, the same erasure happens.
- On platforms with multiple instances (not this phase, but foreseeable), each instance writes to its own local file — there is no unified log view.

What this means for 4.3a:

- **File logs become short-term in-process diagnostics only.** They help if you are SSH-ing or `railway run`-ing into a live container to inspect recent behavior. They do not replace platform log aggregation.
- **STDOUT / STDERR is the canonical log destination in production.** Railway captures it, Vercel captures it (for their Serverless Function runtimes), Fly captures it. Every level we `logger.info(...)` already reaches STDOUT via the root logger's default handler, so the platform already sees everything.
- **The file handler is left in place** (simplicity, no refactor), but it is understood to be a convenience, not a reliability layer.

A later phase can add structured log shipping (e.g. Logtail, Better Stack, or a self-hosted Loki) if and when platform-native logs become insufficient. For 4.3a the platform's own log view is sufficient.

## 9. Acceptance criteria

Everything below has to be demonstrable before 4.3a can be called done.

### 9.1 Post-deploy smoke check

Once the design is implemented and deploys land on both platforms, these must all pass:

1. `curl https://<railway-domain>/api/calendar` → `200 OK` with the 2026 GP list.
2. Opening `https://<vercel-domain>` in a browser renders the form; network tab shows the calendar fetch succeeding against the Railway URL (not against the Vercel host).
3. Starting a plan from the UI opens a WebSocket to `wss://<railway-domain>/ws`, receives at least one `message` event within 3 seconds, and completes a full `result → done` for a simple GP (e.g. Italian GP mocks).
4. A plan for a non-default GP (e.g. Azerbaijan) with explicit depart/return dates completes without crashing, even if the SerpAPI tier hits a limit (fallbacks take over).

### 9.2 Security hygiene

1. `ALLOWED_ORIGINS` environment variable is set on Railway; `CORSMiddleware` reads it and no longer uses `["*"]` in production.
2. The WebSocket endpoint rejects a handshake from an unapproved `Origin` (test with `wscat -o https://example.com ...`).
3. `grep -r "OPENAI_API_KEY\|SERPAPI_API_KEY\|FIRECRAWL_API_KEY" frontend/dist/` finds nothing. Secrets stay on the backend.
4. Platform-level access baseline (option A above, Vercel Deployment Protection) is enabled on the Vercel project.

### 9.3 Concurrency protection

1. A single WebSocket submitting `plan` twice quickly sees the second attempt rejected with a clear message (not a silent queue, not a parallel run).
2. Fifteen concurrent WebSocket clients submitting `plan` simultaneously result in at most `N` (default 5) backend runs at any moment; the rest wait or receive an explicit "busy" signal.
3. Sixty `plan` requests from the same IP in one minute trigger the slowapi rate limit (`429` or equivalent).

### 9.4 Rollback drill

1. Deploy a deliberately-broken commit (e.g. syntax error in a status message).
2. Roll back via Railway dashboard to the previous revision.
3. Re-run the Section 9.1 smoke check; all four steps pass on the rolled-back version.
4. Record the drill outcome as a one-line note in `CHANGELOG.md` under `[Unreleased]`.

## Out of scope

Explicit list of things this design does not cover and does not pretend to cover. Each is deferred to a named later phase.

- **User accounts, JWT, OAuth, password login** — Phase 5 (multi-user + persistence).
- **Session persistence across reconnects** — Phase 5. Current state is per-WebSocket in-memory; a reconnect starts fresh.
- **Automatic deployment controlled from this repo** — considered again when there is reason to gate production on tag or branch.
- **Preview / staging environments** — one production environment is enough for a portfolio-stage app. Preview URLs can be added once there are contributors beyond the project owner.
- **Custom domain** — the Vercel and Railway default subdomains are fine for the first deploy. Registering a `.com` and configuring DNS is a 15-minute dashboard task when the project owner decides the subdomain is a hiring-impression issue.
- **Tavily / `search_web` provider adapter** — separate design, separate phase (4.3b).
- **PWA manifest, mobile responsive CSS, touch polish** — separate design, separate phase (4.3c).
- **Mobile distribution strategy** — whether to stay PWA-only, wrap the web app with Capacitor for Play Store / App Store, or add a Telegram Mini App target is an orthogonal product decision. A dedicated short document will evaluate the options before Phase 4.3c commits to any of them. This deployment design intentionally does not presume a mobile form factor.
- **Observability beyond platform defaults** — no APM, no distributed tracing, no external log aggregator in this phase. Platform log viewers and the existing `backend/logs/` file handler are enough for the first deploy.

## Summary of decisions

| # | Decision | Choice |
|---|---|---|
| Deployment target | Vercel (frontend) + Railway (backend) | ✅ |
| Alternative considered | Fly.io single-platform — viable, not the first pick | ✅ |
| Rejected | Self-managed VPS — operational load not worth it at this phase | ❌ |
| Production URL strategy | `VITE_BACKEND_URL` + `VITE_WS_URL` build-time injection; fall back to `window.location` only in dev | ✅ |
| CORS | Explicit allowlist via `ALLOWED_ORIGINS`; no more `["*"]` in production | ✅ |
| WebSocket Origin gate | `Origin` header check in `/ws` handler; understood as advisory, not authentication | ✅ |
| Access baseline | Vercel Deployment Protection (platform password) for first deploy; shared demo token as a ready alternative | ✅ |
| Per-connection in-flight gate | `asyncio.Lock` on session dict | ✅ |
| Global concurrency cap | `asyncio.Semaphore(N)` at module scope, `N` from env | ✅ |
| Per-IP rate limit | `slowapi` app-side; edge / CDN rate limit deferred | ✅ |
| CD in this repo | Not in 4.3a — platform-native auto-deploy is the production path | ✅ |
| Rollback | Platform per-revision rollback + README runbook + smoke check | ✅ |
| Logging | File handler kept for convenience; STDOUT is the canonical source on Railway | ✅ |
| Not in scope | User auth, persistence, Tavily, PWA, mobile wrappers, custom domain, staging | — |
