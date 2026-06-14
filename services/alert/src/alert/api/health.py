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

    # 2. Kafka — list cluster metadata via a *fresh, short-lived* AdminClient.
    #
    # BP-350 history: we previously reused a single long-lived confluent_kafka
    # Producer (app.state.kafka_health_producer) for this check and kept bumping
    # its handshake/socket timeouts (2s→5s→8s→30s). That never fixed the real
    # failure mode: once librdkafka's background thread on that one handle wedges
    # into a `_TRANSPORT` (Broker transport failure) backoff state, the handle
    # never self-heals, so `list_topics()` returns the same transport error
    # forever even though the broker is perfectly healthy. The service then sat
    # UNHEALTHY for ~45h while a brand-new producer in the same container could
    # list topics in ~0.1s.
    #
    # Fix: create a throwaway AdminClient per check. It is cheap (~0.1s), gets a
    # fresh broker connection every time, and therefore self-heals the instant
    # the broker is reachable. The 3s timeout stays well inside the Docker
    # healthcheck window so a slow probe can still report "degraded" instead of
    # blowing the healthcheck's own timeout.
    try:
        bootstrap = request.app.state.kafka_bootstrap_servers

        def _list_topics() -> object:
            from confluent_kafka.admin import AdminClient  # type: ignore[import-untyped]

            client = AdminClient({"bootstrap.servers": bootstrap})
            return client.list_topics(timeout=3)

        await asyncio.get_running_loop().run_in_executor(None, _list_topics)
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

    # 4. S1 internal health (best-effort — S10 degrades gracefully when S1 is unavailable)
    # PRD §12.1: S1 is not a hard dependency; watchlist lookups degrade to empty results.
    # Do NOT set ok=False here — alert-test compose profile has no portfolio container.
    try:
        s1_healthy = await request.app.state.s1_client.health_check()
        checks["s1"] = "ok" if s1_healthy else "degraded"
    except Exception:
        _log.warning("readyz_s1_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["s1"] = "degraded"

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
