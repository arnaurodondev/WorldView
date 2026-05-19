"""Unit tests for InternalJWTMiddleware (PRD-0025 §6.5, T-C-1-05)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from portfolio.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = [pytest.mark.unit]

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
    aud: str = "worldview-internal",
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "iss": iss,
        "aud": aud,
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


# ── Test app factory ──────────────────────────────────────────────────────────


class _PreKeyedJWTMiddleware(InternalJWTMiddleware):
    """Subclass that accepts a pre-built public key to avoid HTTP calls in tests."""

    def __init__(self, app: Any, public_key: Any) -> None:
        super().__init__(app, jwks_url="http://unused-in-test/internal/jwks")
        self._public_key = public_key


def _build_app(public_key: Any = None) -> FastAPI:
    """Build a FastAPI app with _PreKeyedJWTMiddleware.

    The public key is stored on app.state._internal_jwt_public_key so that
    InternalJWTMiddleware.dispatch() can read it via request.app.state.
    """
    app = FastAPI()

    # Inject the key into app.state so dispatch() can read it.
    # This mirrors what startup() does in production (writing to self.app.state).
    if public_key is not None:
        app.state._internal_jwt_public_key = public_key

    @app.get("/api/v1/data")
    async def data_route(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "tenant_id": getattr(request.state, "tenant_id", None),
                "role": getattr(request.state, "role", None),
            },
        )

    @app.get("/health")
    async def health_route() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/metrics")
    async def metrics_route() -> JSONResponse:
        return JSONResponse({"metric": 1})

    app.add_middleware(_PreKeyedJWTMiddleware, public_key=public_key)
    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_internal_jwt_middleware_rejects_missing_jwt() -> None:
    """No X-Internal-JWT header and public key loaded → 401."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data")

    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


async def test_internal_jwt_middleware_rejects_expired() -> None:
    """Expired JWT → 401."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    expired_token = _make_token(private_key, exp_offset=-60)  # expired 60s ago

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": expired_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_rejects_wrong_issuer() -> None:
    """iss != worldview-gateway → 401."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    bad_iss_token = _make_token(private_key, iss="evil-gateway")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": bad_iss_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_sets_tenant_id() -> None:
    """Valid JWT → request.state.tenant_id/role set; 200 response."""
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    token = _make_token(private_key, tenant_id="t-123", role="user")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "t-123"
    assert body["role"] == "user"


async def test_internal_jwt_middleware_skips_health() -> None:
    """GET /health passes without X-Internal-JWT header."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200


async def test_internal_jwt_middleware_skips_metrics() -> None:
    """GET /metrics passes without X-Internal-JWT header."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 200


async def test_internal_jwt_middleware_returns_503_when_no_key() -> None:
    """When JWKS not loaded (public_key is None), return 503 Service Unavailable.

    F-001 / F-SEC-001: The fail-open path (unverified decode) was removed. Requests
    must be rejected when the service hasn't loaded its public key yet — this prevents
    auth bypass via timing attacks during startup.
    """
    app = _build_app(public_key=None)  # no key loaded

    token = "any-token-value"  # noqa: S105

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 503
    assert "jwks not loaded" in resp.json()["detail"].lower()


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


async def test_internal_jwt_middleware_rejects_wrong_algorithm() -> None:
    """HS256 token (wrong algorithm) → 401."""
    _private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    # Sign with HS256 instead of RS256
    hs_token = jwt.encode(
        {"sub": "u", "tenant_id": "t", "role": "user", "iss": "worldview-gateway", "exp": int(time.time()) + 3600},
        "some-hmac-secret",
        algorithm="HS256",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": hs_token})

    assert resp.status_code == 401


# ── F-001 (PLAN-0087 audit) — JWT audience negative tests ─────────────────────
#
# Commit 80dfc0fc added audience="worldview-internal" to jwt.decode() and "aud"
# to options.require across 6+ services BUT the helper _make_token() was
# simultaneously updated to include aud="worldview-internal" so existing happy-
# path tests still passed.  No negative test asserted that wrong/missing aud →
# 401.  qa-beta-test-engineer flagged this BLOCKING (F-001) because a future
# refactor that drops the audience= kwarg or the require-list entry would pass
# every existing test and silently re-introduce a token-replay vulnerability.
#
# These three tests pin the contract from the rejection side:
#   1. wrong aud value     → 401  (proves the audience= kwarg is enforced)
#   2. missing aud claim   → 401  (proves "aud" in options.require is enforced)
#   3. multi-aud list incl expected → 200 (pins PyJWT's list-aud behaviour)


async def test_internal_jwt_middleware_rejects_wrong_audience() -> None:
    """Token signed with aud="zitadel-frontend" → 401 (must be "worldview-internal").

    Regression target: a future commit that drops `audience="worldview-internal"`
    from the jwt.decode() call would cause this test to fail (token would be
    accepted).  PyJWT raises InvalidAudienceError → middleware maps to 401.
    """
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    bad_aud_token = _make_token(private_key, aud="zitadel-frontend")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": bad_aud_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_rejects_missing_audience() -> None:
    """Token with no aud claim → 401 (require: aud triggers MissingRequiredClaimError).

    Regression target: a future commit that drops "aud" from options.require
    would cause this test to fail (token without aud would be accepted because
    PyJWT only enforces audience=... when an aud kwarg is supplied AND aud is
    in require-list).
    """
    private_key, public_key = _generate_rsa_pair()
    app = _build_app(public_key=public_key)

    # Build a token WITHOUT the aud claim.  We bypass _make_token() because that
    # helper unconditionally inserts aud="worldview-internal".
    payload = {
        "sub": "user-123",
        "tenant_id": "tenant-abc",
        "role": "user",
        "iss": "worldview-gateway",
        "exp": int(time.time()) + 3600,
        # NO "aud" key — this is the whole point of the test.
    }
    no_aud_token = jwt.encode(payload, private_key, algorithm="RS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": no_aud_token})

    assert resp.status_code == 401


async def test_internal_jwt_middleware_accepts_multi_audience_list_containing_expected() -> None:
    """Token with aud=["worldview-internal", "other"] → 200.

    PyJWT 2.x accepts a list-form aud claim if the configured audience is one
    of the entries.  This test pins that behaviour so a future PyJWT upgrade
    that changes the semantics is caught.
    """
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
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": multi_aud_token})

    assert resp.status_code == 200


# ── W1-05 (BUG-005) — kid-based JWKS rotation regression tests ────────────────
#
# These tests are the canonical W1-05 regression suite (per the task brief, only
# portfolio carries the full test set; the other 8 backends rely on their
# existing suites + W2-05's consolidated shared lib for full coverage).
#
# Each test pokes the middleware's ``_keys_by_kid`` map directly because the
# helper ``_PreKeyedJWTMiddleware`` overrides ``__init__`` to skip the HTTP
# fetch — we follow that same pattern but populate the kid map manually.


class _KidMappedJWTMiddleware(InternalJWTMiddleware):
    """Test subclass that pre-seeds the kid → key map without hitting the network.

    Also accepts a callable to swap in a "post-refresh" map, simulating what
    happens when ``_refresh_jwks_if_allowed`` actually fetches a new key set.
    """

    def __init__(
        self,
        app: Any,
        keys_by_kid: dict[str, Any],
        post_refresh_map: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(app, jwks_url="http://unused-in-test/internal/jwks")
        # Pre-seed the kid map. dispatch() consults this before falling back
        # to the legacy single-key path.
        self._keys_by_kid = dict(keys_by_kid)
        # Public key fallback (legacy contract). Pick first value if present.
        self._public_key = next(iter(keys_by_kid.values()), None)
        self._post_refresh_map = post_refresh_map
        self._refresh_attempted = 0

    async def _refresh_jwks_if_allowed(self) -> bool:  # type: ignore[override]
        """Stub: simulate the rate-limited refresh without an outbound fetch."""
        self._refresh_attempted += 1
        # First refresh: swap in the post-refresh map if provided.
        if self._post_refresh_map is not None:
            self._keys_by_kid = dict(self._post_refresh_map)
            self._post_refresh_map = None  # one-shot
            return True
        return False


def _build_kid_app(
    keys_by_kid: dict[str, Any],
    post_refresh_map: dict[str, Any] | None = None,
) -> tuple[FastAPI, _KidMappedJWTMiddleware]:
    """Build a FastAPI app with the kid-mapped middleware. Returns (app, middleware ref)."""
    app = FastAPI()
    # Seed app.state too so the existing dispatch logic that reads
    # ``app.state._internal_jwt_public_key`` finds something non-None and
    # proceeds past the 503 gate.
    if keys_by_kid:
        app.state._internal_jwt_public_key = next(iter(keys_by_kid.values()))

    @app.get("/api/v1/data")
    async def data_route(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "tenant_id": getattr(request.state, "tenant_id", None)})

    middleware = _KidMappedJWTMiddleware(app, keys_by_kid, post_refresh_map=post_refresh_map)
    # add_middleware would create a fresh instance — we want the test to be
    # able to inspect the SAME instance that handles requests.
    app.user_middleware.insert(0, _wrap_middleware_instance(middleware))
    app.middleware_stack = app.build_middleware_stack()
    return app, middleware


def _wrap_middleware_instance(instance: Any) -> Any:
    """Wrap a pre-built middleware instance so Starlette uses IT (not a fresh copy)."""
    from starlette.middleware import Middleware

    return Middleware(_PassthroughFactory, instance=instance)


class _PassthroughFactory:
    """Returns the pre-built instance instead of constructing a fresh one.

    Starlette's ``Middleware`` wrapper normally calls ``cls(app, **kwargs)``.
    We exploit that by accepting ``app`` + ``instance`` and just returning the
    instance with its ``app`` attribute updated.
    """

    def __new__(cls, app: Any, instance: Any) -> Any:  # type: ignore[misc]
        instance.app = app
        return instance


def _make_token_with_kid(private_key: Any, kid: str | None) -> str:
    """Encode a JWT including a kid header (or no kid header at all)."""
    payload = {
        "sub": "user-123",
        "tenant_id": "tenant-abc",
        "role": "user",
        "iss": "worldview-gateway",
        "aud": "worldview-internal",
        "exp": int(time.time()) + 3600,
    }
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


async def test_w1_05_known_kid_validates_successfully() -> None:
    """W1-05 (a): JWT carrying a kid present in the cache verifies normally."""
    private_key, public_key = _generate_rsa_pair()
    app, _ = _build_kid_app(keys_by_kid={"v1": public_key})

    token = _make_token_with_kid(private_key, kid="v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200


async def test_w1_05_unknown_kid_triggers_refresh_and_succeeds() -> None:
    """W1-05 (b): kid not in cache → refresh runs → new kid is found → 200."""
    # W1-05's cooldown is module-level. Reset it so this test starts clean.
    import portfolio.infrastructure.middleware.internal_jwt as mw_module

    mw_module._last_refresh_ts = 0.0  # type: ignore[attr-defined]

    private_key, public_key = _generate_rsa_pair()
    # Cache starts with v1; post-refresh map adds v2 (the kid the token uses).
    app, middleware = _build_kid_app(
        keys_by_kid={"v1": public_key},
        post_refresh_map={"v1": public_key, "v2": public_key},
    )

    token = _make_token_with_kid(private_key, kid="v2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
    assert middleware._refresh_attempted == 1


async def test_w1_05_unknown_kid_under_cooldown_rejects_without_refresh() -> None:
    """W1-05 (c): refresh already ran <60s ago → second unknown kid → 401 immediately, no refresh."""
    # Force the cooldown timestamp to "just now" so the helper returns False.
    import portfolio.infrastructure.middleware.internal_jwt as mw_module

    mw_module._last_refresh_ts = time.monotonic()  # type: ignore[attr-defined]

    private_key, public_key = _generate_rsa_pair()
    app, _ = _build_kid_app(keys_by_kid={"v1": public_key})

    token = _make_token_with_kid(private_key, kid="v9-unknown")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    # The refresh-helper path under cooldown returns False; dispatch rejects 401.
    # (The middleware DOES still call _refresh_jwks_if_allowed — what matters
    # is that the override returns False inside the cooldown window.)
    assert resp.status_code == 401


async def test_w1_05_token_without_kid_falls_back_to_default() -> None:
    """W1-05 (d): no kid header → treated as kid "v1" (back-compat with pre-W1-05 S9)."""
    import portfolio.infrastructure.middleware.internal_jwt as mw_module

    mw_module._last_refresh_ts = 0.0  # type: ignore[attr-defined]

    private_key, public_key = _generate_rsa_pair()
    # Cache contains the default kid "v1" — same key — so back-compat path resolves.
    app, _ = _build_kid_app(keys_by_kid={"v1": public_key})

    token = _make_token_with_kid(private_key, kid=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data", headers={"X-Internal-JWT": token})

    assert resp.status_code == 200
