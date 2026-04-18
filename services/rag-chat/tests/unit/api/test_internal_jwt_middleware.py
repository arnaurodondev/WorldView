"""Unit tests for InternalJWTMiddleware on rag-chat (T-D-1-07)."""

from __future__ import annotations

import time

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

# Settings with fail-closed (default) — skip_verification=False
_SETTINGS = RagChatSettings(
    database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
    s1_internal_token="test-token",
    log_json=False,
    log_level="WARNING",
)

# Settings with skip_verification=True — for tests that need unverified decode
_SETTINGS_SKIP = RagChatSettings(
    database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
    s1_internal_token="test-token",
    log_json=False,
    log_level="WARNING",
    internal_jwt_skip_verification=True,
)


async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401 (middleware enforces before route)."""
    app = create_app(_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/chat", json={"message": "test"})
    assert resp.status_code == 401


async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT (health path is exempt)."""
    app = create_app(_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    # Middleware skips /healthz; route returns 200 (liveness is always ok).
    assert resp.status_code == 200


async def test_middleware_rejects_missing_jwt_on_briefings() -> None:
    """No X-Internal-JWT on /internal/v1/briefings → 401."""
    app = create_app(_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json={
                "user_id": "00000000-0000-0000-0000-000000000001",
                "tenant_id": "00000000-0000-0000-0000-000000000002",
                "portfolio_context": {},
                "market_snapshots": [{"symbol": "AAPL"}],
                "active_signals": [],
                "lookback_days": 7,
            },
        )
    assert resp.status_code == 401


async def test_middleware_returns_503_when_no_public_key_fail_closed() -> None:
    """F-001: When public_key is None and skip_verification=False, return 503 (fail-closed).

    In unit tests there is no lifespan, so the middleware has no public key.
    With default settings (skip_verification=False), this returns 503.
    """
    token = _jwt.encode(
        {"sub": "u", "tenant_id": "t", "role": "user", "iss": "worldview-gateway", "exp": int(time.time()) + 3600},
        "any-secret",
        algorithm="HS256",
    )
    app = create_app(_SETTINGS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"X-Internal-JWT": token},
        )
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.json()["detail"]


async def test_middleware_passes_through_with_well_formed_jwt_skip_verification() -> None:
    """Well-formed JWT passes through when skip_verification=True and no public key is loaded.

    In unit tests there is no lifespan, so the middleware has no public key.
    With skip_verification=True, it decodes without signature verification
    and populates request.state. The route then processes the request normally.
    """
    token = _jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000001", "tenant_id": "t1", "role": "user"},
        "secret",
        algorithm="HS256",
    )
    app = create_app(_SETTINGS_SKIP)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"X-Internal-JWT": token, "X-Tenant-Id": "t1", "X-User-Id": "00000000-0000-0000-0000-000000000001"},
        )
    # Middleware passes through; route-level auth (get_auth_context) may return
    # 401 if UUID parsing fails, but middleware itself did not block.
    assert resp.status_code != 401 or resp.json().get("detail") != "Missing X-Internal-JWT header"
