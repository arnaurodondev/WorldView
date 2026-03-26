"""Unit tests for admin API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

# We test the API at the HTTP level using a test client with mocked dependencies.

ADMIN_TOKEN = "test-admin-token"  # noqa: S105


@pytest.fixture
def mock_app():
    """Create a FastAPI app with mocked state for testing."""
    from content_ingestion.app import create_app

    app = create_app()

    # Mock lifespan dependencies on app.state
    app.state.settings = MagicMock(admin_token=ADMIN_TOKEN)
    app.state.session_factory = AsyncMock()
    app.state.valkey = AsyncMock()
    app.state.storage = AsyncMock()
    app.state.trigger_fn = AsyncMock()

    return app


@pytest.fixture
async def client(mock_app):
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestAdminAuth:
    async def test_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 401

    async def test_valid_token_passes_auth(self, client: AsyncClient, mock_app) -> None:
        from contextlib import asynccontextmanager

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def _fake_session():
            yield mock_session

        mock_app.state.session_factory = _fake_session

        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200


class TestDLQAuth:
    async def test_dlq_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/dlq")
        assert resp.status_code == 401


class TestInternalAuth:
    async def test_internal_health_no_auth_required(self, client: AsyncClient) -> None:
        resp = await client.get("/internal/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    async def test_internal_submit_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/internal/v1/ingest/submit",
            json={"source_type": "manual", "raw_content": "test"},
        )
        assert resp.status_code == 401
