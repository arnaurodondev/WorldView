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
async def test_middleware_returns_503_when_no_public_key_fail_closed() -> None:
    """F-001: No JWKS public key + skip_verification=False (default) → 503 fail-closed.

    Without the public key we cannot verify JWT signatures, so accepting
    tokens here would allow any forged JWT to pass through unchecked.
    The middleware now returns 503 by default (fail-closed).
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
    # F-001 fail-closed: no public key → 503
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.text


@pytest.mark.asyncio
async def test_middleware_passes_through_with_skip_verification() -> None:
    """F-001: No JWKS public key + skip_verification=True → unverified decode (test-only path).

    When skip_verification is explicitly enabled (E2E tests without full S9 stack),
    the middleware decodes the JWT without signature verification and populates
    request.state with the claims (or empty strings on decode error).
    """
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://api-gateway:8000/internal/jwks",
        skip_verification=True,
    )

    @test_app.get("/test")
    async def test_endpoint() -> dict[str, str]:
        return {"ok": "true"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/test", headers={"X-Internal-JWT": "bad.token.here"})
    # skip_verification=True: passes through with empty state rather than 503
    assert resp.status_code == 200
