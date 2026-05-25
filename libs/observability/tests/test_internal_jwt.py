"""Unit tests for the shared observability.internal_jwt module.

REF-001 (W2-05): the bulk of InternalJWTMiddleware behaviour was extracted from
9 per-service copies into ``libs/observability``.  These tests cover the shared
class directly so refactor regressions are caught here rather than across
9 separate service test suites.

Covers:
* valid JWT with known kid → 200
* JWT with unknown kid + cooldown elapsed → refresh runs → 200 (W1-05 path)
* JWT with unknown kid + cooldown active → 401 immediately
* JWT with no kid header → treated as ``"v1"`` (back-compat)
* expired JWT → 401
* wrong issuer → 401
* wrong audience → 401
* skip_verification=True bypasses signature validation
* skip_prefixes match → request passes through without a JWT
* JTI replay (enabled) → second use of same jti → 401
* JTI replay (disabled) → second use passes
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from observability.internal_jwt import InternalJWTMiddleware

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────


def _generate_rsa_pair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Generate an RSA keypair for signing test JWTs."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_token(
    private_key: Any,
    *,
    sub: str = "user-123",
    tenant_id: str = "tenant-abc",
    role: str = "user",
    issuer: str = "worldview-gateway",
    audience: str = "worldview-internal",
    exp_offset: int = 3600,
    jti: str | None = None,
    kid: str | None = None,
) -> str:
    """Encode a test JWT.  Setting any string param overrides the default claim."""
    payload: dict[str, Any] = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
    }
    if jti is not None:
        payload["jti"] = jti
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


class _PreKeyedJWTMiddleware(InternalJWTMiddleware):
    """Test subclass that skips the HTTP JWKS fetch — pre-seeds kid map."""

    def __init__(
        self,
        app: Any,
        keys_by_kid: dict[str, Any],
        post_refresh_map: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(app, jwks_url="http://unused-in-test/internal/jwks", **kwargs)
        self._keys_by_kid = dict(keys_by_kid)
        self._public_key = next(iter(keys_by_kid.values()), None)
        self._post_refresh_map = post_refresh_map
        self._refresh_attempted = 0

    async def _refresh_jwks_if_allowed(self) -> bool:
        """Stub: simulate the rate-limited refresh without an outbound fetch."""
        self._refresh_attempted += 1
        if self._post_refresh_map is not None:
            self._keys_by_kid = dict(self._post_refresh_map)
            self._post_refresh_map = None  # one-shot
            return True
        return False


def _build_app(
    keys_by_kid: dict[str, Any] | None = None,
    post_refresh_map: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[FastAPI, _PreKeyedJWTMiddleware]:
    """Build a FastAPI app with the pre-keyed middleware (no network)."""
    app = FastAPI()
    if keys_by_kid:
        app.state._internal_jwt_public_key = next(iter(keys_by_kid.values()))

    @app.get("/api/v1/data")
    async def data_route(request: Request) -> JSONResponse:  # — fixture
        return JSONResponse(
            {
                "ok": True,
                "tenant_id": getattr(request.state, "tenant_id", None),
            }
        )

    middleware = _PreKeyedJWTMiddleware(
        app,
        keys_by_kid or {},
        post_refresh_map=post_refresh_map,
        **kwargs,
    )

    # Use the pre-built instance (Starlette would normally construct a fresh one).
    from starlette.middleware import Middleware

    class _PassthroughFactory:
        def __new__(cls, app: Any, instance: Any) -> Any:
            instance.app = app
            return instance

    app.user_middleware.insert(0, Middleware(_PassthroughFactory, instance=middleware))
    app.middleware_stack = app.build_middleware_stack()
    return app, middleware


# ── Happy-path & basic validation ─────────────────────────────────────────────


async def test_valid_jwt_with_known_kid_passes() -> None:
    """Token signed with the cached kid should validate and reach the handler."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid="v1", tenant_id="tenant-xyz")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "tenant-xyz"


async def test_jwt_without_kid_uses_default_v1() -> None:
    """A JWT with no kid header falls back to the ``v1`` default (back-compat)."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200


async def test_missing_jwt_returns_401() -> None:
    """Requests without X-Internal-JWT are rejected with 401."""
    _, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data")

    assert resp.status_code == 401
    assert "Missing" in resp.text


async def test_skip_prefix_passes_through_without_jwt() -> None:
    """Paths matching skip_prefixes bypass JWT validation (no 401)."""
    _, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    app.middleware_stack = app.build_middleware_stack()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200


# ── Failure modes ─────────────────────────────────────────────────────────────


async def test_expired_jwt_returns_401() -> None:
    """Expired tokens return 401 with the expired-token body."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid="v1", exp_offset=-60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 401
    assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()


async def test_wrong_issuer_returns_401() -> None:
    """Tokens with mismatched iss are rejected by PyJWT."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid="v1", issuer="evil-gateway")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 401


async def test_wrong_audience_returns_401() -> None:
    """Tokens with mismatched aud are rejected (lateral-movement prevention)."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid="v1", audience="worldview-external")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 401


# ── W1-05 kid-rotation paths ──────────────────────────────────────────────────


async def test_unknown_kid_triggers_refresh_and_succeeds() -> None:
    """W1-05 (b): kid not in cache → refresh runs → new kid is found → 200."""
    private, public = _generate_rsa_pair()
    app, middleware = _build_app(
        keys_by_kid={"v1": public},
        post_refresh_map={"v1": public, "v2": public},
    )

    token = _make_token(private, kid="v2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    assert middleware._refresh_attempted == 1


async def test_unknown_kid_under_cooldown_rejects() -> None:
    """W1-05 (c): refresh-helper returns False → 401 without retry."""
    private, public = _generate_rsa_pair()
    # No post_refresh_map → _refresh_jwks_if_allowed returns False.
    app, _ = _build_app(keys_by_kid={"v1": public})

    token = _make_token(private, kid="v9-unknown")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 401


# ── skip_verification path ────────────────────────────────────────────────────


async def test_skip_verification_bypasses_validation() -> None:
    """When skip_verification=True and no public key is loaded, decode is unverified."""
    private, _ = _generate_rsa_pair()
    # No public key seeded; skip_verification=True forces the unverified path.
    app, _ = _build_app(keys_by_kid={}, skip_verification=True)
    # _build_app seeds app.state._internal_jwt_public_key only if keys_by_kid is truthy.
    # An empty dict → no seed → dispatch falls through public_key=None branch.

    token = _make_token(private, kid="v1", tenant_id="tenant-skip")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "tenant-skip"


async def test_skip_verification_takes_precedence_path() -> None:
    """When skip_verification_takes_precedence=True, the skip path runs even if a key is loaded.

    market-data parity: a service that loaded a real RS256 public key should
    still accept HS256 dev tokens when this flag is set.
    """
    _, public = _generate_rsa_pair()
    app, _ = _build_app(
        keys_by_kid={"v1": public},
        skip_verification=True,
        skip_verification_takes_precedence=True,
    )

    # Sign with HS256 — would never validate against the RS256 public key.
    payload = {
        "sub": "u",
        "tenant_id": "t-precedence",
        "role": "user",
        "iss": "worldview-gateway",
        "aud": "worldview-internal",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, "dev-secret", algorithm="HS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "t-precedence"


# ── JTI replay protection ─────────────────────────────────────────────────────


async def test_jti_replay_enabled_blocks_second_use() -> None:
    """F-012: when Valkey SET NX returns False (key existed), reject with 401."""
    private, public = _generate_rsa_pair()
    app, middleware = _build_app(
        keys_by_kid={"v1": public},
        jti_replay_check_enabled=True,
        service_name="test-svc",
    )

    valkey = AsyncMock()
    valkey.set_nx = AsyncMock(return_value=False)  # simulate "already present"
    app.state.valkey = valkey

    token = _make_token(private, kid="v1", jti="replayed-jti-1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 401
    assert "replay" in resp.text.lower() or "invalid" in resp.text.lower()
    valkey.set_nx.assert_awaited_once()
    # service_name is NOT included by default — key is plain ``jti:{jti}``.
    args, _kwargs = valkey.set_nx.call_args
    assert args[0] == "jti:replayed-jti-1"
    # silence ref-unused warning
    _ = middleware


async def test_jti_replay_disabled_allows_repeat() -> None:
    """When jti_replay_check_enabled=False, the JTI check is skipped entirely."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(
        keys_by_kid={"v1": public},
        jti_replay_check_enabled=False,
    )

    valkey = AsyncMock()
    valkey.set_nx = AsyncMock(return_value=False)  # would block if called
    app.state.valkey = valkey

    token = _make_token(private, kid="v1", jti="repeated-jti")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    valkey.set_nx.assert_not_awaited()


async def test_jti_key_includes_service_name_when_flag_set() -> None:
    """When jti_key_includes_service_name=True, key is ``jti:{service}:{jti}``."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(
        keys_by_kid={"v1": public},
        jti_replay_check_enabled=True,
        service_name="svc-A",
        jti_key_includes_service_name=True,
    )

    valkey = AsyncMock()
    valkey.set_nx = AsyncMock(return_value=True)  # accept
    app.state.valkey = valkey

    token = _make_token(private, kid="v1", jti="abc")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    args, _kwargs = valkey.set_nx.call_args
    assert args[0] == "jti:svc-A:abc"


async def test_valkey_attr_can_be_overridden() -> None:
    """When ``valkey_attr="valkey_client"``, the middleware reads app.state.valkey_client."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(
        keys_by_kid={"v1": public},
        jti_replay_check_enabled=True,
        valkey_attr="valkey_client",
    )

    valkey = AsyncMock()
    valkey.set_nx = AsyncMock(return_value=True)
    app.state.valkey_client = valkey  # NOT app.state.valkey

    token = _make_token(private, kid="v1", jti="abc")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    valkey.set_nx.assert_awaited_once()


async def test_jti_check_fail_open_on_valkey_error() -> None:
    """F-012 fail-open: Valkey exception must NOT block requests (degraded mode)."""
    private, public = _generate_rsa_pair()
    app, _ = _build_app(
        keys_by_kid={"v1": public},
        jti_replay_check_enabled=True,
    )

    valkey = AsyncMock()
    valkey.set_nx = AsyncMock(side_effect=RuntimeError("connection refused"))
    app.state.valkey = valkey

    token = _make_token(private, kid="v1", jti="abc")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    # Fail-open: signature + expiry valid → request proceeds.
    assert resp.status_code == 200
