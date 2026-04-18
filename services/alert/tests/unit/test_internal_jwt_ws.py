"""Tests for InternalJWTMiddleware WebSocket token support (PRD-0028 Wave S9-2).

Verifies that:
- WebSocket upgrade requests read the JWT from ?token= query param
- Normal HTTP requests still read from X-Internal-JWT header
- Missing token on WS upgrade returns 401
"""

from __future__ import annotations

from typing import Any

import jwt as pyjwt
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_PAYLOAD = {
    "iss": "worldview-gateway",
    "sub": "user-1",
    "tenant_id": "t-1",
    "role": "user",
    "scope": "alerts:stream",
    "jti": "test-jti-001",
    "iat": 1000000000,
    "exp": 9999999999,
}

# HS256 token used for the "no public key" fallback path
_HS256_SECRET = "test-secret"  # noqa: S105


def _make_unsigned_jwt() -> str:
    """Create an HS256-signed JWT that the middleware will decode without verification
    (since we don't inject a public key into the middleware).
    """
    return pyjwt.encode(_JWT_PAYLOAD, _HS256_SECRET, algorithm="HS256")


def _make_app_with_middleware() -> FastAPI:
    """Build a minimal FastAPI app with InternalJWTMiddleware (no public key loaded)."""
    from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

    app = FastAPI()

    @app.get("/api/v1/alerts/pending")
    async def pending_alerts(request: Request) -> dict[str, Any]:
        return {
            "user_id": getattr(request.state, "user_id", ""),
            "tenant_id": getattr(request.state, "tenant_id", ""),
            "role": getattr(request.state, "role", ""),
        }

    # Add middleware — no public key will be loaded (startup not called).
    # skip_verification=True so the middleware falls back to
    # decode-without-verification path (F-001: default is fail-closed 503).
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://localhost:9999/internal/jwks",
        skip_verification=True,
    )

    return app


@pytest.mark.asyncio
async def test_internal_jwt_http_still_reads_header() -> None:
    """Normal HTTP request reads JWT from X-Internal-JWT header."""
    app = _make_app_with_middleware()
    token = _make_unsigned_jwt()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/alerts/pending",
            headers={"X-Internal-JWT": token},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-1"
    assert body["tenant_id"] == "t-1"
    assert body["role"] == "user"


@pytest.mark.asyncio
async def test_internal_jwt_ws_upgrade_reads_query_param() -> None:
    """WebSocket upgrade request reads JWT from ?token= query param.

    We simulate a WebSocket upgrade by sending an HTTP request with the
    ``Upgrade: websocket`` header. The middleware should read the token
    from the query parameter instead of X-Internal-JWT header.
    """
    app = _make_app_with_middleware()
    token = _make_unsigned_jwt()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Send request with Upgrade: websocket header and ?token= query param
        resp = await client.get(
            f"/api/v1/alerts/pending?token={token}",
            headers={"Upgrade": "websocket"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-1"
    assert body["tenant_id"] == "t-1"


@pytest.mark.asyncio
async def test_internal_jwt_ws_upgrade_missing_token() -> None:
    """WebSocket upgrade without ?token= → 401."""
    app = _make_app_with_middleware()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # WebSocket upgrade with no token at all
        resp = await client.get(
            "/api/v1/alerts/pending",
            headers={"Upgrade": "websocket"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_jwt_ws_upgrade_ignores_header() -> None:
    """WebSocket upgrade with X-Internal-JWT header but no ?token= → 401.

    The middleware must only read from ?token= for WebSocket upgrades,
    not from the X-Internal-JWT header. This prevents header confusion
    in environments where headers might leak through.
    """
    app = _make_app_with_middleware()
    token = _make_unsigned_jwt()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/alerts/pending",
            headers={
                "Upgrade": "websocket",
                "X-Internal-JWT": token,
            },
        )

    # Even though X-Internal-JWT is set, the middleware should only check ?token=
    # for WebSocket upgrades — so this should fail with 401
    assert resp.status_code == 401
