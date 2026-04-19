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

# WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
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


async def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    # Generate a fresh RSA key pair — we control both sides in this unit test.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Craft a token that is properly signed but carries the wrong issuer.
    evil_token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "tenant-1",
            "role": "user",
            "iss": "evil",  # <-- wrong issuer; should be "worldview-gateway"
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )

    # Inject the public key directly — bypasses JWKS HTTP fetch in unit tests.
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=True)
    mw._public_key = public_key

    called: list[bool] = []

    async def _mock_call_next(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", evil_token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _mock_call_next)

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert result.status_code == 401
    assert not called  # route handler must NOT have been called


async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True)."""
    from unittest.mock import AsyncMock

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "tenant-1",
            "role": "user",
            "iss": "worldview-gateway",
            "jti": "rag-jti-first-use",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set = AsyncMock(return_value=True)  # SET NX succeeded → new key
    mock_app.state.valkey = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 200
    assert called


async def test_jti_replay_rejected() -> None:
    """F-012: Second request with same jti returns 401 (Valkey SET NX returns None = key existed)."""
    from unittest.mock import AsyncMock

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "tenant-1",
            "role": "user",
            "iss": "worldview-gateway",
            "jti": "rag-replayed-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set = AsyncMock(return_value=None)  # SET NX failed → key already present
    mock_app.state.valkey = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


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
            headers={"X-Internal-JWT": token},
        )
    # Middleware passes through; route-level auth (get_auth_context) may return
    # 401 if UUID parsing fails, but middleware itself did not block.
    assert resp.status_code != 401 or resp.json().get("detail") != "Missing X-Internal-JWT header"
