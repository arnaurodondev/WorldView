"""Unit tests for api-gateway middleware (security headers, CORS, rate limit, OIDC)."""

from __future__ import annotations

import time
from datetime import UTC
from unittest.mock import AsyncMock

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
    assert resp.headers["Permissions-Policy"] == "geolocation=(), microphone=()"


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
    app.add_middleware(RateLimitMiddleware, valkey_client=valkey, max_requests=100)
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
    app.add_middleware(RateLimitMiddleware, valkey_client=valkey, max_requests=100)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/test")

    # Without a user state, rate limiter must use an IP-based key (rl:v1:ip:...)
    assert valkey.incr.called
    key_used = valkey.incr.call_args[0][0]
    assert key_used.startswith("rl:v1:ip:"), f"Expected ip-based key, got: {key_used}"
    assert "rl:v1:user:" not in key_used


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
