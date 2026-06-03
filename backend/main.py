"""FastAPI server for the F1 Paddock Club Travel Assistant.

Provides:
- POST /plan  — trigger a full planning run, returns complete result
- WS   /ws    — WebSocket session with two-lane routing:
                  First message (type=plan) → Lane 1 (full DAG pipeline)
                  Subsequent messages (type=chat) → Lane 2 (supervisor refinement)

WebSocket message protocol:

  Client → Server:
    {"type": "plan", "data": {TripRequest fields}}   — start/restart full plan
    {"type": "chat", "data": "user message text"}     — refine existing plan
    {"type": "quote", "data": {"selections": {...}}}  — recompute selected total

  Server → Client:
    {"type": "message", "data": {"agent": "...", "text": "..."}}  — status update
    {"type": "result",  "data": {tickets, transport, hotel, ...}} — full state snapshot
    {"type": "quote",   "data": {quote_id, budget_summary}}       — selected quote
    {"type": "reply",   "data": "supervisor text response"}       — Lane 2 text reply
    {"type": "done"}                                               — request complete
    {"type": "error",   "data": "error description"}              — error
"""

from __future__ import annotations
import asyncio
import copy
import json
import logging
import os
import time

from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError, field_validator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from logging_config import setup_logging
from graph import plan_trip
from refine import refine_plan, RefineDeadlineError
from llm import LLMDailyLimitError, check_llm_quota
from _session import create_session, append_turn, clear_history, get_history
from tools._race_calendar import all_races, upcoming_races, is_past
from tools.recompute import recompute_budget
from tools._trip_dates import validate_trip_dates
from auth import AuthError, require_user, require_user_for_ws
from health import router as health_router
from observability import install_observability
from security_headers import install_security_headers


logger = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return max(value, minimum)
    except (TypeError, ValueError):
        return default


_APP_ENV = os.environ.get("APP_ENV") or os.environ.get("ENV") or "local"
_IS_LOCAL_ENV = _APP_ENV.strip().lower() in {"", "local", "dev", "development", "test"}
_DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
_ALLOWED_ORIGINS = _csv_env("ALLOWED_ORIGINS") or (_DEV_ORIGINS if _IS_LOCAL_ENV else [])
_ALLOWED_ORIGINS_SET = set(_ALLOWED_ORIGINS)
# Auth gating lives entirely in auth.py (Clerk + demo-token dual mode). The
# old module-level _REQUIRE_DEMO_TOKEN here was dead code (never read) and
# implied a "non-local => gated" behavior that auth.py now enforces directly.
_MAX_CONCURRENT_PLANS = _int_env("MAX_CONCURRENT_PLANS", 5)
_PLAN_ACQUIRE_TIMEOUT_SECONDS = _int_env("PLAN_ACQUIRE_TIMEOUT_SECONDS", 5)
_HTTP_LIMIT_PER_MINUTE = _int_env("HTTP_RATE_LIMIT_PER_MINUTE", 60)
_WS_LIMIT_PER_MINUTE = _int_env("WS_CONNECT_LIMIT_PER_MINUTE", 20)
_plan_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PLANS)

# Number of trusted reverse-proxy hops in front of the app. The rightmost
# N entries of X-Forwarded-For were appended by our own proxies; the entry
# just before them is the real client. Defaults to 1 (single Railway proxy).
# Set to 0 only when the app is directly internet-facing (then XFF is fully
# untrusted and we ignore it). See _trusted_forwarded_ip (security-3).
_TRUSTED_PROXY_HOPS = _int_env("TRUSTED_PROXY_HOPS", 1, minimum=0)

# WebSocket hardening (BS-05). Idle timeout closes silent sockets that
# authenticated then went quiet (slow-loris); the concurrency cap bounds
# the number of simultaneously OPEN sessions on this single process.
# Both env-configurable. NOTE: the concurrency counter is in-process only
# (no cross-replica coordination) — consistent with IPRateLimiter.
_WS_IDLE_TIMEOUT_SECONDS = _int_env("WS_IDLE_TIMEOUT_SECONDS", 300)
_MAX_WS_CONNECTIONS = _int_env("MAX_WS_CONNECTIONS", 100)
_ws_open_connections = 0
_ws_conn_lock = asyncio.Lock()


class ServerBusyError(RuntimeError):
    pass


class IPRateLimiter:
    """Small in-process sliding-window limiter for demo-stage abuse control."""

    def __init__(self, max_per_window: int, window_seconds: int):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        if self.max_per_window <= 0:
            return True
        now = time.monotonic()
        events = self._events[ip]
        cutoff = now - self.window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self.max_per_window:
            return False
        events.append(now)
        return True


_http_rate_limiter = IPRateLimiter(_HTTP_LIMIT_PER_MINUTE, 60)
_ws_connect_limiter = IPRateLimiter(_WS_LIMIT_PER_MINUTE, 60)


def _trusted_forwarded_ip(forwarded: str) -> str | None:
    """Pick the real client IP from X-Forwarded-For, honoring trusted-proxy hops.

    XFF is "client, proxy1, proxy2, ..." where the rightmost _TRUSTED_PROXY_HOPS
    entries were appended by proxies we control (e.g. Railway's edge). The entry
    immediately to the left of those is the genuine client. Earlier (leftmost)
    entries are client-supplied and forgeable; trusting them lets an attacker
    rotate a fake IP per request to get a fresh rate-limit bucket (security-3).

    With _TRUSTED_PROXY_HOPS=1 (default, single trusted proxy) this is the
    rightmost entry. With 0 (app is directly internet-facing) XFF is fully
    untrusted and we return None so the caller falls back to the socket peer.

    NOTE: this enforces the hop COUNT, not a proxy IP allow-list. The deeper
    fix is uvicorn --proxy-headers + forwarded-allow-ips, or a vetted
    ProxyHeadersMiddleware; documented as a known limitation.
    """
    if _TRUSTED_PROXY_HOPS <= 0:
        return None
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if not parts:
        return None
    # Index from the right: hops=1 -> parts[-1]; hops=2 -> parts[-2], etc.
    idx = len(parts) - _TRUSTED_PROXY_HOPS
    if idx < 0:
        # Fewer entries than declared trusted hops: the chain is shorter than
        # expected (someone may be talking to us without going through all
        # proxies). Fall back to the leftmost entry rather than an out-of-range
        # index; the socket-peer fallback in _client_ip still applies upstream.
        idx = 0
    return parts[idx] or None


def _client_ip(request: Request) -> str:
    ip = _trusted_forwarded_ip(request.headers.get("x-forwarded-for", ""))
    if ip:
        return ip
    return request.client.host if request.client else "unknown"


def _ws_client_ip(ws: WebSocket) -> str:
    ip = _trusted_forwarded_ip(ws.headers.get("x-forwarded-for", ""))
    if ip:
        return ip
    return ws.client.host if ws.client else "unknown"


def _check_http_rate_limit(request: Request) -> None:
    """Per-IP rate limit for HTTP routes. Auth is enforced separately via Depends(require_user)."""
    ip = _client_ip(request)
    if not _http_rate_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many requests")


def _http_rate_limit_dep(request: Request) -> None:
    """Dependency form of the rate limit. Declared BEFORE require_user on each
    route so it runs first — otherwise failed-auth floods never reach the
    limiter (they 401 out) and so are never counted or throttled."""
    _check_http_rate_limit(request)


def _ws_origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "")
    if not origin or not _ALLOWED_ORIGINS_SET:
        return True
    return origin in _ALLOWED_ORIGINS_SET


async def _run_plan_with_limit(payload: dict) -> dict:
    try:
        async with asyncio.timeout(_PLAN_ACQUIRE_TIMEOUT_SECONDS):
            await _plan_semaphore.acquire()
    except TimeoutError as exc:
        raise ServerBusyError("Server is busy. Please try again shortly.") from exc
    try:
        return await asyncio.to_thread(plan_trip, payload)
    finally:
        _plan_semaphore.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize file logging only when the app actually starts serving.
    # Bare imports (e.g. `from main import TripRequest` in a script)
    # no longer write to the log file.
    log_file = setup_logging()
    logger.info("FastAPI starting, log file: %s", log_file)
    # Fail fast instead of booting a non-local deploy with an empty origin
    # allowlist, which would silently break CORS for the real frontend AND
    # disable the WebSocket Origin gate while /healthz still reported "ok".
    if not _IS_LOCAL_ENV and not _ALLOWED_ORIGINS:
        raise RuntimeError(
            "ALLOWED_ORIGINS must be set in non-local environments "
            "(empty allowlist breaks frontend CORS and disables the WS Origin gate)."
        )
    _startup_config_checks()
    yield
    logger.info("FastAPI shutting down")


def _startup_config_checks() -> None:
    """Fail fast (or loudly warn) on misconfigured production deploys.

    Previously only ALLOWED_ORIGINS was guarded at boot, so a prod deploy
    with auth enforced but a missing/typo'd CLERK_JWT_ISSUER booted clean and
    passed /healthz, then 503'd on every authenticated request — a green probe
    on a dead app. Likewise a prod deploy with no LLM key silently served mock
    itineraries. We now assert the auth config and warn loudly on mock LLM
    (deploy-cicd-8). Pure local/dev/test is exempt so demos still boot.
    """
    if _IS_LOCAL_ENV:
        return

    # Auth: when Clerk is enforced, the issuer (and resolvable JWKS) MUST be
    # present, or every authenticated request will 503 behind a green probe.
    from auth import _require_clerk, _clerk_issuer, _clerk_jwks_url, _clerk_audience

    if _require_clerk():
        if not _clerk_issuer():
            raise RuntimeError(
                "REQUIRE_CLERK_AUTH/production is set but CLERK_JWT_ISSUER is "
                "missing — authenticated requests would 503 on a green probe."
            )
        if not _clerk_jwks_url():
            raise RuntimeError(
                "Clerk auth is enforced but no JWKS URL is resolvable "
                "(set CLERK_JWKS_URL or a valid CLERK_JWT_ISSUER)."
            )
        if not _clerk_audience():
            # Per GLOBAL DECISIONS: missing CLERK_AUDIENCE in production is a
            # config WARNING (audience check stays optional), not a hard crash.
            logger.warning(
                "CLERK_AUDIENCE is not set in production: JWT audience is NOT "
                "verified, so a token minted for another app on the same Clerk "
                "issuer would be accepted. Set CLERK_AUDIENCE to harden."
            )

    # LLM: a prod deploy with no provider key silently degrades to mock plans.
    # Don't hard-fail (mock is a valid graceful-degradation path) but make the
    # degraded state impossible to miss in logs.
    from llm import PROVIDER as _LLM_PROVIDER

    _provider_key_env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(_LLM_PROVIDER)
    if _provider_key_env and not os.environ.get(_provider_key_env):
        logger.warning(
            "LLM_PROVIDER=%s but %s is not set in a non-local environment: "
            "the app will serve MOCK itineraries/plans, not real LLM output.",
            _LLM_PROVIDER,
            _provider_key_env,
        )


# Disable interactive docs on real deploys: the default Swagger/ReDoc pages
# load assets from cdn.jsdelivr.net, which the production CSP blocks (blank
# page), and /openapi.json would otherwise expose the full schema unauthed.
_DOCS_KWARGS = (
    {} if _IS_LOCAL_ENV else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)
app = FastAPI(title="F1 Paddock Club", version="0.2.0", lifespan=lifespan, **_DOCS_KWARGS)

install_observability(app)
install_security_headers(app)
app.include_router(health_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


_SUPPORTED_CURRENCIES = {"EUR", "USD", "CNY"}
_MAX_LEGACY_EXTRA_DAYS = 27


class TripRequest(BaseModel):
    gp_name: str = "Italian GP"
    gp_city: str = "Monza"
    gp_date: str = "Sep 6"
    origin: str = "New York"
    budget: float = 2500
    currency: str = "EUR"         # "EUR" | "USD" | "CNY"
    stand_pref: str = "any"
    extra_days: int = 2           # legacy; ignored when depart_date/return_date are set
    depart_date: str = ""         # optional explicit travel dates (ISO YYYY-MM-DD)
    return_date: str = ""
    stops: str = ""
    special_requests: str = ""

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, v):
        # Accept any case (e.g. "usd") and normalize to upper.
        # Reject anything outside the supported set — explicit invalid input
        # must not silently fall back to EUR.
        code = str(v or "EUR").strip().upper()
        if code not in _SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency {v!r}. Must be one of: "
                f"{', '.join(sorted(_SUPPORTED_CURRENCIES))}."
            )
        return code

    @field_validator("budget")
    @classmethod
    def _validate_budget(cls, v):
        amount = float(v)
        if amount <= 0:
            raise ValueError("Budget must be greater than 0")
        return amount


def _validate_plan_payload(data) -> TripRequest:
    """Wrap TripRequest validation with a clean error surface.

    Raises ValueError(reason) on invalid input. Used by both HTTP and
    WS entry points so they share the same validation contract.

    Three layers of validation happen here, in order:
      1. Shape  — reject non-dict payloads outright
      2. Schema — Pydantic + the currency field_validator
      3. Travel-date semantics — validate_trip_dates() on the pair
         (depart_date, return_date). Lets us surface "depart after
         return" at the API boundary instead of producing a bad plan.

    Non-dict payloads and explicit invalid dates are rejected rather
    than silently falling back to defaults — explicit bad input
    deserves an explicit error.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"plan payload must be a JSON object, got {type(data).__name__}"
        )
    try:
        req = TripRequest(**data)
    except ValidationError as e:
        # Surface the first field error in plain text; FastAPI's own
        # error body is noisy and not meant for end-user consumption.
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        msg = first.get("msg", "invalid input")
        raise ValueError(f"{loc}: {msg}" if loc else msg)

    ok, reason = validate_trip_dates(req.gp_date, req.depart_date, req.return_date)
    if not ok:
        raise ValueError(reason)

    if not (req.depart_date and req.return_date):
        if req.extra_days < 0:
            raise ValueError("extra_days must be between 0 and 27")
        if req.extra_days > _MAX_LEGACY_EXTRA_DAYS:
            raise ValueError("extra_days must be between 0 and 27")

    return req


def _state_snapshot(state: dict) -> dict:
    """Extract the serializable result from state for the client."""
    return {
        "tickets": state.get("tickets", []),
        "transport": state.get("transport", []),
        "hotel": state.get("hotel", []),
        "itinerary": state.get("itinerary", []),
        "tour": state.get("tour", []),
        "budget_summary": state.get("budget_summary"),
        "active_constraints": state.get("active_constraints", {}),
    }


# ── GET /api/calendar — GP list for frontend ────────────────────────

@app.get("/api/calendar")
async def get_calendar(
    request: Request,
    _rl: None = Depends(_http_rate_limit_dep),
    user_id: str = Depends(require_user),
):
    """Return the 2026 race calendar for the GP selection grid."""
    from datetime import date
    today = date.today()
    races = all_races()
    return [
        {
            "gp_name": r["gp_name"],
            "city": r["city"],
            "country": r["country"],
            "race_date": r["race_date"],
            "round": r["round"],
            "sprint": r.get("sprint", False),
            "is_past": is_past(r["gp_name"], today),
        }
        for r in races
    ]


# ── POST /plan (unchanged, backward compatible) ────────────────────

@app.post("/plan")
async def plan(
    payload: dict,
    request: Request,
    _rl: None = Depends(_http_rate_limit_dep),
    user_id: str = Depends(require_user),
):
    """Run the full planning pipeline and return the result.

    Validates explicitly via _validate_plan_payload so that invalid
    input (e.g. unsupported currency) surfaces as a clean 400 rather
    than Pydantic's default 422 or a downstream 500.
    """
    try:
        req = _validate_plan_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        result = await _run_plan_with_limit(req.model_dump())
    except ServerBusyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    snapshot = _state_snapshot(result)
    snapshot["messages"] = result.get("messages", [])
    return snapshot


# ── Clerk webhook: user.deleted → erase user_profiles (+ cascade trips) ──
# Right-to-erasure path (BS-03). When a user deletes their Clerk account,
# Clerk POSTs a svix-signed `user.deleted` event here and we drop the
# corresponding user_profiles row; the saved_trips FK cascade removes their
# trips + stored email. Verification:
#   - If CLERK_WEBHOOK_SECRET is set, the svix signature is REQUIRED. We use
#     the `svix` library when installed; otherwise we verify the HMAC-SHA256
#     signature defensively in-process (same scheme svix uses) so the endpoint
#     is never an unauthenticated delete primitive.
#   - If CLERK_WEBHOOK_SECRET is unset, the endpoint is disabled (404-style
#     503) so it cannot be abused before it is configured.
def _clerk_webhook_secret() -> str:
    return (os.environ.get("CLERK_WEBHOOK_SECRET") or "").strip()


def _verify_svix_signature(secret: str, headers: dict, body: bytes) -> bool:
    """Verify a svix webhook signature. Returns True iff valid.

    Tries the official `svix` library first; falls back to a defensive
    in-process HMAC-SHA256 check matching svix's signing scheme
    (signed content = "{id}.{timestamp}.{body}", key = base64 of the part
    after the "whsec_" prefix). Either path is constant-time on the digest.
    """
    svix_id = headers.get("svix-id") or headers.get("webhook-id") or ""
    svix_ts = headers.get("svix-timestamp") or headers.get("webhook-timestamp") or ""
    svix_sig = headers.get("svix-signature") or headers.get("webhook-signature") or ""
    if not (svix_id and svix_ts and svix_sig):
        return False

    try:  # Preferred: the vetted svix verifier (handles tolerance, rotation).
        from svix.webhooks import Webhook  # type: ignore

        Webhook(secret).verify(
            body,
            {
                "svix-id": svix_id,
                "svix-timestamp": svix_ts,
                "svix-signature": svix_sig,
            },
        )
        return True
    except ImportError:
        # svix not installed — defensive in-process verification. Note the
        # dependency so it can be added to requirements by the ci-deploy batch.
        logger.warning(
            "svix library not installed; using in-process HMAC verification "
            "for the Clerk webhook (add `svix` to requirements to use the "
            "vetted verifier)."
        )
    except Exception:
        return False

    import base64
    import hashlib
    import hmac

    key = secret
    if key.startswith("whsec_"):
        key = key[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(key)
    except Exception:
        return False
    signed_content = f"{svix_id}.{svix_ts}.".encode() + body
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode()
    # svix-signature header is a space-separated list of "v1,<sig>" entries.
    for part in svix_sig.split(" "):
        _, _, sig = part.partition(",")
        if sig and hmac.compare_digest(sig, expected):
            return True
    return False


def _delete_clerk_user_sync(clerk_user_id: str) -> bool:
    with _SessionLocal() as db:
        return _repo.delete_user_by_clerk_id(db, clerk_user_id=clerk_user_id)


@app.post("/webhooks/clerk")
async def clerk_webhook(
    request: Request,
    _rl: None = Depends(_http_rate_limit_dep),
):
    """Handle Clerk webhooks. Only user.deleted triggers a side effect."""
    secret = _clerk_webhook_secret()
    if not secret:
        # Not configured: refuse rather than expose an unauthenticated path.
        raise HTTPException(status_code=503, detail="webhooks not configured")
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not _verify_svix_signature(secret, headers, body):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        event = json.loads(body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid JSON body")
    event_type = event.get("type")
    if event_type != "user.deleted":
        # Acknowledge other events so Clerk does not retry; no side effect.
        return {"status": "ignored", "type": event_type}
    clerk_user_id = str((event.get("data") or {}).get("id") or "")
    if not clerk_user_id:
        raise HTTPException(status_code=400, detail="missing user id")
    deleted = await asyncio.to_thread(_delete_clerk_user_sync, clerk_user_id)
    logger.info("clerk webhook user.deleted: id=%s deleted=%s", clerk_user_id, deleted)
    return {"status": "ok", "deleted": deleted}


# ── WebSocket /ws (two-lane session routing) ────────────────────────

MAX_WS_MESSAGE_SIZE = 16 * 1024  # 16KB max per ws message


def _build_trace_events(
    before_state: dict | None,
    after_state: dict,
    failed_tools: list[str] | None = None,
    updated_fields: list[str] | None = None,
) -> list[dict]:
    """Derive trace events from state before/after a handler run.

    Emits three event kinds (minimum viable observability surface):
      - state_apply  (one per changed list field — by content, not just count)
      - tool_fail    (one per failed Lane-2 tool call)
      - budget_final (once, from final budget_summary)

    state_apply detection: Lane 2 callers pass an explicit `updated_fields`
    list from `_apply_tool_updates`, which is the authoritative signal
    that a tool wrote to that field (even if counts match, e.g. 3 hotels
    replaced by 3 different hotels). Lane 1 callers pass None, in which
    case we fall back to a JSON content diff (every agent run rewrites
    state fresh, so this catches real content changes).
    """
    events: list[dict] = []
    before = before_state or {}

    for field in ("tickets", "transport", "hotel", "itinerary", "tour"):
        b = before.get(field) or []
        a = after_state.get(field) or []

        if updated_fields is not None:
            # Lane 2: trust the refine closure's report
            changed = field in updated_fields
        else:
            # Lane 1 (or unknown): content-aware diff
            try:
                changed = json.dumps(a, sort_keys=True, ensure_ascii=False) \
                       != json.dumps(b, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                changed = len(a) != len(b)

        if changed:
            events.append({
                "event": "state_apply",
                "field": field,
                "before_count": len(b),
                "after_count": len(a),
            })

    for name in (failed_tools or []):
        events.append({"event": "tool_fail", "tool": name})

    bs = after_state.get("budget_summary") or {}
    if bs:
        events.append({
            "event": "budget_final",
            "total": bs.get("total"),
            "budget": bs.get("budget"),
            "currency": bs.get("currency"),
            "within_budget": bs.get("within_budget"),
            "quote_complete": bs.get("quote_complete", True),
            "missing_price_categories": bs.get("missing_price_categories") or [],
        })

    return events


async def _send_trace(ws: WebSocket, events: list[dict], enabled: bool) -> None:
    if not enabled or not events:
        return
    for ev in events:
        await ws.send_json({"type": "trace", "data": ev})

@app.websocket("/ws")
async def websocket_session(ws: WebSocket):
    """WebSocket endpoint with session state and two-lane routing.

    The connection IS the session. State lives for the duration of
    the WebSocket connection. No external session store needed.

    Routing:
      type=plan → Lane 1 (graph.py): full parallel DAG, produces complete plan
      type=chat → Lane 2 (refine.py): supervisor agent, targeted updates

    type=plan can be sent again to start fresh (clears state).
    type=chat as the very first message goes to refine.py planning mode
    (produces 3/5 sections — no itinerary/tour).
    """
    client_ip = _ws_client_ip(ws)
    if not _ws_connect_limiter.allow(client_ip):
        await ws.close(code=1008)
        return
    if not _ws_origin_allowed(ws):
        await ws.close(code=1008)
        return
    try:
        user_id = require_user_for_ws(ws)
    except AuthError:
        await ws.close(code=1008)
        return

    # Concurrency cap (BS-05): bound the number of simultaneously OPEN sessions
    # so an attacker cannot hold the single process hostage with many silent
    # connections. The connect-RATE limiter above does not cap concurrency.
    global _ws_open_connections
    async with _ws_conn_lock:
        if _ws_open_connections >= _MAX_WS_CONNECTIONS:
            # 1013 = "Try Again Later" (server overloaded). Reject before accept.
            await ws.close(code=1013)
            return
        _ws_open_connections += 1

    await ws.accept()
    session = create_session()
    session["user_id"] = user_id

    try:
        while True:
            # Idle timeout (BS-05): close sockets that authenticated then went
            # silent. asyncio.wait_for raises TimeoutError when no frame arrives
            # within the window, which we map to a clean 1001 (going away) close.
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(), timeout=_WS_IDLE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.info("WebSocket idle timeout after %ss", _WS_IDLE_TIMEOUT_SECONDS)
                try:
                    await ws.send_json({"type": "error", "data": "Idle timeout"})
                except Exception:
                    pass
                await ws.close(code=1001)
                return

            # Minimal safety: reject oversized messages
            if len(raw) > MAX_WS_MESSAGE_SIZE:
                await ws.send_json({"type": "error", "data": "Message too large"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")
            msg_data = msg.get("data", {})

            # Backward compat: raw TripRequest without {type, data} envelope.
            if not msg_type and msg.get("gp_name"):
                msg_type = "plan"
                msg_data = msg

            if msg_type == "plan":
                await _handle_plan(ws, msg_data, session)

            elif msg_type == "chat":
                await _handle_chat(ws, msg_data, session)

            elif msg_type == "quote":
                await _handle_quote(ws, msg_data, session)

            elif msg_type == "save_trip":
                await _handle_save_trip(ws, msg_data, session)

            elif msg_type == "list_trips":
                await _handle_list_trips(ws, session)

            elif msg_type == "load_trip":
                await _handle_load_trip(ws, msg_data, session)

            elif msg_type == "delete_trip":
                await _handle_delete_trip(ws, msg_data, session)

            else:
                await ws.send_json({
                    "type": "error",
                    "data": f"Unknown message type: {msg_type}.",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket session error")
        try:
            await ws.send_json({"type": "error", "data": str(e)})
            await ws.close()
        except Exception:
            pass
    finally:
        # Always release the concurrency slot, however the loop exited
        # (disconnect, idle timeout, handler error). (BS-05)
        async with _ws_conn_lock:
            _ws_open_connections = max(_ws_open_connections - 1, 0)


async def _handle_plan(ws: WebSocket, data: dict, session: dict) -> None:
    """Run Lane 1 full pipeline. Clears history (fresh start).

    Validates the payload in-place (e.g. unsupported currency) and
    sends a type=error without closing the socket, so the user can
    correct the input and try again.
    """
    logger.info("/ws plan: %s", data.get("gp_name", "?") if isinstance(data, dict) else "?")

    # Debug opt-in: once set on a plan call, it stays on for subsequent
    # chats in the same session. Plan-envelope flag is preferred over a
    # ws query string because it lets clients toggle per-request later.
    if isinstance(data, dict) and (data.get("debug") is True or data.get("_debug") is True):
        session["debug"] = True

    try:
        req = _validate_plan_payload(data)
    except ValueError as e:
        await ws.send_json({"type": "error", "data": f"Invalid plan input: {e}"})
        return  # socket stays open for retry

    # Per-identity daily LLM-call ceiling (BS-15). A full plan fans out to the
    # itinerary/tour LLM agents; charge one unit and refuse past the ceiling so
    # a single identity cannot run up unbounded provider cost.
    try:
        check_llm_quota(_session_user_id(session))
    except LLMDailyLimitError as e:
        await ws.send_json({"type": "error", "data": str(e)})
        return

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Starting your trip plan..."},
    })

    before = session.get("plan_state") or {}
    try:
        result = await _run_plan_with_limit(req.model_dump())
    except ServerBusyError as e:
        await ws.send_json({"type": "error", "data": str(e)})
        return

    for msg in result.get("messages", []):
        await ws.send_json({"type": "message", "data": msg})

    # Replace plan state entirely + clear conversation history
    session["plan_state"] = result
    clear_history(session)

    await ws.send_json({"type": "result", "data": _state_snapshot(result)})

    # Minimal trace (Step 1): state_apply + budget_final. Lane 1 doesn't
    # expose per-tool failures so tool_fail stays empty here.
    trace = _build_trace_events(before, result, failed_tools=[])
    await _send_trace(ws, trace, session.get("debug", False))

    await ws.send_json({"type": "done"})


async def _handle_chat(ws: WebSocket, data, session: dict) -> None:
    """Run Lane 2 supervisor with conversation history.

    Copy-on-write discipline: `refine_plan` mutates the state dict
    it receives (the state-aware tool factory + `_apply_tool_updates`
    write directly onto it). If any step raises mid-mutation, the
    session must not be left with a half-updated plan. We deep-copy
    the session plan_state once up front, hand the copy to refine_plan,
    and only swap it back into the session on success.
    """
    user_message = data if isinstance(data, str) else str(data)
    logger.info("/ws chat: %s", user_message[:100])

    # Per-identity daily LLM-call ceiling (BS-15). A refine turn drives the
    # supervisor (and its fan-out tools), so charge one unit and refuse past
    # the ceiling — same guard the /plan path uses — so a single identity
    # cannot run up unbounded provider cost via repeated chat refinements.
    try:
        check_llm_quota(_session_user_id(session))
    except LLMDailyLimitError as e:
        await ws.send_json({"type": "error", "data": str(e)})
        return

    await ws.send_json({
        "type": "message",
        "data": {"agent": "concierge", "text": "Processing your request..."},
    })

    original = session.get("plan_state") or {}
    history = get_history(session)

    # Snapshot pre-mutation field lists for the trace diff. Cheap and
    # taken from the original (not the working copy) so it survives
    # regardless of what happens inside refine_plan.
    before_snapshot = {
        f: list(original.get(f) or [])
        for f in ("tickets", "transport", "hotel", "itinerary", "tour")
    }

    working = copy.deepcopy(original)
    try:
        updated_state, reply, trace_ctx = await asyncio.to_thread(
            refine_plan, working, user_message, history,
        )
    except ValueError as e:
        # Known, user-actionable: surface plainly, keep session intact
        await ws.send_json({"type": "error", "data": f"Refine failed: {e}"})
        return
    except RefineDeadlineError:
        # Provider/tool stalled past the hard deadline (backend-completeness-2).
        # The working copy is discarded, so the session plan is unchanged.
        logger.warning("_handle_chat refine deadline exceeded")
        await ws.send_json({
            "type": "error",
            "data": "That request timed out. Your plan is unchanged — please try again.",
        })
        return
    except Exception:
        logger.exception("_handle_chat unexpected error")
        await ws.send_json({
            "type": "error",
            "data": "Internal chat error. Your plan is unchanged — please try again.",
        })
        return

    # Only reached on success — commit to session
    session["plan_state"] = updated_state
    append_turn(session, user_message, reply)

    await ws.send_json({"type": "reply", "data": reply})
    await ws.send_json({"type": "result", "data": _state_snapshot(updated_state)})

    # updated_fields from refine trace_ctx is authoritative (tool
    # actually wrote), which also covers the "3 hotels → 3 different
    # hotels" case that pure count diff would miss.
    trace = _build_trace_events(
        before_snapshot,
        updated_state,
        failed_tools=trace_ctx.get("failed_tools") or [],
        updated_fields=trace_ctx.get("updated_fields") or [],
    )
    await _send_trace(ws, trace, session.get("debug", False))

    await ws.send_json({"type": "done"})


async def _handle_quote(ws: WebSocket, data, session: dict) -> None:
    """Recompute budget against frontend selections without mutating state."""
    if not isinstance(data, dict):
        await ws.send_json({"type": "error", "data": "quote payload must be a JSON object"})
        return

    state = session.get("plan_state") or {}
    if not state:
        await ws.send_json({"type": "error", "data": "No active plan to quote. Run planning first."})
        return

    if "selections" in data and data["selections"] is None:
        await ws.send_json({"type": "error", "data": "Invalid quote selection: selections must be an object"})
        return

    selections = data["selections"] if "selections" in data else {}
    quote_id = data.get("quote_id")
    try:
        summary = recompute_budget(state, selections=selections)
    except ValueError as e:
        await ws.send_json({"type": "error", "data": f"Invalid quote selection: {e}"})
        return
    except Exception:
        logger.exception("quote recomputation failed")
        await ws.send_json({
            "type": "error",
            "data": "Quote recomputation failed. Your plan is unchanged.",
        })
        return

    await ws.send_json({
        "type": "quote",
        "data": {"quote_id": quote_id, "budget_summary": summary},
    })

    # Emit a budget_final trace so the debug surface reflects what the
    # user just selected. Without this, only the baseline plan budget
    # shows up in traces, and amber/incomplete quotes from selections
    # have no observable signal beyond the rendered panel.
    await _send_trace(
        ws,
        [{
            "event": "budget_final",
            "total": summary.get("total"),
            "budget": summary.get("budget"),
            "currency": summary.get("currency"),
            "within_budget": summary.get("within_budget"),
            "quote_complete": summary.get("quote_complete", True),
            "missing_price_categories": summary.get("missing_price_categories") or [],
        }],
        session.get("debug", False),
    )


# ── Saved-trip handlers ─────────────────────────────────────────────


from datetime import date as _date
import uuid as _uuid

from db import SessionLocal as _SessionLocal
import repository as _repo


def _parse_date(value) -> _date | None:
    if not value:
        return None
    try:
        return _date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _session_user_id(session: dict) -> str:
    return session.get("user_id") or "demo-user"


def _persistence_blocked(user_id: str) -> bool:
    """On a real (non-local) deploy the shared "demo-user" sentinel must not
    own persisted trips — otherwise every demo visitor collapses into one
    account and can read/delete each other's trips. Local/test dev legitimately
    runs as demo-user (single developer), so persistence stays open there.
    """
    return user_id == "demo-user" and not _IS_LOCAL_ENV


# Each persistence op is a synchronous unit of work. We run it via
# asyncio.to_thread so a slow/contended DB round-trip does not block the single
# uvicorn event loop (and with it every other WebSocket session + HTTP probe).
# JSON-serializable payloads are built inside the session, before offload returns.


def _save_trip_sync(user_id: str, data: dict, plan_snapshot: dict) -> dict:
    with _SessionLocal() as db:
        user = _repo.upsert_user(
            db,
            clerk_user_id=user_id,
            email=data.get("email"),
            display_name=data.get("display_name"),
        )
        trip = _repo.save_trip(
            db,
            user_id=user.id,
            gp_slug=str(data.get("gp_slug") or "unknown-gp"),
            depart_date=_parse_date(data.get("depart_date")),
            return_date=_parse_date(data.get("return_date")),
            plan_snapshot=plan_snapshot,
            budget_summary=data.get("budget_summary"),
            active_constraints=data.get("active_constraints"),
        )
        return {"id": str(trip.id), "gp_slug": trip.gp_slug}


def _list_trips_sync(user_id: str) -> list[dict]:
    with _SessionLocal() as db:
        user = _repo.upsert_user(db, clerk_user_id=user_id, email=None, display_name=None)
        rows = _repo.list_trips(db, user_id=user.id)
        return [
            {
                "id": str(r.id),
                "gp_slug": r.gp_slug,
                "depart_date": r.depart_date.isoformat() if r.depart_date else None,
                "return_date": r.return_date.isoformat() if r.return_date else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "budget_total": (r.budget_summary or {}).get("total"),
                "currency": (r.budget_summary or {}).get("currency"),
            }
            for r in rows
        ]


def _load_trip_sync(user_id: str, trip_uuid: "_uuid.UUID") -> dict | None:
    with _SessionLocal() as db:
        user = _repo.upsert_user(db, clerk_user_id=user_id, email=None, display_name=None)
        trip = _repo.get_trip(db, trip_id=trip_uuid, user_id=user.id)
        if trip is None:
            return None
        return {
            "id": str(trip.id),
            "gp_slug": trip.gp_slug,
            "depart_date": trip.depart_date.isoformat() if trip.depart_date else None,
            "return_date": trip.return_date.isoformat() if trip.return_date else None,
            "plan_snapshot": trip.plan_snapshot,
            "budget_summary": trip.budget_summary,
            "active_constraints": trip.active_constraints,
        }


def _delete_trip_sync(user_id: str, trip_uuid: "_uuid.UUID") -> bool:
    with _SessionLocal() as db:
        user = _repo.upsert_user(db, clerk_user_id=user_id, email=None, display_name=None)
        return _repo.delete_trip(db, trip_id=trip_uuid, user_id=user.id)


async def _handle_save_trip(ws: WebSocket, data: dict, session: dict) -> None:
    user_id = _session_user_id(session)
    if _persistence_blocked(user_id):
        await ws.send_json({"type": "error", "data": "Sign in to save trips."})
        return
    plan_snapshot = data.get("plan_snapshot")
    if not isinstance(plan_snapshot, dict):
        plan_snapshot = session.get("plan_state") or {}
    if not plan_snapshot:
        await ws.send_json({
            "type": "error",
            "data": "nothing to save: plan has not run yet",
        })
        return
    try:
        ack = await asyncio.to_thread(_save_trip_sync, user_id, data, plan_snapshot)
    except _repo.SavedTripQuotaError as e:
        # Per-user storage quota reached (BS-02). User-actionable, not a 500.
        await ws.send_json({"type": "error", "data": str(e)})
        return
    except Exception as e:
        logger.exception("save_trip failed")
        await ws.send_json({"type": "error", "data": f"save failed: {e}"})
        return
    await ws.send_json({"type": "save_trip_ack", "data": ack})


async def _handle_list_trips(ws: WebSocket, session: dict) -> None:
    user_id = _session_user_id(session)
    if _persistence_blocked(user_id):
        await ws.send_json({"type": "error", "data": "Sign in to view saved trips."})
        return
    try:
        trips = await asyncio.to_thread(_list_trips_sync, user_id)
    except Exception as e:
        logger.exception("list_trips failed")
        await ws.send_json({"type": "error", "data": f"list failed: {e}"})
        return
    await ws.send_json({"type": "trips_list", "data": {"trips": trips}})


async def _handle_load_trip(ws: WebSocket, data: dict, session: dict) -> None:
    user_id = _session_user_id(session)
    if _persistence_blocked(user_id):
        await ws.send_json({"type": "error", "data": "Sign in to view saved trips."})
        return
    raw = data.get("id") or ""
    try:
        trip_uuid = _uuid.UUID(str(raw))
    except (TypeError, ValueError):
        await ws.send_json({"type": "error", "data": "invalid trip id"})
        return
    try:
        payload = await asyncio.to_thread(_load_trip_sync, user_id, trip_uuid)
    except Exception as e:
        logger.exception("load_trip failed")
        await ws.send_json({"type": "error", "data": f"load failed: {e}"})
        return
    if payload is None:
        await ws.send_json({"type": "error", "data": "trip not found"})
        return
    session["plan_state"] = payload.get("plan_snapshot") or {}
    await ws.send_json({"type": "trip_loaded", "data": payload})


async def _handle_delete_trip(ws: WebSocket, data: dict, session: dict) -> None:
    user_id = _session_user_id(session)
    if _persistence_blocked(user_id):
        await ws.send_json({"type": "error", "data": "Sign in to manage saved trips."})
        return
    raw = data.get("id") or ""
    try:
        trip_uuid = _uuid.UUID(str(raw))
    except (TypeError, ValueError):
        await ws.send_json({"type": "error", "data": "invalid trip id"})
        return
    try:
        ok = await asyncio.to_thread(_delete_trip_sync, user_id, trip_uuid)
    except Exception as e:
        logger.exception("delete_trip failed")
        await ws.send_json({"type": "error", "data": f"delete failed: {e}"})
        return
    await ws.send_json({"type": "delete_trip_ack", "data": {"ok": ok}})


if __name__ == "__main__":
    # Lifespan handler will call setup_logging() when the app starts.
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
