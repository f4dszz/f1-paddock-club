# Enterprise Floor — Deploy / Registration Checklist

This is the operator checklist for what *you, the human* need to register, top up, and paste before the deployed app works end-to-end. Code is shipped; only the external accounts + secrets are missing.

Status of code: **all 8 implementation slices landed.** Verification:
- 117/117 backend tests pass
- Frontend builds clean, 0 npm vulnerabilities
- Default E2E lane 3/3, full deterministic lane 7/7 (smoke + refine + saved_trips + quote_incomplete + explain)
- gitleaks scan: no leaks across 97 commits
- `scripts/check-local.sh` 7/7 PASS

## 1. Services to register (free tiers cover a portfolio demo)

| Service | URL | Free tier | What it costs if you exceed it |
|---|---|---|---|
| **Clerk** | https://dashboard.clerk.com | 10,000 MAU | $25/mo Production plan when MAU > 10k |
| **Sentry** | https://sentry.io | 5,000 errors/mo, 1 team member | $26/mo Team plan |
| **Railway** | https://railway.app | $5/mo Hobby credit (no card required for trial) | pay-as-you-go beyond $5; typical small demo costs ~$3–8/mo |
| **Vercel** | https://vercel.com | Hobby plan (free, non-commercial) | $20/mo Pro plan for team/commercial |
| **OpenAI** | https://platform.openai.com | none free | pay-as-you-go; gpt-4o-mini ~$0.001/plan call |
| **SerpAPI** *(optional)* | https://serpapi.com | 100 searches/mo | $50/mo Developer |
| **Firecrawl** *(optional)* | https://firecrawl.dev | 500 pages/mo | $19/mo Hobby |

**Top-up notes:**
- The only service you *must* fund is OpenAI (the planner makes 4–7 LLM calls per trip). $5–10 of credit covers many test runs.
- All others are usable on free tier for a single-developer demo.
- Railway's $5/mo "Hobby" credit covers running a small FastAPI service + Postgres continuously for a portfolio demo — monitor usage in the first week.

## 2. Step-by-step

### 2.1 Register accounts (5 min total)

Open the 4 dashboards in 4 tabs and create accounts. No payment required upfront for any of them.

### 2.2 Clerk — create application (3 min)

1. Dashboard → **Create Application** → name it `f1-paddock-club`.
2. Enable sign-in methods: Google, GitHub, Email code (recommended); add others as you like.
3. From left sidebar → **API Keys**, copy:
   - **Publishable key** (`pk_test_...` or `pk_live_...`) → goes to Vercel as `VITE_CLERK_PUBLISHABLE_KEY`
   - **Secret key** (`sk_test_...` or `sk_live_...`) → goes to Railway as `CLERK_SECRET_KEY`
4. From the application's **API Keys → JWT** section (or "Configure → JWT Templates"), copy your **issuer URL**. It looks like `https://your-app-name.clerk.accounts.dev`.
   - Goes to Railway as `CLERK_JWT_ISSUER`
   - The JWKS URL is just the issuer + `/.well-known/jwks.json`. Goes to Railway as `CLERK_JWKS_URL`.

### 2.3 Sentry — create two projects (4 min)

1. Dashboard → **Projects → Create Project**:
   - Platform: **FastAPI** → name `f1-paddock-backend`. Copy DSN → Railway as `SENTRY_DSN_BACKEND`.
   - Platform: **React** → name `f1-paddock-frontend`. Copy DSN → Vercel as `VITE_SENTRY_DSN_FRONTEND`.

### 2.4 Railway — provision backend + Postgres (6 min)

1. **New Project → Deploy from GitHub repo** → pick this repo.
2. After the first auto-deploy attempt, click **+ New → Database → Postgres**. Railway injects `DATABASE_URL` automatically into the backend service.
3. On the **backend service → Variables**, paste:
   ```
   APP_ENV=production
   REQUIRE_CLERK_AUTH=true
   ALLOWED_ORIGINS=https://<your-vercel-domain>      # fill after step 2.5
   OPENAI_API_KEY=sk-...
   CLERK_SECRET_KEY=sk_test_...                       (from 2.2)
   CLERK_JWT_ISSUER=https://your-app.clerk.accounts.dev
   CLERK_JWKS_URL=https://your-app.clerk.accounts.dev/.well-known/jwks.json
   SENTRY_DSN_BACKEND=https://...@oXXXXX.ingest.sentry.io/YYYYY
   # Optional:
   SERPAPI_API_KEY=...
   FIRECRAWL_API_KEY=...
   ```
4. Note the public backend URL — looks like `https://<service-name>.up.railway.app`. You'll paste it into Vercel next.

### 2.5 Vercel — provision frontend (5 min)

1. **Add New → Project → Import Git Repository** → pick this repo.
2. Framework Preset: **Other** (the repo's `vercel.json` provides the build + headers).
3. Settings → Environment Variables, paste (all environments):
   ```
   VITE_BACKEND_URL=https://<service-name>.up.railway.app
   VITE_WS_URL=wss://<service-name>.up.railway.app/ws
   VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
   VITE_SENTRY_DSN_FRONTEND=https://...@oXXXXX.ingest.sentry.io/YYYYY
   VITE_APP_ENV=production
   ```
4. Deploy. Note the public frontend URL — `https://<project>.vercel.app`.

### 2.6 Close the loop on Railway (1 min)

Go back to Railway → backend service → Variables, update:
```
ALLOWED_ORIGINS=https://<your-vercel-domain>.vercel.app
```
Restart the service so CORS + WS origin check pick it up.

### 2.7 Verify (3 min)

GitHub → **Actions → Deploy smoke → Run workflow** with:
- `backend_url` = your Railway URL
- `frontend_url` = your Vercel URL

All steps should pass.

Then in a browser, open the Vercel URL:
1. Clerk sign-in page appears.
2. Sign in with Google → planner UI loads.
3. Plan a trip end-to-end → click **SAVE** → reload page → **MY TRIPS** → click **Load** → the saved trip restores.

## 3. Env-var summary (the only thing left for you to fill)

### Railway (backend) — 11 vars to set, 3 optional
| Var | Source | Required? |
|---|---|---|
| `APP_ENV=production` | constant | yes |
| `REQUIRE_CLERK_AUTH=true` | constant | yes |
| `ALLOWED_ORIGINS` | Vercel domain | yes |
| `OPENAI_API_KEY` | OpenAI dashboard | yes |
| `CLERK_SECRET_KEY` | Clerk dashboard | yes |
| `CLERK_JWT_ISSUER` | Clerk dashboard | yes |
| `CLERK_JWKS_URL` | derived from issuer | yes |
| `SENTRY_DSN_BACKEND` | Sentry backend project | yes |
| `DATABASE_URL` | Railway Postgres addon — **auto-injected** | yes (auto) |
| `SENTRY_TRACES_SAMPLE_RATE=0.1` | constant (optional override) | no |
| `MAX_CONCURRENT_PLANS=5` | constant (optional override) | no |
| `HTTP_RATE_LIMIT_PER_MINUTE=60` | constant (optional override) | no |
| `WS_CONNECT_LIMIT_PER_MINUTE=20` | constant (optional override) | no |
| `SERPAPI_API_KEY` | SerpAPI dashboard | optional |
| `FIRECRAWL_API_KEY` | Firecrawl dashboard | optional |

### Vercel (frontend) — 5 vars to set
| Var | Source | Required? |
|---|---|---|
| `VITE_BACKEND_URL` | Railway service URL | yes |
| `VITE_WS_URL` | Railway service URL with `/ws` and `wss://` | yes |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk dashboard | yes |
| `VITE_SENTRY_DSN_FRONTEND` | Sentry frontend project | yes |
| `VITE_APP_ENV=production` | constant | yes |

## 4. What you do NOT need to do

- No Postgres setup — Railway's one-click addon handles it. Alembic migrations run automatically on every deploy via `railway.json`'s `buildCommand`.
- No code changes — every code change is committed to `main`.
- No CSP tuning — the policy in `vercel.json` + `backend/security_headers.py` already allows Clerk + Sentry; you only revisit it if you add a new external host (e.g. analytics).
- No iCal export, custom domain, mobile/PWA polish, or audit log — those live in Phase 5.

## 5. Rough monthly cost on free tiers

| Item | Free tier expectation |
|---|---|
| Clerk | $0 (10k MAU) |
| Sentry | $0 (5k errors) |
| Railway | ~$3-8/mo (Hobby $5 credit, Postgres + small FastAPI) |
| Vercel | $0 (Hobby) |
| OpenAI | depends on usage; each full plan = ~$0.005–0.02 with gpt-4o-mini |
| **Total** | **~$5–15/mo for a portfolio demo with modest usage** |

If costs become a concern, the largest lever is Railway: scale-to-zero on Fly.io is a future migration option (documented in `docs/deployment-design.md` §2).
