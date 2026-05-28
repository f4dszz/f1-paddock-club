"""Clerk JWT verification + dual-mode auth helpers.

Production mode (APP_ENV=production OR REQUIRE_CLERK_AUTH=true):
  - Only a Clerk JWT is accepted. Missing/invalid token → 401 (HTTP)
    or close 1008 (WS).

Dev/test mode (APP_ENV in {local, dev, test, ""}, REQUIRE_CLERK_AUTH unset):
  - Accept either a valid Clerk JWT or DEMO_ACCESS_TOKEN.
  - When only the demo token is presented, user_id falls back to "demo-user".
  - When neither Clerk nor demo token is configured, all requests are
    treated as the "demo-user" (pure local dev, no gate).

The frontend always tries Clerk first when VITE_CLERK_PUBLISHABLE_KEY is
set; it falls back to VITE_DEMO_TOKEN otherwise. The backend mirrors that.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException, WebSocket


_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict[str, tuple[float, dict]] = {}
_jwks_lock = threading.Lock()


class AuthError(Exception):
    """Raised by verify_clerk_jwt and require_user_for_ws."""


# ── Env readers ─────────────────────────────────────────────────────


def _app_env() -> str:
    return (os.environ.get("APP_ENV") or os.environ.get("ENV") or "local").strip().lower()


def _is_prod_env() -> bool:
    return _app_env() in {"production", "prod"}


def _require_clerk() -> bool:
    if _is_prod_env():
        return True
    raw = (os.environ.get("REQUIRE_CLERK_AUTH") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _clerk_issuer() -> str:
    return (os.environ.get("CLERK_JWT_ISSUER") or "").rstrip("/")


def _clerk_jwks_url() -> str:
    url = (os.environ.get("CLERK_JWKS_URL") or "").strip()
    if url:
        return url
    iss = _clerk_issuer()
    return f"{iss}/.well-known/jwks.json" if iss else ""


def _demo_token() -> str:
    return (os.environ.get("DEMO_ACCESS_TOKEN") or "").strip()


# ── JWKS fetch + cache ──────────────────────────────────────────────


def _fetch_jwks(url: str) -> dict:  # pragma: no cover (mocked in tests)
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def _jwks(url: str) -> dict:
    now = time.time()
    with _jwks_lock:
        cached = _jwks_cache.get(url)
        if cached and now - cached[0] < _JWKS_TTL_SECONDS:
            return cached[1]
    data = _fetch_jwks(url)
    with _jwks_lock:
        _jwks_cache[url] = (now, data)
    return data


def _public_key_for_kid(jwks: dict, kid: str):
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return jwt.PyJWK(key).key
    raise AuthError(f"unknown kid: {kid}")


# ── Public verification API ─────────────────────────────────────────


def verify_clerk_jwt(token: str, *, issuer: str | None = None) -> dict[str, Any]:
    """Verify a Clerk JWT. Raises AuthError on any failure.

    Cached JWKS is reused for up to _JWKS_TTL_SECONDS. If the kid is unknown
    in the cached JWKS (i.e. Clerk rotated keys), the cache is cleared once
    and re-fetched to give the rotation a chance.
    """
    iss = (issuer or _clerk_issuer()).rstrip("/")
    if not iss:
        raise AuthError("clerk issuer not configured")

    jwks_url = _clerk_jwks_url() or f"{iss}/.well-known/jwks.json"
    if not jwks_url:
        raise AuthError("clerk jwks url not configured")

    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise AuthError(f"malformed token: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise AuthError("missing kid")

    try:
        key = _public_key_for_kid(_jwks(jwks_url), kid)
    except AuthError:
        # JWKS may have rotated; clear cache and try once more.
        with _jwks_lock:
            _jwks_cache.pop(jwks_url, None)
        key = _public_key_for_kid(_jwks(jwks_url), kid)

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            issuer=iss,
            options={"require": ["exp", "iss", "sub"]},
        )
        return claims
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid token: {e}") from e


# ── HTTP dependency ─────────────────────────────────────────────────


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        return token or None
    return None


def require_user(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: returns user_id or raises HTTPException(401).

    Implements the dual-mode rules in the module docstring.
    """
    token = _extract_bearer(authorization)
    demo = _demo_token()

    if _is_prod_env() or _require_clerk():
        # Strict mode: only Clerk
        if not _clerk_issuer():
            raise HTTPException(
                status_code=503,
                detail="auth not configured: CLERK_JWT_ISSUER required in production",
            )
        if not token:
            raise HTTPException(status_code=401, detail="missing token")
        try:
            claims = verify_clerk_jwt(token)
            return str(claims["sub"])
        except AuthError as e:
            raise HTTPException(status_code=401, detail=f"invalid token: {e}") from e

    # Dev/test mode: try Clerk first if configured, then demo, then accept-all
    if token and _clerk_issuer():
        try:
            claims = verify_clerk_jwt(token)
            return str(claims["sub"])
        except AuthError:
            # Fall through to demo check
            pass
    if demo:
        if token == demo:
            return "demo-user"
        # If demo configured but missing or wrong, deny.
        if token is not None:
            raise HTTPException(status_code=401, detail="invalid demo token")
        raise HTTPException(status_code=401, detail="missing token")
    # No auth configured at all — pure local dev passthrough
    return "demo-user"


# ── WebSocket equivalent ────────────────────────────────────────────


def require_user_for_ws(ws: WebSocket) -> str:
    """Return user_id from a WS handshake. Raises AuthError on failure.

    Reads the token from `?token=` (Clerk JWT) or legacy `?demo_token=`.
    """
    token = (
        ws.query_params.get("token")
        or ws.query_params.get("demo_token")
        or ""
    )
    demo = _demo_token()

    if _is_prod_env() or _require_clerk():
        if not _clerk_issuer():
            raise AuthError("auth not configured")
        if not token:
            raise AuthError("missing token")
        try:
            claims = verify_clerk_jwt(token)
            return str(claims["sub"])
        except AuthError:
            raise

    if token and _clerk_issuer():
        try:
            claims = verify_clerk_jwt(token)
            return str(claims["sub"])
        except AuthError:
            pass
    if demo:
        if token == demo:
            return "demo-user"
        if token:
            raise AuthError("invalid demo token")
        raise AuthError("missing token")
    return "demo-user"


def reset_jwks_cache_for_tests() -> None:
    """Test helper: clears the in-process JWKS cache."""
    with _jwks_lock:
        _jwks_cache.clear()
