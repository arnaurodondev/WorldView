"""Unit tests for InternalJWTMiddleware on alert service (T-D-1-08)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from alert.infrastructure.websocket.manager import ConnectionManager
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_app(**settings_kwargs: object) -> object:
    """Create a wired app with mock session factory for unit tests."""
    base: dict[str, object] = {
        "kafka_bootstrap_servers": "localhost:9092",
        "kafka_schema_registry_url": "http://localhost:8081",
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test",
        "s8_internal_token": "test-s8",
        "s1_internal_token": "test-s1",
    }
    base.update(settings_kwargs)
    settings = Settings(**base)  # type: ignore[arg-type]
    app = create_app(settings)

    # Wire minimal state so routes don't crash on missing DB state
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory
    app.state.read_factory = mock_factory

    # R27: read_uow_factory — used by get_pending_alerts_uc dependency.
    from alert.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork

    app.state.read_uow_factory = lambda: SqlaReadOnlyUnitOfWork(mock_factory)

    app.state.ws_manager = ConnectionManager()
    return app


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT (skipped by middleware prefix match)."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    # /healthz is a liveness probe — returns 200 without any infra state
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_middleware_returns_503_when_no_public_key() -> None:
    """F-001: With default skip_verification=False and no public key loaded,
    middleware returns 503 (fail-closed) instead of accepting unverified JWTs.
    """
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": "any.jwt.here"})
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.text


@pytest.mark.asyncio
async def test_middleware_rejects_invalid_jwt_with_skip_verification() -> None:
    """Invalid (malformed) X-Internal-JWT → 401 (via get_current_user_id dependency)
    when skip_verification=True and public key is not loaded.

    When the token is malformed, InternalJWTMiddleware sets empty user_id in
    request.state. The get_current_user_id dependency then raises 401.
    """
    app = _make_app(internal_jwt_skip_verification=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": "bad.jwt"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import jwt as pyjwt
    from alert.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate a fresh RSA key pair — we control both sides in this unit test.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Craft a token that is properly signed but carries the wrong issuer.
    evil_token = pyjwt.encode(
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

    # Build a minimal FastAPI app with the middleware pre-loaded with the public key.
    test_app = FastAPI()

    @test_app.get("/api/v1/test")
    async def _test_route(request: Request) -> dict[str, Any]:
        return {"ok": True}

    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://localhost:9999/internal/jwks",
        skip_verification=True,  # set skip so test can inject public key directly
    )

    # Inject the public key directly — bypasses JWKS HTTP fetch in unit tests.
    from starlette.applications import Starlette

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key

    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=True)
    mw._public_key = public_key

    called: list[bool] = []

    async def _mock_call_next(req: StarletteRequest) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/test",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", evil_token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(StarletteRequest(scope), _mock_call_next)

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert result.status_code == 401
    assert not called  # route handler must NOT have been called


@pytest.mark.asyncio
async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True)."""
    from unittest.mock import AsyncMock

    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Token with a jti claim — first time this jti is seen.
    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "jti": "unique-jti-first-use",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # Mock app with Valkey returning True (was_new = True → first use accepted).
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
        "path": "/api/v1/alerts/pending",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # First use → route handler is called → 200
    assert result.status_code == 200
    assert called


@pytest.mark.asyncio
async def test_jti_replay_rejected() -> None:
    """F-012: Second request with same jti returns 401 (Valkey SET NX returns None = key existed)."""
    from unittest.mock import AsyncMock

    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "jti": "replayed-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # Mock app with Valkey returning None (was_new = None → key already existed → replay).
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
        "path": "/api/v1/alerts/pending",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # Replay detected → middleware returns 401, route handler NOT called
    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


@pytest.mark.asyncio
async def test_jti_check_skipped_when_valkey_unavailable() -> None:
    """F-012: Request proceeds when Valkey.set() raises an exception (fail-open)."""
    from unittest.mock import AsyncMock

    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "jti": "any-jti-valkey-down",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # Mock Valkey that raises on set() — simulates Valkey being unreachable.
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(side_effect=ConnectionError("Valkey is down"))
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
        "path": "/api/v1/alerts/pending",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # Fail-open: Valkey error must not block the request → route handler is called → 200
    assert result.status_code == 200
    assert called


@pytest.mark.asyncio
async def test_jti_check_skipped_when_no_jti() -> None:
    """F-012: JWT without jti claim is accepted without any Valkey interaction."""
    from unittest.mock import AsyncMock

    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Token WITHOUT a jti claim — backward-compat path.
    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            # No "jti" field
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock()  # should never be called
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
        "path": "/api/v1/alerts/pending",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # No jti → Valkey never consulted, request passes through → 200
    assert result.status_code == 200
    assert called
    # Confirm Valkey.set_nx was not called at all
    mock_valkey.set_nx.assert_not_called()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_skip_verification_flag_allows_bypass() -> None:
    """F-001: When skip_verification=True and no public key, middleware decodes
    JWT without signature verification and passes through to route handler.

    Uses a minimal FastAPI app (not create_app) to isolate middleware behavior
    from route-level dependencies like DB sessions.
    """
    import jwt as pyjwt

    # Minimal app with a simple test route — no DB dependencies.
    # Request + Any imported at module level so __future__ annotations can resolve them.
    test_app = FastAPI()

    @test_app.get("/api/v1/test")
    async def _test_route(request: Request) -> dict[str, Any]:
        return {
            "user_id": getattr(request.state, "user_id", ""),
            "tenant_id": getattr(request.state, "tenant_id", ""),
            "role": getattr(request.state, "role", ""),
        }

    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://localhost:9999/internal/jwks",
        skip_verification=True,
    )

    token = pyjwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "t-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "secret",
        algorithm="HS256",
    )
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test", headers={"X-Internal-JWT": token})
    # Middleware passed — route handler returns claims from request.state
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-1"
    assert body["tenant_id"] == "t-1"
    assert body["role"] == "owner"
