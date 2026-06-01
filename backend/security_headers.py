"""HTTP security headers (CSP, HSTS, etc.) applied via middleware.

HSTS + CSP only apply in production (APP_ENV=production). In dev/test
HSTS would forbid cleartext localhost flows, and CSP would interfere
with Vite's dev-time HMR; both are inappropriate locally. The other
headers (X-Content-Type-Options, Referrer-Policy, Permissions-Policy)
are safe everywhere and always applied.

CSP is intentionally tight — only the Clerk + Sentry endpoints we
actually use, plus the WS/HTTPS topology the frontend talks to.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware


def _is_prod() -> bool:
    return (os.environ.get("APP_ENV") or "").strip().lower() in {"production", "prod"}


# Backend CSP — applies to API responses. The frontend bundle is served
# by Vercel; its CSP is set in vercel.json (S7). They are intentionally
# kept consistent.
CSP_PROD = (
    "default-src 'self'; "
    "connect-src 'self' "
    "https://*.clerk.accounts.dev https://*.clerk.com "
    "https://*.sentry.io https://*.ingest.sentry.io; "
    "img-src 'self' data: https:; "
    "script-src 'self' https://*.clerk.accounts.dev https://*.clerk.com "
    "https://challenges.cloudflare.com; "
    "worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "frame-src 'self' https://*.clerk.accounts.dev https://*.clerk.com "
    "https://challenges.cloudflare.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if _is_prod():
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
            response.headers.setdefault("Content-Security-Policy", CSP_PROD)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response


def install_security_headers(app: FastAPI) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
