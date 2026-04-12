"""Unit tests for InternalJWTMiddleware on market-data (T-D-1-02)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = pytest.mark.unit


def _make_middleware_app() -> FastAPI:
    """Minimal FastAPI app with InternalJWTMiddleware (no public key — startup not called)."""
    app = FastAPI()
    app.add_middleware(InternalJWTMiddleware, jwks_url="http://api-gateway:8000/internal/jwks")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content="# metrics", media_type="text/plain")

    @app.get("/api/v1/instruments")
    async def instruments() -> dict[str, str]:
        return {"items": "[]"}

    return app


# ── Health / skip paths ───────────────────────────────────────────────────────


def test_middleware_skips_healthz_path() -> None:
    """GET /healthz passes without X-Internal-JWT (skip list)."""
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200


def test_middleware_skips_health_path() -> None:
    """GET /health passes without X-Internal-JWT (skip list)."""
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/health")
    assert resp.status_code == 200


def test_middleware_skips_metrics_path() -> None:
    """GET /metrics passes without X-Internal-JWT (skip prefix)."""
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200


# ── Protected paths ───────────────────────────────────────────────────────────


def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header on a protected path → 401."""
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments")
    assert resp.status_code == 401
    assert "Missing X-Internal-JWT" in resp.json()["detail"]


def test_middleware_passes_through_with_invalid_jwt_no_public_key() -> None:
    """Malformed X-Internal-JWT when public key is not yet loaded → request passes through.

    PRD-0025 graceful-degradation: when JWKS is unavailable at startup (public_key is None),
    the middleware catches jwt.DecodeError, sets empty state (tenant_id/user_id/role = ""),
    and calls call_next — it does NOT return 401. This allows the service to remain partially
    functional even if S9 JWKS is transiently unavailable.

    Full signature verification (and 401 on invalid tokens) only occurs when public_key is set
    (i.e., after middleware.startup() succeeds).
    """
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments", headers={"X-Internal-JWT": "not.a.jwt"})
    # Graceful degradation: passes through with empty state rather than 401
    assert resp.status_code == 200


def test_middleware_passes_valid_unsigned_jwt() -> None:
    """A well-formed JWT (without signature verification) passes through when public key is unset.

    PRD-0025 graceful-degradation: when JWKS unavailable at startup, the middleware
    decodes claims without signature check so downstream handlers still get state.
    """
    import time

    import jwt  # PyJWT

    # Build an unsigned (none-alg) token — payload only, no signature check needed
    payload = {
        "sub": "user-123",
        "tenant_id": "tenant-abc",
        "role": "viewer",
        "iss": "worldview-gateway",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, key="", algorithm="none")

    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments", headers={"X-Internal-JWT": token})
    # Middleware passes (public_key is None, decode without verification succeeds)
    assert resp.status_code == 200


# ── Async client tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt_async() -> None:
    """Async: no X-Internal-JWT on protected path → 401."""
    app = _make_middleware_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/instruments")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_middleware_skips_health_path_async() -> None:
    """Async: GET /healthz passes without X-Internal-JWT."""
    app = _make_middleware_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code in (200, 503)
