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
    )


def install_observability(app: FastAPI) -> None:
    init_sentry_if_configured()
    configure_logging()
    app.add_middleware(RequestIdMiddleware)
