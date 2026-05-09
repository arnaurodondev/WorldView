"""Unit tests for InternalJWTMiddleware (PRD-0025 §6.5, T-C-1-05)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from portfolio.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = [pytest.mark.unit]

# ── RSA key helpers ───────────────────────────────────────────────────────────


def _generate_rsa_pair() -> tuple[Any, Any]:
    """Return (private_key, public_key) RSA-2048 pair."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_token(
    private_key: Any,
    sub: str = "user-123",
    tenant_id: str = "tenant-abc",
    role: str = "user",
    iss: str = "worldview-gateway",
    aud: str = "worldview-internal",
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iss": iss,
        "aud": aud,
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


# ── Test app factory ──────────────────────────────────────────────────────────


class _PreKeyedJWTMiddleware(InternalJWTMiddleware):
    """Subclass that accepts a pre-built public key to avoid HTTP calls in tests."""

    def __init__(self, app: Any, public_key: Any) -> None:
        super().__init__(app, jwks_url="http://unused-in-test/internal/jwks")
        self._public_key = public_key


def _build_app(public_key: Any = None) -> FastAPI:
    """Build a FastAPI app with _PreKeyedJWTMiddleware.

    The public key is stored on app.state._internal_jwt_public_key so that
    InternalJWTMiddleware.dispatch() can read it via request.app.state.
    """
    app = FastAPI()

    # Inject the key into app.state so dispatch() can read it.
    # This mirrors what startup() does in production (writing to self.app.state).
    if public_key is not None:
        app.state._internal_jwt_public_key = public_key

    @app.get("/api/v1/data")
    async def data_route(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "tenant_id": getattr(request.state, "tenant_id", None),
                "role": getattr(request.state, "role", None),
            },
        )

    @app.get("/health")
    async def health_route() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/metrics")
    async def metrics_route() -> JSONResponse:
        return JSONResponse({"metric": 1})

    app.add_middleware(_PreKeyedJWTMiddleware, public_key=public_key)
    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_internal_jwt_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header and public key loaded → 401."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data")

    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


async def test_internal_jwt_middleware_rejects_expired() -> None:
    """Expired JWT → 401."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    expired_token = _make_token(private_key, exp_offset=-60)  # expired 60s ago

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": expired_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_rejects_wrong_issuer() -> None:
    """iss != worldview-gateway → 401."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    bad_iss_token = _make_token(private_key, iss="evil-gateway")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": bad_iss_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_sets_tenant_id() -> None:
    """Valid JWT → request.state.tenant_id/role set; 200 response."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    token = _make_token(private_key, tenant_id="t-123", role="user")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "t-123"
    assert body["role"] == "user"


async def test_internal_jwt_middleware_skips_health() -> None:
    """GET /health passes without X-Internal-JWT header."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200


async def test_internal_jwt_middleware_skips_metrics() -> None:
    """GET /metrics passes without X-Internal-JWT header."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 200


async def test_internal_jwt_middleware_returns_503_when_no_key() -> None:
    """When JWKS not loaded (public_key is None), return 503 Service Unavailable.

    F-001 / F-SEC-001: The fail-open path (unverified decode) was removed. Requests
    must be rejected when the service hasn't loaded its public key yet — this prevents
    auth bypass via timing attacks during startup.
    """
    app = _build_app(public_key=None)  # no key loaded

    token = "any-token-value"  # noqa: S105

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 503
    assert "jwks not loaded" in resp.json()["detail"].lower()


async def test_startup_raises_on_jwks_failure() -> None:
    """F-003: startup() raises RuntimeError after 3 failed JWKS fetch attempts."""
    from starlette.applications import Starlette

    mock_app = Starlette()
    middleware = InternalJWTMiddleware(
        mock_app,
        jwks_url="http://unreachable:9999/internal/jwks",
    )
    with pytest.raises(RuntimeError, match="JWKS startup failed"):
        await middleware.startup()


async def test_internal_jwt_middleware_rejects_wrong_algorithm() -> None:
    """HS256 token (wrong algorithm) → 401."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    # Sign with HS256 instead of RS256
    hs_token = jwt.encode(
        {"sub": "u", "tenant_id": "t", "role": "user", "iss": "worldview-gateway", "exp": int(time.time()) + 3600},
        "some-hmac-secret",
        algorithm="HS256",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": hs_token})

    assert resp.status_code == 401
