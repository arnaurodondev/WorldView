"""Unit tests for InternalJWTMiddleware on alert service (T-D-1-08)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from alert.infrastructure.websocket.manager import ConnectionManager
from fastapi import FastAPI, Request
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
async def test_middleware_returns_503_when_no_public_key() -> None:
    """F-001: With default skip_verification=False and no public key loaded,
    middleware returns 503 (fail-closed) instead of accepting unverified JWTs.
    """
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": "any.jwt.here"})
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.text


@pytest.mark.asyncio
async def test_middleware_rejects_invalid_jwt_with_skip_verification() -> None:
    """Invalid (malformed) X-Internal-JWT → 401 (via get_current_user_id dependency)
    when skip_verification=True and public key is not loaded.

    When the token is malformed, InternalJWTMiddleware sets empty user_id in
    request.state. The get_current_user_id dependency then raises 401.
    """
    app = _make_app(internal_jwt_skip_verification=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": "bad.jwt"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_skip_verification_flag_allows_bypass() -> None:
    """F-001: When skip_verification=True and no public key, middleware decodes
    JWT without signature verification and passes through to route handler.

    Uses a minimal FastAPI app (not create_app) to isolate middleware behavior
    from route-level dependencies like DB sessions.
    """
    import jwt as pyjwt

    # Minimal app with a simple test route — no DB dependencies.
    # Request + Any imported at module level so __future__ annotations can resolve them.
    test_app = FastAPI()

    @test_app.get("/api/v1/test")
    async def _test_route(request: Request) -> dict[str, Any]:
        return {
            "user_id": getattr(request.state, "user_id", ""),
            "tenant_id": getattr(request.state, "tenant_id", ""),
            "role": getattr(request.state, "role", ""),
        }

    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://localhost:9999/internal/jwks",
        skip_verification=True,
    )

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "t-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "secret",
        algorithm="HS256",
    )
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test", headers={"X-Internal-JWT": token})
    # Middleware passed — route handler returns claims from request.state
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-1"
    assert body["tenant_id"] == "t-1"
    assert body["role"] == "owner"
