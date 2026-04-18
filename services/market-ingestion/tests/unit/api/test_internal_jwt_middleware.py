"""Unit tests for InternalJWTMiddleware on market-ingestion (T-D-1-01).

F-001 update: The middleware now defaults to fail-closed (503) when JWKS public key
is unavailable. Tests that need the old pass-through behavior must explicitly enable
skip_verification=True in Settings.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.app import create_app
from market_ingestion.config import Settings

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt():
    """No X-Internal-JWT header → 401."""
    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/providers")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_middleware_skips_health_path():
    """GET /healthz passes without X-Internal-JWT."""
    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code in (200, 503)  # health endpoint, no auth required


@pytest.mark.asyncio
async def test_middleware_returns_503_when_no_public_key():
    """F-001: Invalid X-Internal-JWT with no public key loaded → 503 (fail-closed).

    When JWKS is unavailable (no public key), the middleware now returns 503
    instead of decoding without verification (fail-closed security fix).
    """
    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/providers", headers={"X-Internal-JWT": "not.a.real.jwt"})
    # F-001: fail-closed → 503 when public key is not loaded
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_middleware_passes_through_with_skip_verification():
    """F-001: With skip_verification=True, invalid JWT passes through when no public key loaded.

    This path exists only for E2E tests without the full S9 stack.
    """
    settings = Settings(internal_jwt_skip_verification=True)  # type: ignore[call-arg]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/providers", headers={"X-Internal-JWT": "not.a.real.jwt"})
    # skip_verification=True: DecodeError path → empty state → request passes to route
    # /api/v1/providers does not exist → 404 after middleware pass-through
    assert resp.status_code in (404, 422)
