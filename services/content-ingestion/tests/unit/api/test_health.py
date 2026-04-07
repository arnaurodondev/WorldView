"""Unit tests for health, readiness, and metrics endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_app():
    from content_ingestion.app import create_app

    app = create_app()
    app.state.settings = MagicMock(
        admin_token="test",
        minio_bucket="test-bucket",
    )
    mock_factory = AsyncMock()
    app.state.write_factory = mock_factory
    app.state.read_factory = mock_factory
    app.state.valkey = AsyncMock()
    app.state.storage = AsyncMock()
    return app


@pytest.fixture
async def client(mock_app):
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    async def test_healthz_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_readyz_returns_200_when_all_healthy(self, client: AsyncClient, mock_app) -> None:
        from contextlib import asynccontextmanager

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        @asynccontextmanager
        async def _fake_session():
            yield mock_session

        mock_app.state.write_factory = _fake_session
        mock_app.state.valkey.ping = AsyncMock()
        mock_app.state.storage.exists = AsyncMock(return_value=False)

        resp = await client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        assert data["valkey"] == "ok"
        assert data["minio"] == "ok"

    async def test_readyz_returns_503_when_db_down(self, client: AsyncClient, mock_app) -> None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _failing_session():
            raise RuntimeError("DB down")
            yield  # unreachable but required by asynccontextmanager

        mock_app.state.write_factory = _failing_session
        mock_app.state.valkey.ping = AsyncMock()
        mock_app.state.storage.exists = AsyncMock()

        resp = await client.get("/readyz")
        assert resp.status_code == 503

    async def test_metrics_endpoint_returns_prometheus_data(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/plain" in ct or "openmetrics" in ct
