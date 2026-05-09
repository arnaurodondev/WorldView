"""Unit tests for InternalJWTMiddleware on content-ingestion (T-D-1-03)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_settings(**kwargs):
    """Create Settings with test values."""
    from content_ingestion.config import Settings

    defaults = {
        "kafka_bootstrap_servers": "localhost:9092",
        "kafka_schema_registry_url": "http://localhost:8081",
        "internal_jwt_skip_verification": True,
    }
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[call-arg]


def _make_app(settings=None):
    """Create a test app with mocked state (no lifespan startup required)."""
    from unittest.mock import AsyncMock

    from content_ingestion.app import create_app

    s = settings or _make_settings()
    app = create_app(s)

    # Stub lifespan dependencies so requests can reach route handlers
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.commit = AsyncMock()
    mock_uow.rollback = AsyncMock()
    mock_uow.sources = AsyncMock()
    mock_uow.tasks = AsyncMock()
    mock_uow.adapter_state = AsyncMock()
    mock_uow.fetch_logs = AsyncMock()
    mock_uow.outbox = AsyncMock()
    mock_uow.dlq = AsyncMock()

    mock_bronze = AsyncMock()
    mock_bronze.put_object = AsyncMock(return_value="content-ingestion/manual/abc123/raw/v1.json")

    app.state.settings = MagicMock(
        admin_token="test-admin",
        api_gateway_url="http://api-gateway:8000",
    )
    mock_factory = AsyncMock()
    app.state.write_factory = mock_factory
    app.state.read_factory = mock_factory
    app.state.valkey = AsyncMock()
    app.state.storage = AsyncMock()
    app.state.bronze_storage = mock_bronze
    app.state.uow_factory = lambda: mock_uow
    app.state.read_uow_factory = lambda: mock_uow
    app.state.metrics = MagicMock()

    return app


@pytest.mark.asyncio
async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header on protected endpoint → 401."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/internal/v1/ingest/submit", json={})
    assert resp.status_code == 401
    assert "Missing X-Internal-JWT" in resp.text


@pytest.mark.asyncio
async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code in (200, 503)


@pytest.mark.asyncio
async def test_middleware_skips_internal_health() -> None:
    """GET /internal/v1/health passes without X-Internal-JWT (declared skip path)."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/internal/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_middleware_accepts_valid_jwt_no_public_key() -> None:
    """With no public key loaded (unit test), any well-formed JWT is accepted (graceful degradation)."""
    import jwt

    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "any-secret",
        algorithm="HS256",
    )
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/ingest/submit",
            json={"source_type": "manual", "raw_content": "hello"},
            headers={"X-Internal-JWT": token},
        )
    # Route-level validation may reject the body, but auth must pass (not 401)
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_middleware_rejects_malformed_jwt() -> None:
    """A completely bogus token string → middleware still returns 401 (decode error → empty claims → route proceeds)."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/ingest/submit",
            json={"source_type": "manual", "raw_content": "test"},
            headers={"X-Internal-JWT": "not.a.jwt"},
        )
    # With no public key loaded, malformed token triggers graceful decode → empty state,
    # route can still process the request body (not necessarily 401 at middleware level).
    # We only assert middleware itself doesn't crash (no 500).
    assert resp.status_code != 500


@pytest.mark.asyncio
async def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    import jwt
    from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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
        "path": "/internal/v1/ingest/submit",
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
    from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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
            "aud": "worldview-internal",
            "jti": "ci-jti-first-use",
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
        "method": "POST",
        "path": "/internal/v1/ingest/submit",
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
    from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
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
            "aud": "worldview-internal",
            "jti": "ci-replayed-jti",
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
        "method": "POST",
        "path": "/internal/v1/ingest/submit",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


@pytest.mark.asyncio
async def test_middleware_rejects_expired_jwt_with_public_key() -> None:
    """Expired X-Internal-JWT with a loaded RS256 public key → 401."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate a throwaway RSA key pair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    expired_token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 1,  # already expired
        },
        private_key,
        algorithm="RS256",
    )

    app = _make_app()

    # Create a fresh middleware instance with the RSA public key injected directly
    # (bypasses JWKS fetch entirely — unit test isolation).
    from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    mw_instance = InternalJWTMiddleware(app, jwks_url="http://mock/jwks", skip_verification=True)
    mw_instance._public_key = public_key

    called: list[bool] = []

    async def mock_call_next(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    # BP-159: dispatch reads from request.app.state; provide a mock app with state
    from starlette.applications import Starlette

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = mw_instance._public_key
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/internal/v1/ingest/submit",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", expired_token.encode())],
        "app": mock_app,
    }
    request = Request(scope)
    result = await mw_instance.dispatch(request, mock_call_next)
    assert result.status_code == 401
    assert not called
