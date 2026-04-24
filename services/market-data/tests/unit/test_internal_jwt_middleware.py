"""Unit tests for InternalJWTMiddleware on market-data (T-D-1-02).

F-001 update: The middleware now defaults to fail-closed (503) when the JWKS public
key is unavailable.  Tests that need the old pass-through behavior must explicitly
create the middleware with ``skip_verification=True``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = pytest.mark.unit


def _make_middleware_app(*, skip_verification: bool = False) -> FastAPI:
    """Minimal FastAPI app with InternalJWTMiddleware (no public key — startup not called).

    Args:
        skip_verification: F-001 flag.  When False (default), the middleware returns
            503 if the JWKS public key is unavailable.  Set to True for tests that
            exercise the unverified-decode path (E2E-only escape hatch).
    """
    app = FastAPI()
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://api-gateway:8000/internal/jwks",
        skip_verification=skip_verification,
    )

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


def test_middleware_returns_503_when_no_public_key() -> None:
    """F-001: JWT present but no public key loaded → 503 (fail-closed).

    When JWKS is unavailable (public_key is None) and skip_verification is False
    (the default), the middleware rejects the request with 503 to prevent any forged
    JWT from being accepted without signature verification.
    """
    app = _make_middleware_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments", headers={"X-Internal-JWT": "not.a.jwt"})
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.json()["detail"]


def test_middleware_passes_through_with_skip_verification_invalid_jwt() -> None:
    """F-001: With skip_verification=True, malformed JWT passes through when no public key.

    This path exists ONLY for E2E tests without the full S9 stack.  The middleware
    catches jwt.DecodeError, sets empty state, and calls call_next.
    """
    app = _make_middleware_app(skip_verification=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments", headers={"X-Internal-JWT": "not.a.jwt"})
    # skip_verification=True: DecodeError → empty state → passes through → 200
    assert resp.status_code == 200


def test_middleware_passes_valid_unsigned_jwt_with_skip_verification() -> None:
    """F-001: With skip_verification=True, a well-formed JWT passes through when no public key.

    The middleware decodes claims without signature check so downstream handlers still
    get state.  This escape hatch exists only for E2E tests without S9.
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

    app = _make_middleware_app(skip_verification=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/instruments", headers={"X-Internal-JWT": token})
    # skip_verification=True: decode without verification succeeds → 200
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


@pytest.mark.asyncio
async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True).

    market-data stores Valkey as app.state.valkey_client.
    """
    import time
    from unittest.mock import AsyncMock

    import jwt  # PyJWT
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "viewer",
            "iss": "worldview-gateway",
            "jti": "md-jti-first-use",
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )

    # market-data uses app.state.valkey_client (not app.state.valkey)
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=True)  # SET NX succeeded → new key
    mock_app.state.valkey_client = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/instruments",
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
    import time
    from unittest.mock import AsyncMock

    import jwt  # PyJWT
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "viewer",
            "iss": "worldview-gateway",
            "jti": "md-replayed-jti",
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )

    # market-data uses app.state.valkey_client
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=False)  # SET NX failed → key already present
    mock_app.state.valkey_client = mock_valkey

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/instruments",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import time

    import jwt  # PyJWT
    from cryptography.hazmat.primitives.asymmetric import rsa
    from market_data.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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
            "role": "viewer",
            "iss": "evil",  # <-- wrong issuer; should be "worldview-gateway"
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )

    # Inject the public key directly — bypasses JWKS HTTP fetch in unit tests.
    import asyncio

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
        "path": "/api/v1/instruments",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", evil_token.encode())],
        "app": mock_app,
    }

    result = asyncio.get_event_loop().run_until_complete(mw.dispatch(Request(scope), _mock_call_next))

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert result.status_code == 401
    assert not called  # route handler must NOT have been called
