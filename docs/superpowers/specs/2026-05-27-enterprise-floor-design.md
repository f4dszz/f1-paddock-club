# Enterprise Floor — Design

**Date:** 2026-05-27
**Author:** Claude (brainstorming session with shawn)
**Status:** Draft — awaiting user review
**Supersedes:** none. **Builds on:** `docs/deployment-design.md`.

## 0. What this design is

`docs/deployment-design.md` chose Vercel + Railway and the demo-token gate, then explicitly listed **user accounts / JWT / OAuth** and **session persistence** as out-of-scope for that phase.

This design is the next phase: the "enterprise floor" — the minimum bar before the app can be called production-grade rather than a portfolio demo. It accepts the deployment topology from the prior doc and adds five things on top:

1. **Real auth** via Clerk (OAuth IdP, Google + GitHub + email + passkey).
2. **Persistent state** — Postgres for saved trips and `active_constraints` per user.
3. **Error tracking** — Sentry on backend + frontend.
4. **Operational readiness** — `/healthz` `/readyz`, structured JSON logs to STDOUT, secret-scanning CI, CSP/HSTS headers, post-deploy smoke script.
5. **Deploy implementation** — wires the existing deployment-design.md into actual `railway.json` / Vercel config / runbook so `git push` → live.

Acceptance is the user goal: filling in env values → deploys + browser login + saved trips work, no bugs, no security issues.

## 1. Architecture

```
┌──────────────────────┐
│  User browser        │
│                      │
│  Clerk <SignIn/>  ───┼──────────► clerk.com (auth flow)
│  ClerkProvider       │            (Google/GitHub/email)
│         │            │
│         ▼            │
│  App (React/Vite)    │ ◄────  static bundle (Vercel CDN)
│                      │
│  fetch('/api/...')   │  HTTPS  Authorization: Bearer <Clerk JWT>
│  new WebSocket(...)  │   WSS   ?token=<Clerk JWT>
│         │            │
└─────────┼────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│  Railway: FastAPI + Uvicorn                  │
│                                              │
│  Middleware (app-wide):                      │
│    1. CORS (allowlist from ALLOWED_ORIGINS)  │
│    2. Sentry ASGI                            │
│    3. Security headers (CSP/HSTS in prod)    │
│    4. Request-ID + structured-log binding    │
│                                              │
│  Per-route dependency:                       │
│    require_user(authorization) -> user_id    │
│    (JWT verify against cached Clerk JWKS)    │
│                                              │
│  Routes:                                     │
│    /healthz   (no auth — liveness)           │
│    /readyz    (no auth — readiness + DB)    │
│    /api/calendar  (require_user)             │
│    /plan          (require_user)             │
│    /ws            (token verified on accept) │
│                                              │
│                                              │
│  Persistence layer (SQLAlchemy):             │
│    user_profiles   (Clerk id → row)          │
│    saved_trips     (per-user plan snapshots) │
│    saved_constraints (per-user defaults)     │
└──────────┬──────────────────┬────────────────┘
           │                  │
           ▼                  ▼
   ┌──────────────┐   ┌─────────────────┐
   │  Postgres    │   │  OpenAI/SerpAPI │
   │  (Railway    │   │  /Firecrawl     │
   │   addon)     │   │   (outbound)    │
   └──────────────┘   └─────────────────┘
```

External services and corresponding env placeholders (full inventory in §6):

| Service | What it provides | Env keys (placeholders) |
|---|---|---|
| Clerk | OAuth IdP, sign-in UI, JWT issuance | `CLERK_SECRET_KEY`, `VITE_CLERK_PUBLISHABLE_KEY`, `CLERK_JWT_ISSUER`, `CLERK_JWKS_URL` |
| Postgres (Railway) | persistence | `DATABASE_URL` |
| Sentry | error tracking | `SENTRY_DSN_BACKEND`, `VITE_SENTRY_DSN_FRONTEND` |
| Vercel | frontend hosting | `VITE_BACKEND_URL`, `VITE_WS_URL` |
| Railway | backend hosting | `ALLOWED_ORIGINS`, `APP_ENV=production` |
| OpenAI / SerpAPI / Firecrawl | already in deployment-design.md | unchanged |

## 2. Components

### 2.1 Auth (Clerk)

**Why Clerk:** native Vercel Marketplace integration auto-provisions env keys on Vercel side; React SDK is mature; JWT verification on FastAPI is well-supported via JWKS; free tier covers 10k MAU which exceeds portfolio scale.

**Frontend integration:**

- `npm i @clerk/clerk-react`
- Wrap `<App />` in `<ClerkProvider publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}>`.
- Use `<SignedIn>` / `<SignedOut>` to gate the planner UI.
- Use `<SignIn />` component on a dedicated sign-in route.
- Use `useAuth()` to call `getToken()` for the current JWT on each backend call.
- Replace the current `DEMO_TOKEN` bake-into-bundle with `getToken()` per request.
- Show `<UserButton />` in `AppHeader` so users can sign out.

**Backend verification:**

- `pip install pyjwt[crypto]` (JWKS-aware JWT verification, RS256).
- A `verify_clerk_jwt(token: str) -> ClerkClaims` helper:
  - Fetches the Clerk JWKS once and caches it for an hour.
  - Verifies `alg=RS256`, `iss == CLERK_JWT_ISSUER`, `aud` if set, `exp/nbf`, signature against the matching `kid`.
  - Returns claims (`sub` = user id, `email`, ...).
  - Raises `HTTPException(401)` on any failure with a single safe error message.
- A FastAPI dependency `current_user_id(authorization: str = Header(...)) -> str` for HTTP routes.
- A WS-path equivalent that reads `?token=` from query params (same constraint as DEMO_TOKEN — browser WS constructor cannot send headers).

**Dual-mode auth (precise rules):**

- `APP_ENV=production` → Clerk JWT verify is the **only** accepted credential. Missing/invalid token → 401 (HTTP) or close 1008 (WS). `DEMO_ACCESS_TOKEN` if set is ignored.
- `APP_ENV in {local, dev, test}` → the request is accepted if **either** a valid Clerk JWT **or** a matching `DEMO_ACCESS_TOKEN` is presented. The user id falls back to `"demo-user"` when only the demo token is used.
- The `REQUIRE_CLERK_AUTH` env (default `true` in prod, `false` in dev) is an explicit override developers can flip to test prod-like auth locally without changing `APP_ENV`.

This keeps CI fast — the deterministic E2E lane sets `APP_ENV=test` and continues to use the demo token, exactly as today. It also keeps a working escape hatch for developers without a Clerk tenant.

The frontend always tries Clerk first; only if `import.meta.env.VITE_CLERK_PUBLISHABLE_KEY` is unset does it fall back to reading `VITE_DEMO_TOKEN` (dev/test only).

### 2.2 Persistence (Postgres + SQLAlchemy + Alembic)

**Why Postgres on Railway (not Supabase/Neon/SQLite):** Railway has a one-click Postgres addon, the backend already lives there, network egress is in-VPC, `DATABASE_URL` is auto-injected. SQLite would not survive Railway redeploys (ephemeral fs). Neon/Supabase would work but add a second platform for no win at this scale.

**Schema (v1):**

```
user_profiles
  id            UUID PK
  clerk_user_id TEXT UNIQUE NOT NULL    -- Clerk's `sub`
  email         TEXT
  display_name  TEXT
  created_at    TIMESTAMPTZ DEFAULT now()
  last_seen_at  TIMESTAMPTZ

saved_trips
  id              UUID PK
  user_id         UUID FK -> user_profiles.id ON DELETE CASCADE
  gp_slug         TEXT NOT NULL        -- e.g. "italian-gp-2026"
  depart_date     DATE
  return_date     DATE
  plan_snapshot   JSONB NOT NULL       -- the result cards + selections
  budget_summary  JSONB                -- recompute_budget output at save time
  active_constraints JSONB
  created_at      TIMESTAMPTZ DEFAULT now()
  updated_at      TIMESTAMPTZ DEFAULT now()
  INDEX (user_id, created_at DESC)

saved_constraints
  user_id     UUID PK FK -> user_profiles.id ON DELETE CASCADE
  defaults    JSONB NOT NULL           -- e.g. {"direct_only": true, "preferred_hotels": ["Marriott"]}
  updated_at  TIMESTAMPTZ DEFAULT now()
```

**Migrations:** Alembic. Initial revision creates the three tables. Each future schema change ships as a numbered revision.

**Sync pattern:** on every authenticated request, an upsert into `user_profiles` keyed on `clerk_user_id` ensures the row exists and updates `last_seen_at`. No webhook from Clerk in v1 — lazy upsert is simpler and avoids a second integration surface.

**Where the planner writes:** today the LangGraph DAG mutates in-memory state. Persistence is opt-in via two new WS message types — `save_trip` and `load_trip`. The streaming plan flow is unchanged; saving is an explicit user action. This avoids touching the planner's hot path and keeps the WebSocket message protocol additive.

**Frontend UX:**

- After a plan completes, "Save trip" button appears in `AppHeader`.
- "My trips" route lists user's saved trips with summary cards.
- Click → restores selections, constraints, and chat context into the planner view.

### 2.3 Observability (Sentry + structured logs + health)

**Backend Sentry:** `pip install sentry-sdk[fastapi]`. Init early in `main.py`:

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

if SENTRY_DSN_BACKEND:
    sentry_sdk.init(
        dsn=SENTRY_DSN_BACKEND,
        environment=APP_ENV,
        traces_sample_rate=0.1,
        integrations=[FastApiIntegration()],
    )
```

When `SENTRY_DSN_BACKEND` is empty (dev or unset), Sentry is a no-op. No errors, no skipped tests.

**Frontend Sentry:** `npm i @sentry/react`. Init in `prototype.jsx` entry:

```js
import * as Sentry from "@sentry/react";

if (import.meta.env.VITE_SENTRY_DSN_FRONTEND) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN_FRONTEND,
    environment: import.meta.env.VITE_APP_ENV || "production",
    tracesSampleRate: 0.1,
  });
}
```

**Structured logs:** the existing file handler stays for local debugging. A JSON formatter is added to the STDOUT handler so Railway/Vercel log aggregators can parse fields. Library: `python-json-logger`. Format includes `level`, `logger`, `message`, `timestamp`, `request_id` (per request via middleware).

**Health endpoints:**

- `GET /healthz` — always returns `{"status": "ok"}`. No DB, no auth. Used by Railway liveness probe.
- `GET /readyz` — pings DB with a `SELECT 1` (1-second timeout). Returns 200 with `{"db": "ok"}` or 503 with `{"db": "down", "error": "..."}`. Used by Railway readiness probe and the post-deploy smoke script.

### 2.4 Security headers (CSP + HSTS)

A FastAPI middleware adds response headers in production (`APP_ENV=production`):

- `Strict-Transport-Security: max-age=63072000; includeSubDomains` — HSTS, 2 years.
- `Content-Security-Policy: default-src 'self'; connect-src 'self' https://*.clerk.accounts.dev https://*.sentry.io; ...` — locked to the Clerk + Sentry endpoints we actually use. **Frontend CSP is set in `vercel.json` headers** because the static bundle is served by Vercel, not the FastAPI process.
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`

CSP is the load-bearing one. Get it wrong and Clerk's iframe-based passkey flow breaks. The design value above is the minimum Clerk requires; we'll iterate during implementation by checking the Clerk-recommended directives.

### 2.5 CI/secret-scanning + deploy

**Secret scanning:** GitHub Action using `gitleaks` on every PR + push. Free for public repos. Fails CI if a secret pattern is detected in the diff. Trufflehog was considered but gitleaks has lower false-positive rate on JS/Python codebases.

**Deploy implementation:**

- `railway.json` in repo root specifies the build (Nixpacks → Python) and start command (`uvicorn backend.main:app --host 0.0.0.0 --port $PORT`).
- `vercel.json` in repo root specifies build (`cd frontend && npm run build`), output dir, and CSP/HSTS headers.
- `.github/workflows/deploy-smoke.yml` runs after the platforms finish deploying — hits `/healthz` `/readyz` `/api/calendar` against the production URL, fails if any return non-200 or wrong shape. Triggered manually or on workflow_dispatch.

**Rollback drill** is a manual procedure documented in `README.md`.

## 3. Data flow

### 3.1 Sign-in

1. User opens `https://<vercel>` → Vercel CDN serves the static bundle.
2. Bundle imports `@clerk/clerk-react`, mounts `<ClerkProvider>`.
3. `<SignedOut>` shows the sign-in page; `<SignedIn>` shows the planner.
4. User picks Google → Clerk handles OAuth roundtrip → Clerk session cookie set.
5. `useAuth().getToken()` now returns a JWT for the user.

### 3.2 Authenticated API call

1. Frontend calls `getToken()` → JWT.
2. `fetch(BACKEND + "/api/calendar", { headers: { Authorization: \`Bearer ${jwt}\` }})`.
3. The `require_user` route dependency verifies the JWT against the cached Clerk JWKS. On success it returns `user_id = claims["sub"]`, which the handler accepts as an argument.
4. Handler runs, optionally reads/writes `user_profiles` / `saved_trips`.

### 3.3 Authenticated WebSocket

1. Frontend calls `getToken()`, opens `new WebSocket(WS_URL + "?token=" + jwt)`.
2. FastAPI `@app.websocket("/ws")` reads `ws.query_params["token"]`, verifies, derives `user_id`.
3. On any failure → `ws.close(code=1008)`.
4. On success → accept, run normal plan/chat loop. Per-WS `session` dict now also carries `user_id`.

### 3.4 Save trip

1. After a plan completes, user clicks "Save trip".
2. Frontend sends WS message `{ "type": "save_trip", "data": { "gp_slug": ..., "depart_date": ..., ... } }`.
3. Backend reads current `session["plan_state"]` + `session["budget_summary"]` + active constraints, inserts into `saved_trips`.
4. Backend echoes `{ "type": "save_trip_ack", "data": { "id": "..." } }`.

### 3.5 Load trip

1. User clicks a saved trip from "My trips".
2. Frontend sends WS message `{ "type": "load_trip", "data": { "id": "..." } }`.
3. Backend fetches the row, sets `session["plan_state"]` from `plan_snapshot`, sends `{ "type": "trip_loaded", "data": { ... } }`.
4. Frontend hydrates `results`, `selections`, `activeConstraints` from the response.

## 4. Error handling

| Scenario | Behavior |
|---|---|
| Clerk JWT invalid/expired | `401` on HTTP, WS close `1008`. Frontend `useAuth()` will refresh automatically on the next call. |
| Clerk JWKS unreachable | Backend logs error to Sentry + STDOUT; returns `503 Service Unavailable` until JWKS recovers. |
| Postgres down | `/readyz` returns 503; `/healthz` still 200 (process is alive but degraded). Planner flow continues — only save/load fail with `{"error": "persistence unavailable"}`. |
| Sentry down | No effect — `sentry-sdk` swallows its own transport errors. |
| User deletes their Clerk account | Lazy cleanup: rows remain orphaned until a periodic `DELETE FROM user_profiles WHERE last_seen_at < now() - interval '180 days'` (cron task, out of scope for v1; document in README as known gap). |

## 5. Testing

| Layer | What we test | Tooling |
|---|---|---|
| Backend unit | JWT verify happy + 5 failure modes; Postgres model upsert; CSP middleware sets headers in prod | `unittest` (existing) + `pytest-asyncio` if needed |
| Backend integration | `/healthz` returns 200; `/readyz` returns 200 with DB up, 503 with DB down; `/api/calendar` requires Clerk JWT in prod | `unittest` + `httpx.AsyncClient` |
| Frontend unit | Sign-in route renders SignIn; planner gated by `<SignedIn>`; saved-trips list renders | `vitest` (new) |
| E2E (deterministic lane) | Existing 4-spec lane keeps running with `LLM_STUB_MODE=1` and Clerk-bypass via `APP_ENV=test` | Playwright |
| E2E (auth lane) | New spec: mock Clerk JWT via test env, save trip → reload page → load trip → state restored | Playwright |
| Deploy smoke | After Vercel/Railway promote, hit `/healthz` `/readyz` `/api/calendar` from a clean machine | `.github/workflows/deploy-smoke.yml` |

**Test-environment auth:** real Clerk in CI is overkill. The backend's `APP_ENV=test` path accepts the demo token without any JWT verification, exactly as today. Frontend E2E lane keeps the existing demo-token flow by leaving `VITE_CLERK_PUBLISHABLE_KEY` unset — the frontend then falls back to demo-token mode (§2.1 dual-mode rule, "frontend always tries Clerk first").

A separate, env-gated E2E spec (`E2E_INCLUDE_AUTH=1`) covers the Clerk-real path using Clerk's documented test mode (`pk_test_*` publishable key + test email codes). This spec stays out of the default CI lane so the lane keeps no external dependencies.

## 6. Env inventory (final)

| Variable | Where | Public/Secret | Who registers | Free tier? |
|---|---|---|---|---|
| `LLM_PROVIDER` | Railway env | non-secret | — | — |
| `OPENAI_API_KEY` | Railway env | **secret** | already | paid usage |
| `ANTHROPIC_API_KEY` | Railway env | secret | optional | paid usage |
| `SERPAPI_API_KEY` | Railway env | secret | already | 100/mo |
| `FIRECRAWL_API_KEY` | Railway env | secret | already | 500 pages/mo |
| `TAVILY_API_KEY` | Railway env | secret | optional | 1000/mo |
| `APP_ENV` | Railway env | non-secret | — | — |
| `ALLOWED_ORIGINS` | Railway env | non-secret | — | — |
| `DEMO_ACCESS_TOKEN` | Railway env | secret (dev fallback only) | — | — |
| `REQUIRE_CLERK_AUTH` | Railway env | non-secret (defaults true in prod) | — | — |
| `MAX_CONCURRENT_PLANS` | Railway env | non-secret | — | — |
| `HTTP_RATE_LIMIT_PER_MINUTE` | Railway env | non-secret | — | — |
| `WS_CONNECT_LIMIT_PER_MINUTE` | Railway env | non-secret | — | — |
| **`CLERK_SECRET_KEY`** | Railway env | **secret** | **register Clerk** | **10k MAU** |
| **`CLERK_JWT_ISSUER`** | Railway env | non-secret (`https://<your>.clerk.accounts.dev`) | Clerk dashboard | included |
| **`CLERK_JWKS_URL`** | Railway env | non-secret | derived from issuer | included |
| **`DATABASE_URL`** | Railway env | **secret** | **Railway Postgres addon (auto-injected)** | $5/mo Hobby plan covers it |
| **`SENTRY_DSN_BACKEND`** | Railway env | secret | **register Sentry** | 5k errors/mo |
| **`VITE_BACKEND_URL`** | Vercel env | non-secret | — | — |
| **`VITE_WS_URL`** | Vercel env | non-secret | — | — |
| **`VITE_CLERK_PUBLISHABLE_KEY`** | Vercel env | non-secret (public by design) | Clerk dashboard | included |
| **`VITE_SENTRY_DSN_FRONTEND`** | Vercel env | non-secret (public by design — Sentry DSN is public) | Sentry dashboard | included |
| **`VITE_APP_ENV`** | Vercel env | non-secret | — | — |

**Bold rows** are new in this design. The "register" column flags external sign-ups the user must perform; everything else falls out of Vercel + Railway dashboards.

Final registration checklist (delivered at end of implementation):

1. Sign up Clerk → create an application → copy publishable + secret key.
2. Sign up Sentry → create one project per side (`f1-paddock-backend`, `f1-paddock-frontend`).
3. Provision Railway → add Postgres → backend service automatic.
4. Provision Vercel → connect repo → set env vars from the table above.
5. Optional: SerpAPI / Firecrawl / OpenAI accounts already in `backend/.env.example`.

## 7. Out of scope (explicit)

- **Per-user billing / Stripe integration** — orthogonal product decision.
- **Admin dashboard / impersonation** — not needed for a portfolio app.
- **Multi-tenant orgs** — Clerk supports it but adds two columns + UI; v2.
- **Email digests / notifications** — no SMTP integration in v1.
- **Custom domain** — Vercel/Railway subdomains are fine; 15-min task later.
- **Mobile app / PWA install** — deployment-design.md already deferred this.
- **i18n of new auth UI** — Clerk's localization is opt-in; not configured in v1.
- **Audit log table** — `last_seen_at` is enough for v1; full audit log is v2.

## 8. Implementation slicing

This design is large enough that one PR is unrealistic. The implementation will be sliced as follows (executed via `superpowers:writing-plans` after design approval). Each slice ends green (CI + browser-verified) before the next begins.

1. **S1 — Persistence foundation:** Postgres addon docs in env example, SQLAlchemy + Alembic, three tables, no UI yet. Backend tests pass. (Smallest blast radius — no user-facing change.)
2. **S2 — Clerk backend verify + dual mode:** `verify_clerk_jwt`, dependency, WS query-param path, `REQUIRE_CLERK_AUTH` flag. Existing tests still pass; new test for JWT verify.
3. **S3 — Clerk frontend integration:** `@clerk/clerk-react`, `<ClerkProvider>`, `<SignIn>`, `<UserButton>`, replace `DEMO_TOKEN` bake with `getToken()`. Existing E2E lane still green via `APP_ENV=test` Clerk bypass.
4. **S4 — Save/Load trip + My Trips UI:** new WS messages, new route, new component. New Playwright spec.
5. **S5 — Health endpoints + Sentry:** `/healthz` `/readyz`, Sentry init both sides, structured JSON logs.
6. **S6 — Security headers + CSP:** middleware backend, `vercel.json` headers frontend, validate Clerk's iframe flows still work.
7. **S7 — Deploy implementation:** `railway.json`, `vercel.json` (auth + redirects), deploy-smoke workflow, README runbook.
8. **S8 — Secret scanning CI:** gitleaks workflow, baseline allowlist.

Each slice produces:
- Code change.
- New tests (unit + integration where applicable).
- E2E updates if user-facing.
- `CHANGELOG.md` entry under `[Unreleased]`.
- One commit (or fused two if cleanup-only follows main change).

Reviewer (you) sees each slice in the chat before commit, with the diff + run output. The slice does not commit until you OK it.

## 9. Acceptance criteria (binding)

The phase is done when **all** of these hold:

1. `git pull` from a fresh machine + filling the env values in §6 + following the README runbook results in:
   - `https://<vercel-domain>` loads, prompts Clerk sign-in.
   - Sign-in with Google or email succeeds.
   - Planner runs end-to-end for a real GP.
   - "Save trip" button persists to Postgres; reloading the page + "My trips" restores the plan.
2. `curl https://<railway>/healthz` → 200. `curl https://<railway>/readyz` → 200 with `{"db": "ok"}`.
3. `curl https://<railway>/api/calendar` without a token → 401.
4. `curl https://<railway>/api/calendar` with a valid Clerk JWT → 200.
5. CI passes:
   - existing 4-spec deterministic lane,
   - new auth-lane spec (save/load trip),
   - new backend tests (JWT verify, model upsert, health endpoints),
   - gitleaks finds no secrets,
   - `npm audit` and equivalent backend check pass.
6. `grep -r "CLERK_SECRET_KEY\|DATABASE_URL\|SENTRY_DSN_BACKEND\|OPENAI_API_KEY\|SERPAPI_API_KEY\|FIRECRAWL_API_KEY" frontend/dist/` returns nothing.
7. Sentry receives a deliberate test error from both sides.
8. README has a "Deploy from scratch" section that, followed literally, completes a deploy in under 30 minutes for someone who has never seen the project.

## 10. Open questions (none currently blocking)

- Whether to also store a per-user "preferred home airport" in `saved_constraints`. Decision: not in v1 — keep `saved_constraints` schema flat JSONB and add it lazily.
- Whether to use Clerk's webhooks for user-deleted cleanup. Decision: no — lazy expiry is enough for v1.
- Whether `traces_sample_rate=0.1` is right for Sentry. Decision: start there; tune after first week of real traffic.
