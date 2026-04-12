"""Unit tests for InternalJWTMiddleware on content-store (T-D-1-04)."""

from __future__ import annotations

import pytest
from content_store.app import create_app
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/documents/batch", json={"doc_ids": []})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT (skip-list path)."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code in (200, 503)


@pytest.mark.asyncio
async def test_middleware_passes_through_with_invalid_jwt_no_public_key() -> None:
    """Malformed X-Internal-JWT when public key is not yet loaded → request passes through.

    PRD-0025 graceful-degradation: when JWKS is unavailable at startup (public_key is None),
    the middleware catches jwt.DecodeError, sets empty state (tenant_id/user_id/role = ""),
    and calls call_next — it does NOT return 401. Full signature verification (and 401 on
    invalid tokens) only occurs when public_key is set (after middleware.startup() succeeds).
    """
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.add_middleware(InternalJWTMiddleware, jwks_url="http://api-gateway:8000/internal/jwks")

    @test_app.get("/test")
    async def test_endpoint() -> dict[str, str]:
        return {"ok": "true"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/test", headers={"X-Internal-JWT": "bad.token.here"})
    # Graceful degradation: passes through with empty state rather than 401
    assert resp.status_code == 200
