"""Health, readiness, and Prometheus metrics endpoints for S10.

Dependencies checked in /readyz (4 deps per plan spec):
  1. alert_db   — SQLAlchemy SELECT 1
  2. Kafka       — producer metadata (bootstrap connection)
  3. Valkey      — PING
  4. S1 /health  — HTTP GET via S1Client
"""

from __future__ import annotations

import asyncio
import json

import prometheus_client
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(tags=["health"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get("/healthz")
async def healthz() -> dict:  # type: ignore[type-arg]
    """Liveness probe — 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — 503 if any of the 4 dependencies is unhealthy."""
    checks: dict[str, str] = {}
    ok = True

    # 1. alert_db
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["alert_db"] = "ok"
    except Exception:
        _log.warning("readyz_alert_db_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["alert_db"] = "error"
        ok = False

    # 2. Kafka (check producer metadata — lightweight)
    try:
        producer = request.app.state.kafka_health_producer
        # list_topics — initial connection establishment can take 3-4s on cold start;
        # 5s gives enough headroom without blocking health checks too long (BP-350)
        await asyncio.get_running_loop().run_in_executor(None, lambda: producer.list_topics(timeout=8))
        checks["kafka"] = "ok"
    except Exception:
        _log.warning("readyz_kafka_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["kafka"] = "error"
        ok = False

    # 3. Valkey
    try:
        await request.app.state.valkey.ping()
        checks["valkey"] = "ok"
    except Exception:
        _log.warning("readyz_valkey_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["valkey"] = "error"
        ok = False

    # 4. S1 internal health
    try:
        s1_healthy = await request.app.state.s1_client.health_check()
        checks["s1"] = "ok" if s1_healthy else "error"
        if not s1_healthy:
            ok = False
    except Exception:
        _log.warning("readyz_s1_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["s1"] = "error"
        ok = False

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
