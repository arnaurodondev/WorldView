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
async def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import jwt
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from cryptography.hazmat.primitives.asymmetric import rsa
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

    # Inject the RSA public key directly — bypasses JWKS HTTP fetch.
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
        "path": "/api/v1/documents/batch",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", evil_token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _mock_call_next)

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert result.status_code == 401
    assert not called  # route handler must NOT have been called


@pytest.mark.asyncio
async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True)."""
    from unittest.mock import AsyncMock

    import jwt
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from cryptography.hazmat.primitives.asymmetric import rsa
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
            "jti": "cs-jti-first-use",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # content-store uses app.state.valkey_client (not app.state.valkey)
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set = AsyncMock(return_value=True)  # SET NX succeeded → new key
    mock_app.state.valkey_client = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/documents/batch",
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
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from cryptography.hazmat.primitives.asymmetric import rsa
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
            "jti": "cs-replayed-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # content-store uses app.state.valkey_client
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set = AsyncMock(return_value=None)  # SET NX failed → key already present
    mock_app.state.valkey_client = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/documents/batch",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


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
