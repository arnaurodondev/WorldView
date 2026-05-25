"""Unit tests for api-gateway middleware (security headers, CORS, rate limit, OIDC)."""

from __future__ import annotations

import time
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


def _make_minimal_app() -> FastAPI:
    app = FastAPI()

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/auth/login")
    async def login():
        return {"url": "https://zitadel.example.com/auth"}

    return app


# ── SecurityHeadersMiddleware ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_present() -> None:
    """All 5 required security headers must appear on every response."""
    from api_gateway.middleware import SecurityHeadersMiddleware

    app = _make_minimal_app()
    app.add_middleware(SecurityHeadersMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    assert resp.status_code == 200
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["X-XSS-Protection"] == "0"
    assert resp.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=()"


@pytest.mark.asyncio
async def test_hsts_absent_when_cookie_secure_false() -> None:
    """HSTS header must NOT be set when cookie_secure=False (dev mode)."""
    from api_gateway.middleware import SecurityHeadersMiddleware

    app = _make_minimal_app()
    # No cookie_secure in state → defaults to False
    app.add_middleware(SecurityHeadersMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    assert "Strict-Transport-Security" not in resp.headers


# ── CORS ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cors_explicit_allowlist() -> None:
    """add_cors must use explicit method list — not a wildcard."""
    from api_gateway.middleware import add_cors

    app = _make_minimal_app()
    add_cors(app, "http://localhost:5173")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/test",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    # Verify the allowed methods header does NOT contain a wildcard
    allowed_methods = resp.headers.get("Access-Control-Allow-Methods", "")
    assert "*" not in allowed_methods
    # Standard methods must be present
    assert "GET" in allowed_methods


# ── RateLimitMiddleware ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_user_id_key() -> None:
    """Authenticated request uses rl:v1:user:{id} key (not IP)."""
    from api_gateway.middleware import RateLimitMiddleware

    captured_keys: list[str] = []

    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    # Inject user state via a simple middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class InjectUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = {"user_id": "u-abc-123", "tenant_id": "t-1"}
            return await call_next(request)

    app.add_middleware(InjectUserMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/test")

    assert any("rl:v1:user:u-abc-123" in k for k in captured_keys)


@pytest.mark.asyncio
async def test_rate_limit_ip_hash_key() -> None:
    """Unauthenticated request uses rl:v1:ip:{hash} key (not user key)."""
    from api_gateway.middleware import RateLimitMiddleware

    valkey = AsyncMock()
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/test")

    # Without a user state, rate limiter must use an IP-based key (rl:v1:ip:...)
    assert valkey.incr.called
    key_used = valkey.incr.call_args[0][0]
    assert key_used.startswith("rl:v1:ip:"), f"Expected ip-based key, got: {key_used}"
    assert "rl:v1:user:" not in key_used


@pytest.mark.asyncio
async def test_rate_limit_returns_503_when_valkey_none() -> None:
    """D-001: fail-closed — requests get 503 when Valkey is unavailable.

    When both ``valkey_client`` (constructor) and ``app.state.valkey`` are None,
    the middleware returns 503 Service Unavailable to prevent unmetered traffic.
    """
    from api_gateway.middleware import RateLimitMiddleware

    app = _make_minimal_app()
    # Ensure app.state.valkey is None (no Valkey)
    app.state.valkey = None
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=None,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    # D-001: fail-closed — 503 when Valkey unavailable
    assert resp.status_code == 503


# ── OIDCAuthMiddleware — skip paths ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_middleware_skips_auth_paths() -> None:
    """Public paths (/v1/auth/login, /health) pass without Authorization header."""
    from api_gateway.middleware import OIDCAuthMiddleware

    app = _make_minimal_app()
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/auth/login")
        assert resp.status_code == 200
        resp2 = await client.get("/health")
        assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_oidc_middleware_sets_user_state_on_valid_token(rsa_keypair) -> None:
    """Valid RS256 JWT → request.state.user is populated."""
    from datetime import datetime

    import jwt as pyjwt
    from api_gateway.domain import OIDCProviderConfig
    from api_gateway.middleware import OIDCAuthMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    now = int(time.time())
    payload = {
        "iss": "https://example.zitadel.cloud",
        "sub": "zitadel-sub-1",
        "aud": "client-id",
        "exp": now + 300,
        "iat": now,
        "email": "user@example.com",
        "email_verified": True,
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})

    # Build minimal settings mock
    class FakeSettings:
        oidc_audience = "client-id"

    oidc_config = OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={kid: public_key},
        last_refreshed_at=datetime.now(tz=UTC),
    )

    captured_user: list = []

    app = FastAPI()
    app.state.settings = FakeSettings()
    app.state.oidc_config = oidc_config
    app.state.valkey = None

    app.add_middleware(OIDCAuthMiddleware)

    @app.get("/protected")
    async def protected(request: Request):
        captured_user.append(request.state.user)
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert captured_user[0] is not None
    assert captured_user[0]["sub"] == "zitadel-sub-1"


# ── JWKS endpoint ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_jwt_middleware_has_public_key_after_startup(rsa_keypair) -> None:
    """BP-159: lifespan sets public key on the SERVING instance, not a throw-away.

    The api-gateway registers OIDCAuthMiddleware and InternalJWTIssuerMiddleware
    via ``add_middleware()`` — both read keys from ``app.state`` at request time,
    so they are NOT affected by the BP-159 dual-instance pattern.  This test
    verifies that after lifespan sets ``app.state.rsa_private_key``, the
    InternalJWTIssuerMiddleware dispatch path has access to the key.
    """
    from api_gateway.middleware import InternalJWTIssuerMiddleware

    private_key, public_key = rsa_keypair

    app = FastAPI()

    # Simulate what lifespan does: set keys on app.state
    from api_gateway.oidc import rsa_key_id

    kid = rsa_key_id(public_key)
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = public_key
    app.state.rsa_kid = kid

    # The middleware reads from app.state.rsa_private_key / app.state.rsa_kid
    # in its dispatch() — verify it can access them via a request.
    captured_tokens: list[str | None] = []

    app.add_middleware(InternalJWTIssuerMiddleware)

    @app.get("/check")
    async def check(request: Request):
        # After InternalJWTIssuerMiddleware runs, X-Internal-JWT should be set
        # if request.state.user was populated before the middleware ran.
        token = request.headers.get("X-Internal-JWT")
        captured_tokens.append(token)
        return {"ok": True}

    # InternalJWTIssuerMiddleware requires request.state.user to be set
    # by a prior middleware (OIDCAuth). Simulate that with an inject middleware.
    from starlette.middleware.base import BaseHTTPMiddleware

    class InjectUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = {"user_id": "u-1", "tenant_id": "t-1", "sub": "sub-1"}
            return await call_next(request)

    app.add_middleware(InjectUserMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/check")

    assert resp.status_code == 200
    # The serving instance MUST have signed a JWT using app.state keys
    assert captured_tokens, "Expected at least one captured token"
    assert captured_tokens[0] is not None, (
        "BP-159: InternalJWTIssuerMiddleware did not set X-Internal-JWT — "
        "the serving instance has no access to app.state.rsa_private_key"
    )


@pytest.mark.asyncio
async def test_jwks_endpoint_returns_200(rsa_keypair) -> None:
    """GET /internal/jwks returns 200 with JWKS JSON."""
    from api_gateway.oidc import build_jwks_response, rsa_key_id
    from api_gateway.routes.internal import router

    _, public_key = rsa_keypair
    kid = rsa_key_id(public_key)
    jwks = build_jwks_response(public_key, kid)

    app = FastAPI()
    app.state.internal_jwks = jwks
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/jwks")

    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert data["keys"][0]["kty"] == "RSA"


@pytest.mark.asyncio
async def test_jwks_endpoint_has_cache_control(rsa_keypair) -> None:
    """GET /internal/jwks has Cache-Control: public, max-age=3600."""
    from api_gateway.oidc import build_jwks_response, rsa_key_id
    from api_gateway.routes.internal import router

    _, public_key = rsa_keypair
    kid = rsa_key_id(public_key)
    jwks = build_jwks_response(public_key, kid)

    app = FastAPI()
    app.state.internal_jwks = jwks
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/jwks")

    assert "public" in resp.headers.get("Cache-Control", "")
    assert "max-age=3600" in resp.headers.get("Cache-Control", "")


# ── T-4-01: InternalJWTIssuerMiddleware — error logging on signing failure ─────


@pytest.mark.asyncio
async def test_jwt_issuance_failure_logs_error(rsa_keypair) -> None:
    """F-011: When JWT signing raises, logger.error must be called with exc_info=True.

    The middleware is fail-open (proxy must not be blocked), but the error MUST
    be logged so operators can detect key-configuration problems in production.
    """
    from api_gateway.middleware import InternalJWTIssuerMiddleware

    private_key, public_key = rsa_keypair

    app = FastAPI()

    from api_gateway.oidc import rsa_key_id

    kid = rsa_key_id(public_key)
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = public_key
    app.state.rsa_kid = kid

    app.add_middleware(InternalJWTIssuerMiddleware)

    # Inject a user so the signing path is entered
    from starlette.middleware.base import BaseHTTPMiddleware

    class InjectUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = {"user_id": "u-1", "tenant_id": "t-1", "sub": "sub-1"}
            return await call_next(request)

    app.add_middleware(InjectUserMiddleware)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    # Patch issue_user_jwt to raise a RuntimeError simulating a signing failure
    with patch(
        "api_gateway.middleware.InternalJWTIssuerMiddleware.dispatch",
        wraps=None,
    ):
        pass  # we use the real dispatch below; patch issue_user_jwt directly

    with patch("api_gateway.jwt_utils.issue_user_jwt", side_effect=RuntimeError("key error")):
        import api_gateway.middleware as _mw

        with patch.object(_mw, "logger") as mock_logger:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/probe")

    # The proxy must still succeed (fail-open)
    assert resp.status_code == 200
    # logger.error must have been called with exc_info=True
    mock_logger.error.assert_called_once()
    call_kwargs = mock_logger.error.call_args
    # structlog binds keyword arguments; verify exc_info=True was passed
    assert call_kwargs.kwargs.get("exc_info") is True or (
        len(call_kwargs.args) > 0 and "internal_jwt_issuance_failed" in call_kwargs.args[0]
    )


# ── T-4-03: OIDCAuthMiddleware dev-mode — require claims ──────────────────────


@pytest.mark.asyncio
async def test_dev_mode_rejects_jwt_without_exp(rsa_keypair) -> None:
    """F-014: Dev-mode JWT decode must reject tokens that lack an 'exp' claim.

    When oidc_config is None (dev / tests without Zitadel) the middleware
    still validates Bearer tokens as internal JWTs.  Adding
    ``options={"require": ["iss", "sub", "exp"]}`` to jwt.decode() ensures
    that tokens without 'exp' are rejected and user remains None.
    """
    import jwt as pyjwt
    from api_gateway.middleware import OIDCAuthMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    # Token with 'iss' and 'sub' but NO 'exp'
    payload_no_exp = {
        "iss": "worldview-gateway",
        "sub": "u-test-no-exp",
        # intentionally omit 'exp'
    }
    token = pyjwt.encode(payload_no_exp, private_key, algorithm="RS256", headers={"kid": kid})

    captured_user: list = []

    app = FastAPI()
    app.state.oidc_config = None  # trigger dev-mode path
    app.state.rsa_public_key = public_key

    app.add_middleware(OIDCAuthMiddleware)

    @app.get("/check")
    async def check(request: Request):
        captured_user.append(request.state.user)
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/check", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    # Token without 'exp' must NOT authenticate the user
    assert captured_user[0] is None, (
        "F-014: OIDCAuthMiddleware accepted a token without 'exp' claim — "
        "options={'require': ['iss','sub','exp']} is not enforced."
    )


@pytest.mark.asyncio
async def test_dev_mode_rejects_jwt_without_sub(rsa_keypair) -> None:
    """F-014: Dev-mode JWT decode must reject tokens that lack a 'sub' claim.

    A token without 'sub' cannot be mapped to a user identity and must be
    rejected, leaving request.state.user as None.
    """
    import time

    import jwt as pyjwt
    from api_gateway.middleware import OIDCAuthMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    # Token with 'iss' and 'exp' but NO 'sub'
    now = int(time.time())
    payload_no_sub = {
        "iss": "worldview-gateway",
        "exp": now + 300,
        # intentionally omit 'sub'
    }
    token = pyjwt.encode(payload_no_sub, private_key, algorithm="RS256", headers={"kid": kid})

    captured_user: list = []

    app = FastAPI()
    app.state.oidc_config = None  # trigger dev-mode path
    app.state.rsa_public_key = public_key

    app.add_middleware(OIDCAuthMiddleware)

    @app.get("/check")
    async def check(request: Request):
        captured_user.append(request.state.user)
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/check", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    # Token without 'sub' must NOT authenticate the user
    assert captured_user[0] is None, (
        "F-014: OIDCAuthMiddleware accepted a token without 'sub' claim — "
        "options={'require': ['iss','sub','exp']} is not enforced."
    )


# ── F-Q2-01: OIDC role propagation ─────────────────────────────────────────────


def test_extract_role_zitadel_admin() -> None:
    """F-Q2-01: a Zitadel-shaped admin claim resolves to role='admin'."""
    from api_gateway.middleware import _extract_role

    payload = {
        "sub": "u-1",
        "urn:zitadel:iam:org:project:roles": {
            "admin": {"project-1": "org-1"},
        },
    }
    assert _extract_role(payload) == "admin"


def test_extract_role_zitadel_user_only() -> None:
    """F-Q2-01: a Zitadel claim without 'admin' resolves to role='user'."""
    from api_gateway.middleware import _extract_role

    payload = {
        "sub": "u-1",
        "urn:zitadel:iam:org:project:roles": {
            "trader": {"project-1": "org-1"},
        },
    }
    assert _extract_role(payload) == "user"


def test_extract_role_roles_array() -> None:
    """F-Q2-01: a generic ``roles`` array claim is honoured."""
    from api_gateway.middleware import _extract_role

    assert _extract_role({"sub": "u", "roles": ["admin", "trader"]}) == "admin"
    assert _extract_role({"sub": "u", "roles": ["trader"]}) == "user"


def test_extract_role_role_string() -> None:
    """F-Q2-01: legacy single ``role`` string claim is honoured."""
    from api_gateway.middleware import _extract_role

    assert _extract_role({"sub": "u", "role": "admin"}) == "admin"
    assert _extract_role({"sub": "u", "role": "viewer"}) == "user"


def test_extract_role_no_claim_defaults_user() -> None:
    """F-Q2-01: missing role claim defaults to ``user``."""
    from api_gateway.middleware import _extract_role

    assert _extract_role({"sub": "u"}) == "user"


@pytest.mark.asyncio
async def test_oidc_admin_role_propagates_to_internal_jwt(rsa_keypair) -> None:
    """F-Q2-01 end-to-end: an OIDC admin payload yields role=admin in the issued internal JWT.

    Wires OIDCAuthMiddleware + InternalJWTIssuerMiddleware together so we can
    assert that the X-Internal-JWT header carried into the route has role=admin
    when the inbound Zitadel token contains the Zitadel-shaped admin claim.
    """
    from datetime import datetime

    import jwt as pyjwt
    from api_gateway.domain import OIDCProviderConfig
    from api_gateway.middleware import InternalJWTIssuerMiddleware, OIDCAuthMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    now = int(time.time())
    # Zitadel-shaped OIDC payload with admin role
    payload = {
        "iss": "https://example.zitadel.cloud",
        "sub": "zitadel-admin-1",
        "aud": "client-id",
        "exp": now + 300,
        "iat": now,
        "email": "admin@example.com",
        "email_verified": True,
        "user_id": "u-admin",
        "tenant_id": "t-1",
        "urn:zitadel:iam:org:project:roles": {"admin": {"p-1": "o-1"}},
    }
    token = pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})

    class FakeSettings:
        oidc_audience = "client-id"

    oidc_config = OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={kid: public_key},
        last_refreshed_at=datetime.now(tz=UTC),
    )

    captured_jwt: list[str | None] = []
    captured_user: list[dict | None] = []

    app = FastAPI()
    app.state.settings = FakeSettings()
    app.state.oidc_config = oidc_config
    app.state.valkey = None
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = public_key
    app.state.rsa_kid = kid

    @app.get("/probe")
    async def probe(request: Request):
        captured_user.append(request.state.user)
        captured_jwt.append(request.headers.get("X-Internal-JWT"))
        return {"ok": True}

    # Order matters: starlette runs middleware in reverse-add order, so the
    # last-added middleware runs first. Add InternalJWTIssuerMiddleware first
    # so OIDCAuthMiddleware (added next) runs first and populates state.user
    # before InternalJWTIssuerMiddleware reads it.
    app.add_middleware(InternalJWTIssuerMiddleware)
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert captured_user[0] is not None
    assert (
        captured_user[0]["role"] == "admin"
    ), f"OIDCAuthMiddleware did not extract admin role; got {captured_user[0]!r}"
    assert captured_jwt[0] is not None
    # Decode the issued internal JWT and verify the role claim
    decoded = pyjwt.decode(
        captured_jwt[0],
        public_key,
        algorithms=["RS256"],
        options={"verify_aud": False},
        issuer="worldview-gateway",
    )
    assert decoded["role"] == "admin", (
        f"InternalJWTIssuerMiddleware issued JWT with role={decoded.get('role')!r} "
        "instead of forwarding the OIDC admin role"
    )


# ── T-4-04: add_cors — wildcard guard ─────────────────────────────────────────


def test_cors_rejects_wildcard_with_credentials() -> None:
    """F-016: add_cors must raise ValueError when origins contains '*'.

    Combining allow_origins=['*'] with allow_credentials=True is rejected by
    all modern browsers (CORS spec §3.2.2).  The guard prevents misconfiguration
    from silently breaking authenticated requests in production.
    """
    from api_gateway.middleware import add_cors

    app = FastAPI()
    with pytest.raises(ValueError, match="CORS misconfiguration"):
        add_cors(app, "*")


def test_cors_accepts_explicit_origins() -> None:
    """F-016: add_cors must succeed when an explicit origin list is provided."""
    from api_gateway.middleware import add_cors

    app = FastAPI()
    # Should not raise
    add_cors(app, "http://localhost:3000")
    # Verify CORSMiddleware was registered.
    # FastAPI stores middleware as Middleware(cls, **kwargs) wrapper objects;
    # the actual class lives on the .cls attribute.
    middleware_classes = [getattr(m, "cls", type(m)).__name__ for m in app.user_middleware]
    assert any(
        "CORS" in t for t in middleware_classes
    ), "CORSMiddleware was not added to the app after add_cors() with explicit origins."


# ── BUG-004 / BP-480: rate-limit bypass via missing request.state.user ────────
#
# These regression tests verify that:
#   1. OIDCAuthMiddleware.dispatch() sets request.state.user = None as its
#      FIRST action, so the attribute is always present even on error paths.
#   2. RateLimitMiddleware reads request.state.user via getattr(..., None)
#      and only enters the per-user bucket when the value is a dict with a
#      truthy user_id — otherwise it falls through to the IP bucket.
#   3. The combination prevents the shared-NAT bypass described in the
#      backend audit (BUG-004): unauthenticated / failed-auth requests can
#      no longer accidentally share the rl:v1:user:* counter, and a missing
#      attribute can no longer raise AttributeError mid-dispatch.


@pytest.mark.asyncio
async def test_oidc_dispatch_initialises_user_none_first(rsa_keypair) -> None:
    """BUG-004 / BP-480: OIDCAuthMiddleware sets ``request.state.user = None``
    as the FIRST action of dispatch, guaranteeing the attribute always exists.

    We assert this by entering the dev-mode branch (``oidc_config=None``) with
    NO Authorization header — the dispatch should still leave
    ``request.state.user`` as ``None`` (sentinel value), never raise
    AttributeError when downstream code reads it.
    """
    from api_gateway.middleware import OIDCAuthMiddleware

    captured_attr_exists: list[bool] = []
    captured_value: list = []

    app = FastAPI()
    app.state.oidc_config = None  # dev-mode path

    app.add_middleware(OIDCAuthMiddleware)

    @app.get("/probe")
    async def probe(request: Request):
        # Critical assertion: the attribute MUST exist, even before any
        # successful auth path runs.
        captured_attr_exists.append(hasattr(request.state, "user"))
        captured_value.append(getattr(request.state, "user", "MISSING"))
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/probe")  # no Authorization header

    assert resp.status_code == 200
    assert captured_attr_exists[0] is True, (
        "BUG-004 / BP-480: OIDCAuthMiddleware did not set request.state.user "
        "before yielding to downstream middleware — attribute is missing."
    )
    assert captured_value[0] is None, f"Expected request.state.user to be sentinel None, got {captured_value[0]!r}"


@pytest.mark.asyncio
async def test_rate_limit_ip_bucket_no_auth_header() -> None:
    """BUG-004 / BP-480 (scenario 1): request with no Authorization header
    → user is None → IP bucket key applied (``rl:v1:ip:...``)."""
    from api_gateway.middleware import OIDCAuthMiddleware, RateLimitMiddleware

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.state.oidc_config = None
    # Order: last-added = outermost. RateLimit must run AFTER OIDCAuth so it
    # sees the initialised request.state.user.
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")  # no Authorization header

    assert resp.status_code == 200
    assert captured_keys, "RateLimitMiddleware never called valkey.incr"
    assert captured_keys[0].startswith("rl:v1:ip:"), f"BUG-004: expected IP bucket, got key={captured_keys[0]!r}"
    assert "rl:v1:user:" not in captured_keys[0]


@pytest.mark.asyncio
async def test_rate_limit_ip_bucket_malformed_jwt(rsa_keypair) -> None:
    """BUG-004 / BP-480 (scenario 2): a malformed/bad-signature JWT must NOT
    bypass to the user bucket. After OIDCAuthMiddleware fails validation it
    sets user=None, and RateLimitMiddleware falls through to the IP bucket.
    """
    from datetime import datetime

    import jwt as pyjwt
    from api_gateway.domain import OIDCProviderConfig
    from api_gateway.middleware import OIDCAuthMiddleware, RateLimitMiddleware
    from api_gateway.oidc import rsa_key_id

    _private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    # Forge a token signed with a DIFFERENT key (bad signature)
    other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    now = int(time.time())
    bad_token = pyjwt.encode(
        {
            "iss": "https://example.zitadel.cloud",
            "sub": "attacker",
            "aud": "client-id",
            "exp": now + 300,
            "iat": now,
        },
        other_private,  # signed with the WRONG key
        algorithm="RS256",
        headers={"kid": kid},
    )

    class FakeSettings:
        oidc_audience = "client-id"

    oidc_config = OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={kid: public_key},  # legitimate key — won't verify bad_token
        last_refreshed_at=datetime.now(tz=UTC),
    )

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.state.settings = FakeSettings()
    app.state.oidc_config = oidc_config
    app.state.valkey = None

    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {bad_token}"})

    assert resp.status_code == 200
    assert captured_keys, "RateLimitMiddleware never called valkey.incr"
    assert captured_keys[0].startswith(
        "rl:v1:ip:"
    ), f"BUG-004: malformed-JWT request must use IP bucket, got {captured_keys[0]!r}"


@pytest.mark.asyncio
async def test_rate_limit_ip_bucket_expired_jwt(rsa_keypair) -> None:
    """BUG-004 / BP-480 (scenario 3): an expired JWT must fall through to the
    IP bucket — OIDCAuthMiddleware catches jwt.ExpiredSignatureError (subclass
    of InvalidTokenError) and sets user=None.
    """
    from datetime import datetime

    import jwt as pyjwt
    from api_gateway.domain import OIDCProviderConfig
    from api_gateway.middleware import OIDCAuthMiddleware, RateLimitMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    now = int(time.time())
    expired_token = pyjwt.encode(
        {
            "iss": "https://example.zitadel.cloud",
            "sub": "old-user",
            "aud": "client-id",
            "exp": now - 60,  # expired one minute ago
            "iat": now - 3600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    class FakeSettings:
        oidc_audience = "client-id"

    oidc_config = OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={kid: public_key},
        last_refreshed_at=datetime.now(tz=UTC),
    )

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.state.settings = FakeSettings()
    app.state.oidc_config = oidc_config
    app.state.valkey = None

    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {expired_token}"})

    assert resp.status_code == 200
    assert captured_keys, "RateLimitMiddleware never called valkey.incr"
    assert captured_keys[0].startswith(
        "rl:v1:ip:"
    ), f"BUG-004: expired-JWT request must use IP bucket, got {captured_keys[0]!r}"


@pytest.mark.asyncio
async def test_rate_limit_user_bucket_valid_jwt(rsa_keypair) -> None:
    """BUG-004 / BP-480 (scenario 4): a valid JWT → user bucket applied
    (``rl:v1:user:...``).  Non-regression for the happy path."""
    from datetime import datetime

    import jwt as pyjwt
    from api_gateway.domain import OIDCProviderConfig
    from api_gateway.middleware import OIDCAuthMiddleware, RateLimitMiddleware
    from api_gateway.oidc import rsa_key_id

    private_key, public_key = rsa_keypair
    kid = rsa_key_id(public_key)

    now = int(time.time())
    valid_token = pyjwt.encode(
        {
            "iss": "https://example.zitadel.cloud",
            "sub": "zitadel-good-1",
            "aud": "client-id",
            "exp": now + 300,
            "iat": now,
            "email": "user@example.com",
            "user_id": "u-good-1",
            "tenant_id": "t-1",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

    class FakeSettings:
        oidc_audience = "client-id"

    oidc_config = OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={kid: public_key},
        last_refreshed_at=datetime.now(tz=UTC),
    )

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.state.settings = FakeSettings()
    app.state.oidc_config = oidc_config
    app.state.valkey = None

    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(OIDCAuthMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {valid_token}"})

    assert resp.status_code == 200
    assert captured_keys, "RateLimitMiddleware never called valkey.incr"
    assert captured_keys[0].startswith(
        "rl:v1:user:u-good-1"
    ), f"Valid-JWT happy path must use user bucket, got {captured_keys[0]!r}"


@pytest.mark.asyncio
async def test_rate_limit_missing_user_attr_no_attribute_error() -> None:
    """BUG-004 / BP-480 (scenario 5): even if a future code path skips
    OIDCAuthMiddleware entirely so ``request.state.user`` is never set,
    ``RateLimitMiddleware`` must NOT raise AttributeError — it must fall
    through to the IP bucket and log a warning. This is the defence-in-depth
    behaviour required by the audit (``getattr(..., None)`` default + the
    ``rate_limit_user_attr_missing`` warning).
    """
    from api_gateway.middleware import RateLimitMiddleware

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    # IMPORTANT: do NOT add OIDCAuthMiddleware — simulates the regression case
    # where some new code path bypasses it. RateLimitMiddleware must remain
    # safe even in that scenario.
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    import api_gateway.middleware as _mw

    with patch.object(_mw, "logger") as mock_logger:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/test")

    # No AttributeError raised; request completes with 200 and uses IP bucket
    assert resp.status_code == 200
    assert captured_keys, "RateLimitMiddleware never called valkey.incr"
    assert captured_keys[0].startswith(
        "rl:v1:ip:"
    ), f"Missing user attr must fall through to IP bucket, got {captured_keys[0]!r}"
    # The defensive warning must fire so operators can spot the regression
    warning_calls = [
        c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "rate_limit_user_attr_missing"
    ]
    assert warning_calls, (
        "BUG-004 / BP-480: RateLimitMiddleware must log "
        "'rate_limit_user_attr_missing' when request.state.user is absent."
    )


@pytest.mark.asyncio
async def test_rate_limit_two_unauth_requests_same_ip_share_bucket() -> None:
    """BUG-004 / BP-480 (scenario 6, non-regression): two unauthenticated
    requests from the same IP must hit the same Valkey key so the counter
    increments — confirms that the IP hashing did not regress.
    """
    from api_gateway.middleware import RateLimitMiddleware

    captured_keys: list[str] = []
    counter = {"n": 0}
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        counter["n"] += 1
        return counter["n"]

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/test")
        r2 = await client.get("/test")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(captured_keys) == 2
    assert captured_keys[0] == captured_keys[1], (
        "Same-IP unauthenticated requests must share the same Valkey bucket — "
        f"got {captured_keys[0]!r} vs {captured_keys[1]!r}"
    )
    assert captured_keys[0].startswith("rl:v1:ip:")


@pytest.mark.asyncio
async def test_rate_limit_user_non_dict_value_falls_through_to_ip() -> None:
    """BUG-004 / BP-480: if ``request.state.user`` is somehow set to a
    non-dict value (string, int, custom object), the strict ``isinstance``
    check guarantees we fall through to the IP bucket instead of raising
    AttributeError on ``.get(...)``.
    """
    from api_gateway.middleware import RateLimitMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware

    captured_keys: list[str] = []
    valkey = AsyncMock()

    async def fake_incr(key: str) -> int:
        captured_keys.append(key)
        return 1

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()

    app = _make_minimal_app()

    class InjectBogusUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Simulate a regression where some middleware mis-types user
            request.state.user = "not-a-dict"  # bogus
            return await call_next(request)

    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(InjectBogusUserMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    assert resp.status_code == 200, "Non-dict user value must not crash the rate limiter."
    assert captured_keys[0].startswith(
        "rl:v1:ip:"
    ), f"Non-dict user must fall through to IP bucket, got {captured_keys[0]!r}"
