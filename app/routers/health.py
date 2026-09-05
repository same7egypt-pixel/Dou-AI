"""Enterprise health check, readiness, and metrics endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import APP_ENV
from ..database import get_db
from ..services.observability import COMMIT, SENTRY_DSN

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness():
    """Liveness probe — is the process up?"""
    return {
        "status": "ok",
        "service": "dou-fleet-os",
        "version": "2.0.0",
        "environment": APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": COMMIT,
        "error_reporting": "on" if SENTRY_DSN else "off",
    }


@router.get("/ready")
async def readiness(db: Session = Depends(get_db)):
    """Readiness probe — verifies database and caching connectivity."""
    db.execute(text("SELECT 1"))
    checks: Dict[str, Any] = {"database": {"status": "ok"}}

    # Redis check (optional)
    try:
        from ..services.cache import get_redis
        r = get_redis()
        if r:
            r.ping()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "not_configured"}
    except Exception as e:
        checks["redis"] = {"status": "error", "message": str(e)}

    return {
        "status": "ok",
        "service": "dou-api",
        "database": "ok",
        "environment": APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


@router.get("/metrics")
async def metrics():
    """Metrics overview."""
    return {
        "status": "ok",
        "service": "dou-fleet-os",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
