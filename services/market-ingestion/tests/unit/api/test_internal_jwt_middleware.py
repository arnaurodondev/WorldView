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


@pytest.mark.asyncio
async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True).

    market-ingestion has no Valkey on app.state in production, so this test
    verifies the code path where Valkey IS present (forward-compat scenario).
    """
    from unittest.mock import AsyncMock

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",
            "jti": "mi-jti-first-use",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=True)  # SET NX succeeded → new key
    mock_app.state.valkey = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/tasks",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 200
    assert called


@pytest.mark.asyncio
async def test_jti_replay_rejected() -> None:
    """F-012: Second request with same jti returns 401 (Valkey SET NX returns None = key existed)."""
    from unittest.mock import AsyncMock

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",
            "jti": "mi-replayed-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=False)  # SET NX failed → key already present
    mock_app.state.valkey = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/tasks",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


@pytest.mark.asyncio
async def test_internal_jwt_rejects_wrong_issuer():
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    # Generate a fresh RSA key pair — we control both sides in this unit test.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Craft a token that is properly signed but carries the wrong issuer.
    evil_token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "evil",  # <-- wrong issuer; should be "worldview-gateway"
            "exp": 9999999999,
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
        "method": "GET",
        "path": "/api/v1/tasks",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", evil_token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _mock_call_next)

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert result.status_code == 401
    assert not called  # route handler must NOT have been called
