"""Unit tests for InternalJWTMiddleware on content-store (T-D-1-04)."""

from __future__ import annotations

import pytest
from content_store.app import create_app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


async def test_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header → 401."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/documents/batch", json={"doc_ids": []})
    assert resp.status_code == 401


async def test_middleware_skips_health_path() -> None:
    """GET /healthz passes without X-Internal-JWT (skip-list path)."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code in (200, 503)


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
            "aud": "worldview-internal",
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
        "method": "POST",
        "path": "/api/v1/documents/batch",
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
            "aud": "worldview-internal",
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


# ── F-001 (PLAN-0087 audit) — JWT audience negative tests ─────────────────────
#
# Commit 80dfc0fc added audience="worldview-internal" + "aud" to options.require
# but no negative test asserted wrong/missing aud → 401.  qa-beta-test-engineer
# (2026-05-09) flagged this BLOCKING — content-store handles document writes,
# so an aud-bypass would let any other-audience token (e.g. zitadel-frontend)
# write to gold storage.


async def _cs_dispatch_with_token(token_bytes: bytes, public_key: object) -> object:
    """Helper: dispatch through InternalJWTMiddleware, return Response.

    Mirrors the existing wrong-issuer test pattern in this file.  No jti claim
    is present, so the valkey check is skipped (no Valkey wiring needed).
    """
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    async def _ok(req: Request) -> Response:
        return Response("ok", status_code=200, headers={"x-route-called": "1"})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/documents/batch",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token_bytes)],
        "app": mock_app,
    }
    return await mw.dispatch(Request(scope), _ok)


async def test_internal_jwt_rejects_wrong_audience() -> None:
    """F-001: aud="zitadel-frontend" → 401 (must be "worldview-internal")."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad_aud_token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "aud": "zitadel-frontend",  # WRONG audience
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )
    result = await _cs_dispatch_with_token(bad_aud_token.encode(), private_key.public_key())
    assert result.status_code == 401
    assert "x-route-called" not in result.headers


async def test_internal_jwt_rejects_missing_audience() -> None:
    """F-001: token without aud claim → 401 (require-list catches it)."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    no_aud_token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            # NO "aud" key
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )
    result = await _cs_dispatch_with_token(no_aud_token.encode(), private_key.public_key())
    assert result.status_code == 401
    assert "x-route-called" not in result.headers


async def test_internal_jwt_accepts_multi_audience_list_containing_expected() -> None:
    """F-001: aud=["worldview-internal", "other"] → 200 (PyJWT list-aud contract)."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    multi_aud_token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "role": "owner",
            "iss": "worldview-gateway",
            "aud": ["worldview-internal", "other-audience"],
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )
    result = await _cs_dispatch_with_token(multi_aud_token.encode(), private_key.public_key())
    assert result.status_code == 200
    assert result.headers.get("x-route-called") == "1"


# ── BP-FIX: JWT skip_verification log level ─────────────────────────────────
#
# skip_verification=True logged at CRITICAL during __init__ and on EVERY
# request dispatch, flooding logs with fake CRITICAL events and drowning real
# alerts.  Fixed: __init__ now logs at WARNING (once, on startup); dispatch
# now logs at DEBUG (per-request, suppressed in production log levels).


def test_skip_verification_init_logs_at_warning_not_critical() -> None:
    """__init__ with skip_verification=True must emit WARNING, not CRITICAL."""
    import structlog.testing
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from starlette.applications import Starlette

    with structlog.testing.capture_logs() as cap:
        InternalJWTMiddleware(
            Starlette(),
            jwks_url="http://mock/jwks",
            skip_verification=True,
        )

    skip_logs = [e for e in cap if e.get("event") == "internal_jwt_skip_verification_enabled"]
    assert skip_logs, "expected internal_jwt_skip_verification_enabled log event"
    for entry in skip_logs:
        assert entry.get("log_level") != "critical", (
            "skip_verification startup log must not be CRITICAL — " f"got level={entry.get('log_level')!r}"
        )


async def test_skip_verification_dispatch_logs_at_debug_not_critical() -> None:
    """dispatch() in skip_verification mode must log at DEBUG, not CRITICAL."""
    import jwt
    import structlog.testing
    from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    test_payload = {"sub": "u1", "tenant_id": "t1", "role": "owner"}
    token = jwt.encode(test_payload, "secret", algorithm="HS256")

    test_app = FastAPI()

    @test_app.get("/probe")
    async def _probe() -> dict[str, str]:
        return {"ok": "1"}

    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://mock/jwks",
        skip_verification=True,
    )

    with structlog.testing.capture_logs() as cap:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            resp = await client.get("/probe", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200

    unverified_logs = [e for e in cap if e.get("event") == "internal_jwt_unverified_decode"]
    # The dispatch log fires on each authenticated request; it must NOT be CRITICAL.
    for entry in unverified_logs:
        assert entry.get("log_level") != "critical", (
            "per-request unverified_decode log must not be CRITICAL — " f"got level={entry.get('log_level')!r}"
        )
