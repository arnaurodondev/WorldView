"""Unit tests for auth routes (api_gateway.routes.auth)."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_oidc_config():
    """Build a minimal OIDCProviderConfig for testing."""
    from datetime import datetime

    from api_gateway.domain import OIDCProviderConfig

    return OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={},
        last_refreshed_at=datetime.now(tz=UTC),
    )


def _make_mock_valkey(getdel_result: str | None = None) -> MagicMock:
    """Build a mock ValkeyClient with a configurable atomic getdel result."""
    valkey = MagicMock()
    valkey.set = AsyncMock()
    valkey.get = AsyncMock(return_value=None)
    valkey.delete = AsyncMock(return_value=0)
    # Atomic GETDEL: returns stored value (or None if key absent) and deletes it.
    valkey.getdel = AsyncMock(return_value=getdel_result)

    return valkey


def _make_auth_app(
    valkey: Any = None,
    oidc_config: Any = None,
    httpx_client: Any = None,
):
    """Build a FastAPI test app with pre-configured auth state."""
    from api_gateway.app import create_app
    from api_gateway.clients import ServiceClients
    from api_gateway.config import Settings
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    settings = Settings(  # type: ignore[call-arg]
        valkey_url="redis://localhost:6379/0",
        oidc_issuer_url="https://example.zitadel.cloud",
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        oidc_audience="test-client-id",
        internal_jwt_private_key=private_pem,
        internal_jwt_public_key=public_pem,
        cors_origins="http://localhost:3000",
        frontend_url="http://localhost:5173",
        cookie_secure=False,
        portfolio_url="http://s1:8001",
    )

    app = create_app(settings)
    app.state.clients = ServiceClients(**{f.name: MagicMock(spec=httpx.AsyncClient) for f in fields(ServiceClients)})
    app.state.valkey = valkey
    app.state.oidc_config = oidc_config or _make_oidc_config()
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = private_key.public_key()
    from api_gateway.oidc import rsa_key_id

    app.state.rsa_kid = rsa_key_id(private_key.public_key())
    app.state.internal_jwks = None

    if httpx_client is not None:
        app.state.httpx_client = httpx_client
    else:
        app.state.httpx_client = MagicMock(spec=httpx.AsyncClient)

    return app


# ── Login endpoint ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_redirect_contains_required_params() -> None:
    """GET /v1/auth/login returns 302 with required PKCE/OIDC params in URL."""
    valkey = _make_mock_valkey()
    app = _make_auth_app(valkey=valkey)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        resp = await ac.get("/v1/auth/login")

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "client_id=test-client-id" in location
    assert "code_challenge_method=S256" in location
    assert "code_challenge=" in location
    assert "state=" in location
    assert "redirect_uri=" in location
    assert "openid" in location


@pytest.mark.asyncio
async def test_login_stores_state_in_valkey() -> None:
    """GET /v1/auth/login stores auth:pkce:{state} in Valkey with TTL=600."""
    valkey = _make_mock_valkey()
    app = _make_auth_app(valkey=valkey)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        resp = await ac.get("/v1/auth/login")

    assert resp.status_code == 302
    # Verify Valkey.set was called
    valkey.set.assert_called_once()
    call_args = valkey.set.call_args
    key = call_args[0][0]
    assert key.startswith("auth:pkce:")
    # Verify TTL
    ttl = call_args[1].get("ttl") or call_args[0][2]
    assert ttl == 600


@pytest.mark.asyncio
async def test_login_503_on_valkey_unavailable() -> None:
    """GET /v1/auth/login returns 503 when Valkey is None (fail-closed)."""
    app = _make_auth_app(valkey=None)  # Valkey not available

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        resp = await ac.get("/v1/auth/login")

    assert resp.status_code == 503
    assert resp.json()["error"] == "valkey_unavailable"


# ── Callback endpoint ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_missing_state_400() -> None:
    """GET /v1/auth/callback without state param returns 400."""
    valkey = _make_mock_valkey()
    app = _make_auth_app(valkey=valkey)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/callback?code=abc")

    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_params"


@pytest.mark.asyncio
async def test_callback_unknown_state_400() -> None:
    """GET /v1/auth/callback with state not in Valkey returns 400."""
    # Pipeline returns None (key not found)
    valkey = _make_mock_valkey(getdel_result=None)
    app = _make_auth_app(valkey=valkey)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/callback?code=abc&state=unknown-state")

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_state"


@pytest.mark.asyncio
async def test_callback_single_use_state() -> None:
    """Second callback attempt with already-consumed state returns 400."""
    # First getdel returns verifier (consumed); second getdel returns None (key gone)
    valkey = MagicMock()
    valkey.set = AsyncMock()
    valkey.getdel = AsyncMock(side_effect=["code-verifier-123", None])

    # httpx_client: first token exchange fails (to stop the flow early)
    httpx_client = MagicMock(spec=httpx.AsyncClient)
    httpx_client.post = AsyncMock(side_effect=ConnectionError("zitadel down"))

    app = _make_auth_app(valkey=valkey, httpx_client=httpx_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First call: PKCE state found, token exchange fails → 503
        resp1 = await ac.get("/v1/auth/callback?code=abc&state=test-state")
        # Second call: state already consumed → 400
        resp2 = await ac.get("/v1/auth/callback?code=abc&state=test-state")

    assert resp1.status_code == 503  # state consumed, but token exchange failed
    assert resp2.status_code == 400
    assert resp2.json()["error"] == "invalid_state"


@pytest.mark.asyncio
async def test_callback_error_param_400() -> None:
    """GET /v1/auth/callback?error=access_denied returns 400 immediately."""
    app = _make_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/callback?error=access_denied&error_description=User+denied+access")

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "access_denied"


# ── Refresh endpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_no_cookie_401() -> None:
    """POST /v1/auth/refresh without refresh_token cookie returns 401."""
    app = _make_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/auth/refresh")

    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_refresh_token"


# ── Logout endpoint ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_clears_cookie() -> None:
    """POST /v1/auth/logout sets Set-Cookie with Max-Age=0."""
    httpx_client = MagicMock(spec=httpx.AsyncClient)
    httpx_client.post = AsyncMock(return_value=MagicMock(status_code=200))
    app = _make_auth_app(httpx_client=httpx_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/auth/logout", cookies={"refresh_token": "old-token"})

    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out successfully"
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "max-age=0" in set_cookie.lower()


@pytest.mark.asyncio
async def test_logout_succeeds_without_cookie() -> None:
    """POST /v1/auth/logout returns 200 even without refresh_token cookie."""
    app = _make_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/v1/auth/logout")

    assert resp.status_code == 200


# ── /me endpoint ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_endpoint_requires_auth() -> None:
    """GET /v1/auth/me without Authorization header returns 401."""
    app = _make_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/me")

    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_token"


@pytest.mark.asyncio
async def test_me_endpoint_rejects_invalid_token() -> None:
    """GET /v1/auth/me with an invalid Bearer token returns 401."""
    app = _make_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert resp.status_code == 401
