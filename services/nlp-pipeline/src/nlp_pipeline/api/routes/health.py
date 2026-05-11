"""Health, readiness, and Prometheus metrics endpoints (STANDARDS.md §5)."""

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
    """Liveness probe — returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — checks nlp_db, intelligence_db, Kafka, Ollama (503 on failure)."""
    checks: dict[str, str] = {}
    ok = True

    # F-003B: JWKS public key must be loaded before accepting traffic.
    if getattr(request.app.state, "_internal_jwt_public_key", None) is None:
        checks["jwks"] = "not_loaded"
        ok = False
    else:
        checks["jwks"] = "ok"

    # nlp_db
    try:
        async with request.app.state.nlp_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["nlp_db"] = "ok"
    except Exception:
        _log.warning("readyz_nlp_db_failed", exc_info=True)
        checks["nlp_db"] = "error"
        ok = False

    # intelligence_db
    try:
        async with request.app.state.intelligence_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["intelligence_db"] = "ok"
    except Exception:
        _log.warning("readyz_intelligence_db_failed", exc_info=True)
        checks["intelligence_db"] = "error"
        ok = False

    # Valkey
    try:
        valkey = getattr(request.app.state, "valkey", None)
        if valkey is not None:
            await valkey.ping()
        checks["valkey"] = "ok"
    except Exception:
        _log.warning("readyz_valkey_failed", exc_info=True)
        checks["valkey"] = "error"
        ok = False

    # Dispatcher health
    dispatcher_healthy = getattr(request.app.state, "dispatcher_healthy", True)
    if not dispatcher_healthy:
        checks["dispatcher"] = "degraded"

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
