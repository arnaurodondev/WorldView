"""Unit tests for InternalJWTMiddleware on knowledge-graph (T-D-1-06)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from knowledge_graph.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

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
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iss": iss,
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
    """Build a minimal FastAPI app with _PreKeyedJWTMiddleware."""
    app = FastAPI()

    @app.get("/api/v1/relations")
    async def relations_route(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "tenant_id": getattr(request.state, "tenant_id", None),
                "role": getattr(request.state, "role", None),
            }
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


async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401."""
    _, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations")
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


async def test_middleware_skips_health_path() -> None:
    """GET /health passes without X-Internal-JWT."""
    _, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


async def test_middleware_rejects_invalid_jwt() -> None:
    """Invalid (wrong-algorithm) JWT → 401."""
    _, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)
    hs_token = jwt.encode(
        {"sub": "u", "tenant_id": "t", "role": "user", "iss": "worldview-gateway", "exp": int(time.time()) + 3600},
        "some-hmac-secret",
        algorithm="HS256",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": hs_token})
    assert resp.status_code == 401


async def test_middleware_rejects_expired_jwt() -> None:
    """Expired JWT → 401."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)
    expired_token = _make_token(private_key, exp_offset=-60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": expired_token})
    assert resp.status_code == 401


async def test_middleware_sets_claims_on_valid_jwt() -> None:
    """Valid RS256 JWT → 200, request.state fields set."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)
    token = _make_token(private_key, tenant_id="t-kg", role="user")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "t-kg"
    assert body["role"] == "user"


async def test_middleware_passes_through_when_no_public_key() -> None:
    """When _public_key is None (startup not called), request with token passes through."""
    app = _build_app(public_key=None)
    token = "any-token-value"  # noqa: S105
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": token})
    assert resp.status_code == 200
