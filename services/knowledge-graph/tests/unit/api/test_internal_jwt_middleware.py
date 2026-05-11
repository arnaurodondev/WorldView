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
    aud: str = "worldview-internal",
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iss": iss,
        "aud": aud,  # DEF-002: audience claim required by middleware
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


# ── Test app factory ──────────────────────────────────────────────────────────


class _PreKeyedJWTMiddleware(InternalJWTMiddleware):
    """Subclass that accepts a pre-built public key to avoid HTTP calls in tests."""

    def __init__(
        self,
        app: Any,
        public_key: Any,
        *,
        skip_verification: bool = False,
        jti_replay_check_enabled: bool = True,
    ) -> None:
        super().__init__(
            app,
            jwks_url="http://unused-in-test/internal/jwks",
            skip_verification=skip_verification,
            jti_replay_check_enabled=jti_replay_check_enabled,
        )
        self._public_key = public_key


def _build_app(
    public_key: Any = None,
    *,
    skip_verification: bool = False,
    jti_replay_check_enabled: bool = True,
) -> FastAPI:
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

    app.add_middleware(
        _PreKeyedJWTMiddleware,
        public_key=public_key,
        skip_verification=skip_verification,
        jti_replay_check_enabled=jti_replay_check_enabled,
    )
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


async def test_middleware_returns_503_when_no_public_key_fail_closed() -> None:
    """F-001: When _public_key is None and skip_verification=False, return 503 (fail-closed)."""
    app = _build_app(public_key=None, skip_verification=False)
    token = "any-token-value"  # noqa: S105
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": token})
    assert resp.status_code == 503
    assert "JWKS not loaded" in resp.json()["detail"]


async def test_middleware_passes_through_when_no_public_key_skip_verification() -> None:
    """When _public_key is None and skip_verification=True, decode without verification."""
    app = _build_app(public_key=None, skip_verification=True)
    token = jwt.encode(
        {"sub": "u", "tenant_id": "t", "role": "user", "iss": "worldview-gateway", "exp": int(time.time()) + 3600},
        "any-secret",
        algorithm="HS256",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": token})
    assert resp.status_code == 200


async def test_jti_first_use_accepted() -> None:
    """F-012: First request with a unique jti is accepted (Valkey SET NX returns True)."""

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key, public_key = _generate_rsa_pair()
    # Encode with jti field included (jti is not part of _make_token's default payload)
    token_with_jti = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-abc",
            "role": "user",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",  # DEF-002: required by middleware
            "jti": "kg-jti-first-use",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # knowledge-graph has no Valkey — getattr returns None → JTI check skipped.
    # Test that the middleware still accepts the request normally.
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    # Intentionally NOT setting mock_app.state.valkey — simulates no Valkey in production.

    mw = InternalJWTMiddleware(mock_app, jwks_url="http://mock/jwks", skip_verification=False)
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/relations",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token_with_jti.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # No Valkey → JTI check skipped → request passes through → 200
    assert result.status_code == 200
    assert called


async def test_jti_replay_rejected_when_check_enabled() -> None:
    """F-012: Replay returns 401 when jti_replay_check_enabled=True and Valkey SET NX returns False.

    This verifies the check mechanism works correctly when explicitly turned on.
    In production, S7 runs with jti_replay_check_enabled=False (see config.py).
    """
    from unittest.mock import AsyncMock

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key, public_key = _generate_rsa_pair()
    token_with_jti = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-abc",
            "role": "user",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",  # DEF-002: required by middleware
            "jti": "kg-replayed-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    # Inject a mock Valkey on app.state to simulate Valkey being present.
    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=False)  # SET NX failed → replay detected
    mock_app.state.valkey = mock_valkey

    # Explicitly enable replay check to confirm enforcement works
    mw = InternalJWTMiddleware(
        mock_app,
        jwks_url="http://mock/jwks",
        skip_verification=False,
        jti_replay_check_enabled=True,
    )
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/relations",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token_with_jti.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    assert result.status_code == 401
    assert b"replay" in result.body
    assert not called


async def test_jti_replay_allowed_when_check_disabled() -> None:
    """F-012-internal: jti_replay_check_enabled=False skips Valkey check entirely.

    This is the production behaviour for S7 (knowledge-graph) and S6 (nlp-pipeline).
    S8 (rag-chat) forwards the same JWT to S7 multiple times per user request
    (graph enrichment call, entity search call). Without this flag the second call
    would be rejected as a replay even though it is a legitimate fan-out from S8.
    """
    from unittest.mock import AsyncMock

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response

    private_key, public_key = _generate_rsa_pair()
    token_with_jti = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-abc",
            "role": "user",
            "iss": "worldview-gateway",
            "aud": "worldview-internal",  # DEF-002: required by middleware
            "jti": "kg-replay-disabled-jti",
            "exp": 9999999999,
        },
        private_key,
        algorithm="RS256",
    )

    mock_app = Starlette()
    mock_app.state._internal_jwt_public_key = public_key
    # Valkey present and would reject replay if the check ran
    mock_valkey = AsyncMock()
    mock_valkey.set_nx = AsyncMock(return_value=False)  # would signal "replay" if called
    mock_app.state.valkey = mock_valkey

    # jti_replay_check_enabled=False — Valkey must NOT be consulted at all
    mw = InternalJWTMiddleware(
        mock_app,
        jwks_url="http://mock/jwks",
        skip_verification=False,
        jti_replay_check_enabled=False,
    )
    mw._public_key = public_key

    called: list[bool] = []

    async def _ok(req: Request) -> Response:
        called.append(True)
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/relations",
        "query_string": b"",
        "headers": [(b"x-internal-jwt", token_with_jti.encode())],
        "app": mock_app,
    }
    result = await mw.dispatch(Request(scope), _ok)

    # Request must pass through: replay check is disabled
    assert result.status_code == 200
    assert called
    # Valkey must not have been touched at all
    mock_valkey.set_nx.assert_not_called()


async def test_internal_jwt_rejects_wrong_issuer() -> None:
    """JWT with wrong issuer returns 401 (F-015).

    PyJWT now validates the issuer claim natively via the ``issuer=`` parameter
    in ``jwt.decode()``. A token signed with the correct RS256 key but carrying
    ``iss=evil`` must be rejected with 401, not passed through to route handlers.
    """
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    # Craft a token that is properly signed but carries the wrong issuer.
    evil_token = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-abc",
            "role": "user",
            "iss": "evil",  # <-- wrong issuer; should be "worldview-gateway"
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": evil_token})

    # Wrong issuer → PyJWT raises InvalidIssuerError → middleware returns 401
    assert resp.status_code == 401


# ── F-001 (PLAN-0087 audit) — JWT audience negative tests ─────────────────────
#
# Commit 80dfc0fc added audience="worldview-internal" + "aud" to options.require
# but no negative test asserted wrong/missing aud → 401.  qa-beta-test-engineer
# (2026-05-09) flagged this BLOCKING — these three tests close the gap by
# pinning the rejection contract from both sides.


async def test_internal_jwt_middleware_rejects_wrong_audience() -> None:
    """F-001: aud="zitadel-frontend" → 401 (must be "worldview-internal")."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    bad_aud_token = _make_token(private_key, aud="zitadel-frontend")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": bad_aud_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_rejects_missing_audience() -> None:
    """F-001: token without aud claim → 401 (require-list catches it)."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    # Build directly to omit the aud claim — _make_token always inserts it.
    payload = {
        "sub": "user-123",
        "tenant_id": "tenant-abc",
        "role": "user",
        "iss": "worldview-gateway",
        "exp": int(time.time()) + 3600,
    }
    no_aud_token = jwt.encode(payload, private_key, algorithm="RS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": no_aud_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_accepts_multi_audience_list_containing_expected() -> None:
    """F-001: aud=["worldview-internal", "other"] → 200 (PyJWT list-aud contract)."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    payload = {
        "sub": "user-123",
        "tenant_id": "tenant-abc",
        "role": "user",
        "iss": "worldview-gateway",
        "aud": ["worldview-internal", "other-audience"],
        "exp": int(time.time()) + 3600,
    }
    multi_aud_token = jwt.encode(payload, private_key, algorithm="RS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/relations", headers={"X-Internal-JWT": multi_aud_token})

    assert resp.status_code == 200
