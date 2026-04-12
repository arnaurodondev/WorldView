"""Unit tests for InternalJWTMiddleware on alert service (T-D-1-08)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.websocket.manager import ConnectionManager
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_app(**settings_kwargs: object) -> object:
    """Create a wired app with mock session factory for unit tests."""
    base: dict[str, object] = {
        "kafka_bootstrap_servers": "localhost:9092",
        "kafka_schema_registry_url": "http://localhost:8081",
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test",
        "s8_internal_token": "test-s8",
        "s1_internal_token": "test-s1",
    }
    base.update(settings_kwargs)
    settings = Settings(**base)  # type: ignore[arg-type]
    app = create_app(settings)

    # Wire minimal state so routes don't crash on missing DB state
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory
    app.state.read_factory = mock_factory
    app.state.ws_manager = ConnectionManager()
    return app


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT (skipped by middleware prefix match)."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    # /healthz is a liveness probe — returns 200 without any infra state
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_middleware_rejects_invalid_jwt() -> None:
    """Invalid (malformed) X-Internal-JWT → 401.

    When the token is malformed, InternalJWTMiddleware sets empty user_id in
    request.state. The get_current_user_id dependency then raises 401.
    """
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": "bad.jwt"})
    assert resp.status_code == 401
