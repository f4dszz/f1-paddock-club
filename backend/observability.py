"""Sentry init + structured JSON logging + per-request request_id binding."""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

# python-json-logger 4.x renamed import path; 2.x kept jsonlogger.
try:  # pragma: no cover (env-dependent)
    from pythonjsonlogger.json import JsonFormatter as _JsonFormatter
except Exception:  # pragma: no cover
    try:
        from pythonjsonlogger.jsonlogger import JsonFormatter as _JsonFormatter
    except Exception:
        _JsonFormatter = None

try:  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
except Exception:  # pragma: no cover
    sentry_sdk = None
    FastApiIntegration = None
    StarletteIntegration = None


def configure_logging() -> None:
    """Apply a JSON formatter to existing STDOUT handlers, no-op if unavailable."""
    if _JsonFormatter is None:
        return
    fmt = _JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    for h in root.handlers:
        # Only re-format stream handlers; file handler keeps human-readable
        # format because setup_logging() already configured it for local logs.
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) and getattr(h.stream, "name", "") in ("<stderr>", "<stdout>"):
            h.setFormatter(fmt)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach an `x-request-id` to every response; reuse client-supplied id when present."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


# Query-string credentials that must never reach an error tracker (security-6).
# The WS handshake carries the Clerk JWT / demo token as ?token= / ?demo_token=
# (a deeper fix — moving it to a subprotocol — is tracked separately/frontend).
# As a targeted mitigation we scrub those params from any URL Sentry captures.
_SENSITIVE_QUERY_KEYS = ("token", "demo_token", "access_token")


def _scrub_url_query(url: str) -> str:
    """Replace the value of any sensitive query param in `url` with [Filtered]."""
    if not url or "?" not in url:
        return url
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

        parts = urlsplit(url)
        pairs = [
            (k, "[Filtered]" if k.lower() in _SENSITIVE_QUERY_KEYS else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(parts._replace(query=urlencode(pairs)))
    except Exception:  # pragma: no cover - never let scrubbing break send
        return url


def _scrub_event(event, _hint):
    """Sentry before_send hook: strip token/demo_token from any captured URL.

    Walks the few well-known places Sentry stores a request URL (request.url,
    request.query_string, and breadcrumb data urls) so a leaked WS handshake
    URL cannot expose live credentials in the error tracker (security-6).
    """
    try:
        req = event.get("request") if isinstance(event, dict) else None
        if isinstance(req, dict):
            if isinstance(req.get("url"), str):
                req["url"] = _scrub_url_query(req["url"])
            qs = req.get("query_string")
            if isinstance(qs, str) and qs:
                # query_string has no scheme/host; scrub via a synthetic URL.
                req["query_string"] = _scrub_url_query("http://x/?" + qs).split("?", 1)[-1]
        for crumb in (event.get("breadcrumbs", {}) or {}).get("values", []) if isinstance(event, dict) else []:
            data = crumb.get("data") if isinstance(crumb, dict) else None
            if isinstance(data, dict) and isinstance(data.get("url"), str):
                data["url"] = _scrub_url_query(data["url"])
    except Exception:  # pragma: no cover - scrubbing must never drop the event
        pass
    return event


def init_sentry_if_configured() -> None:
    dsn = (os.environ.get("SENTRY_DSN_BACKEND") or "").strip()
    if not dsn or sentry_sdk is None:
        return
    sample_rate_raw = os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
    try:
        sample_rate = float(sample_rate_raw)
    except (TypeError, ValueError):
        sample_rate = 0.1
    integrations = []
    if FastApiIntegration:
        integrations.append(FastApiIntegration())
    if StarletteIntegration:
        integrations.append(StarletteIntegration())
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("APP_ENV", "local"),
        traces_sample_rate=sample_rate,
        integrations=integrations,
        # Strip credentials passed in the WS query string before any event
        # leaves the process (security-6). Deeper fix tracked separately.
        before_send=_scrub_event,
        send_default_pii=False,
    )


def install_observability(app: FastAPI) -> None:
    init_sentry_if_configured()
    configure_logging()
    app.add_middleware(RequestIdMiddleware)
