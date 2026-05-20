"""Unit tests for health, readiness, and DLQ admin endpoints.

Covers:
  - GET /healthz always returns 200
  - GET /readyz returns 200 when all deps ok, 503 on any failure
  - DLQ admin: 401 without token, 200 with valid token
  - Prometheus /metrics endpoint returns text
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alert.api.dependencies import get_dlq_use_case
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.websocket.manager import ConnectionManager
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.unit

# ── Setup helpers ─────────────────────────────────────────────────────────────


def _make_app(*, s1_healthy: bool = True) -> FastAPI:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        admin_token="test-admin",
        service_name="alert-unit-test",
        log_json=False,
        s8_internal_jwt="test-s8-token",
        s1_internal_token="test-s1-token",
    )
    app = create_app(settings)

    # DB session factory
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory
    app.state.ws_manager = ConnectionManager()

    # Kafka health producer (for /readyz Kafka connectivity check)
    mock_producer = MagicMock()
    mock_producer.list_topics = MagicMock(return_value=None)
    app.state.kafka_health_producer = mock_producer

    # Valkey
    mock_valkey = AsyncMock()
    mock_valkey.ping = AsyncMock(return_value=True)
    app.state.valkey = mock_valkey

    # S1 client
    mock_s1 = AsyncMock()
    mock_s1.health_check = AsyncMock(return_value=s1_healthy)
    app.state.s1_client = mock_s1

    return app


# ── /healthz ──────────────────────────────────────────────────────────────────


class TestHealthz:
    @pytest.mark.unit
    async def test_healthz_always_returns_200(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── /readyz ───────────────────────────────────────────────────────────────────


class TestReadyz:
    @pytest.mark.unit
    async def test_readyz_200_when_all_deps_ok(self) -> None:
        app = _make_app(s1_healthy=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    @pytest.mark.unit
    async def test_readyz_200_when_s1_degraded(self) -> None:
        app = _make_app(s1_healthy=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["s1"] == "degraded"

    @pytest.mark.unit
    async def test_readyz_503_when_db_fails(self) -> None:
        app = _make_app()
        # Make session.execute raise
        app.state.session_factory.return_value.__aenter__.return_value.execute = AsyncMock(
            side_effect=Exception("db down")
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["alert_db"] == "error"

    @pytest.mark.unit
    async def test_readyz_503_when_valkey_fails(self) -> None:
        app = _make_app()
        app.state.valkey.ping = AsyncMock(side_effect=Exception("valkey down"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["valkey"] == "error"


# ── /metrics ──────────────────────────────────────────────────────────────────


class TestMetrics:
    @pytest.mark.unit
    async def test_metrics_returns_prometheus_text(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


# ── DLQ admin ─────────────────────────────────────────────────────────────────


class TestDLQAdmin:
    @pytest.mark.unit
    async def test_dlq_list_returns_401_without_token(self) -> None:
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/dlq")
        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_dlq_list_returns_200_with_valid_token(self) -> None:
        app = _make_app()
        mock_uc = AsyncMock()
        mock_uc.list_failed.return_value = []
        app.dependency_overrides[get_dlq_use_case] = lambda: mock_uc
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/admin/dlq", headers={"X-Admin-Token": "test-admin"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    @pytest.mark.unit
    async def test_dlq_resolve_returns_404_on_missing_entry(self) -> None:
        app = _make_app()
        dlq_id = str(uuid4())
        mock_uc = AsyncMock()
        mock_uc.resolve.return_value = False
        app.dependency_overrides[get_dlq_use_case] = lambda: mock_uc
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    f"/admin/dlq/{dlq_id}/resolve",
                    json={"note": "fixed"},
                    headers={"X-Admin-Token": "test-admin"},
                )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 404
