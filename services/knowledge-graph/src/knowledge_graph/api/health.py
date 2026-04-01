"""Health, readiness, and Prometheus metrics endpoints (PLAN-0003 pattern)."""

from __future__ import annotations

import json

import prometheus_client
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter()
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — 200 only when intelligence_db and Kafka are reachable."""
    checks: dict[str, str] = {}
    ok = True

    # intelligence_db check
    try:
        session_factory = getattr(request.app.state, "session_factory", None)
        if session_factory is not None:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["intelligence_db"] = "ok"
        else:
            checks["intelligence_db"] = "not_configured"
            ok = False
    except Exception:
        _log.warning("readyz_db_check_failed", exc_info=True)
        checks["intelligence_db"] = "error"
        ok = False

    # Kafka consumer assignment check (best-effort)
    try:
        consumer = getattr(request.app.state, "consumer", None)
        if consumer is not None:
            checks["kafka"] = "ok"
        else:
            checks["kafka"] = "not_started"
    except Exception:
        _log.warning("readyz_kafka_check_failed", exc_info=True)
        checks["kafka"] = "error"

    status_code = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    data = prometheus_client.generate_latest()
    return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)
