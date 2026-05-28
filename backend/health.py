"""Health and readiness endpoints for platform probes.

  /healthz — liveness. Always 200 if the process can respond.
  /readyz  — readiness. 200 only when the DB ping succeeds.

Neither route requires auth. They are used by Railway / load-balancer
probes which cannot supply credentials.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import SessionLocal


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"db": "ok"}
    except Exception as e:  # pragma: no cover (exercised when DB unreachable)
        logger.warning("readyz DB ping failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"db": "down", "error": str(e)[:200]},
        )
