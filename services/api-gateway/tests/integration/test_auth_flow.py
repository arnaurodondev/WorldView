"""Integration tests for the OIDC auth flow (T-B-1-03).

Uses ``httpx.AsyncClient`` with ``ASGITransport``.
Zitadel token endpoint and S1 provision endpoint are mocked via
``unittest.mock`` on the shared httpx_client.
Valkey is mocked in-process.
"""

from __future__ import annotations

import json
import time
from dataclasses import fields
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


# ── Shared test keypairs ──────────────────────────────────────────────────────


def _gen_rsa_pair():
    """Generate an RSA-2048 key pair for tests."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


# Keypair for "Zitadel" signing of access_token (used in callback tests)
_ZITADEL_PRIVATE, _ZITADEL_PUBLIC = _gen_rsa_pair()
# Keypair for S9 internal JWT signing
_S9_PRIVATE, _S9_PUBLIC = _gen_rsa_pair()


def _make_zitadel_access_token(sub: str = "zitadel-sub-123") -> str:
    """Return a Zitadel-style RS256 access_token signed with the test key."""
    iat = int(time.time())
    payload = {
        "iss": "https://example.zitadel.cloud",
        "sub": sub,
        "aud": "test-client-id",
        "exp": iat + 900,
        "iat": iat,
        "email": "user@example.com",
        "email_verified": True,
        "preferred_username": "testuser",
    }
    return jwt.encode(payload, _ZITADEL_PRIVATE, algorithm="RS256", headers={"kid": "zitadel-kid"})


def _make_oidc_config():
    """Build a minimal OIDCProviderConfig with the test Zitadel public key."""
    from datetime import datetime

    from api_gateway.domain import OIDCProviderConfig

    return OIDCProviderConfig(
        issuer="https://example.zitadel.cloud",
        authorization_endpoint="https://example.zitadel.cloud/oauth/v2/authorize",
        token_endpoint="https://example.zitadel.cloud/oauth/v2/token",
        end_session_endpoint="https://example.zitadel.cloud/oidc/v1/end_session",
        jwks_uri="https://example.zitadel.cloud/oauth/v2/keys",
        public_keys={"zitadel-kid": _ZITADEL_PUBLIC},
        last_refreshed_at=datetime.now(tz=UTC),
    )


def _make_integration_app(
    valkey: Any = None,
    httpx_client: Any = None,
):
    """Build a full app suitable for auth integration tests."""
    from api_gateway.app import create_app
    from api_gateway.clients import ServiceClients
    from api_gateway.config import Settings
    from api_gateway.oidc import rsa_key_id

    private_pem = _S9_PRIVATE.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = _S9_PUBLIC.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

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
    app.state.oidc_config = _make_oidc_config()
    app.state.rsa_private_key = _S9_PRIVATE
    app.state.rsa_public_key = _S9_PUBLIC
    app.state.rsa_kid = rsa_key_id(_S9_PUBLIC)
    app.state.internal_jwks = None
    app.state.valkey = valkey
    app.state.httpx_client = httpx_client or MagicMock(spec=httpx.AsyncClient)

    return app


def _make_mock_valkey_with_pkce(state: str, code_verifier: str) -> MagicMock:
    """Valkey mock that has PKCE state stored and caches user identity."""
    valkey = MagicMock()
    valkey.set = AsyncMock()
    valkey.get = AsyncMock(return_value=None)
    valkey.delete = AsyncMock(return_value=1)

    # Pipeline: first call returns [code_verifier, 1] (PKCE get+delete)
    # Subsequent get calls return None (user cache miss initially)
    pipe = MagicMock()
    pipe.get = MagicMock()
    pipe.delete = MagicMock()
    pipe.execute = AsyncMock(return_value=[code_verifier, 1])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    valkey.pipeline = MagicMock(return_value=pipe)

    return valkey


# ── Integration tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_callback_full_flow() -> None:
    """Full flow: callback with valid code → access_token issued, cookie set, user returned."""
    access_token = _make_zitadel_access_token("sub-abc-123")
    refresh_token_value = "zitadel-refresh-token-xyz"  # noqa: S105

    # Mock httpx_client: token exchange returns valid JWT; S1 provision returns user
    httpx_client = MagicMock(spec=httpx.AsyncClient)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json = MagicMock(
        return_value={
            "access_token": access_token,
            "refresh_token": refresh_token_value,
            "expires_in": 900,
            "token_type": "Bearer",
        }
    )

    provision_response = MagicMock()
    provision_response.status_code = 200
    provision_response.json = MagicMock(
        return_value={
            "user_id": "01900000-0000-7000-8000-000000000001",
            "tenant_id": "01900000-0000-7000-8000-000000000002",
            "email": "user@example.com",
            "created": True,
            "linked": False,
        }
    )

    httpx_client.post = AsyncMock(side_effect=[token_response, provision_response])

    # Valkey mock with stored PKCE state
    valkey = _make_mock_valkey_with_pkce("test-state-abc", "test-code-verifier-abc")

    app = _make_integration_app(valkey=valkey, httpx_client=httpx_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/auth/callback?code=auth-code-123&state=test-state-abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == access_token
    assert body["token_type"] == "Bearer"  # noqa: S105
    assert "user" in body
    assert body["user"]["email"] == "user@example.com"
    assert body["user"]["sub"] == "sub-abc-123"

    # Cookie set with correct attributes
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/v1/auth/refresh" in set_cookie.lower()


@pytest.mark.asyncio
async def test_refresh_token_rotation() -> None:
    """POST /v1/auth/refresh exchanges cookie → new access_token, rotates cookie."""
    new_access_token = _make_zitadel_access_token("sub-refresh-456")
    new_refresh_token = "new-refresh-token-xyz"  # noqa: S105

    httpx_client = MagicMock(spec=httpx.AsyncClient)
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json = MagicMock(
        return_value={
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "expires_in": 900,
        }
    )
    httpx_client.post = AsyncMock(return_value=token_response)

    app = _make_integration_app(httpx_client=httpx_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/v1/auth/refresh",
            cookies={"refresh_token": "old-refresh-token"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == new_access_token
    assert body["token_type"] == "Bearer"  # noqa: S105

    # New cookie set (rotation)
    set_cookie = resp.headers.get("set-cookie", "")
    assert new_refresh_token in set_cookie


@pytest.mark.asyncio
async def test_logout_best_effort() -> None:
    """POST /v1/auth/logout returns 200 even if Zitadel revocation fails."""
    httpx_client = MagicMock(spec=httpx.AsyncClient)
    # Simulate Zitadel revocation failure (timeout)
    httpx_client.post = AsyncMock(side_effect=TimeoutError("Zitadel timeout"))

    valkey = MagicMock()
    valkey.delete = AsyncMock(return_value=1)

    app = _make_integration_app(valkey=valkey, httpx_client=httpx_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/v1/auth/logout",
            cookies={"refresh_token": "some-refresh-token"},
        )

    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out successfully"

    # Cookie cleared
    set_cookie = resp.headers.get("set-cookie", "")
    assert "max-age=0" in set_cookie.lower()


@pytest.mark.asyncio
async def test_proxy_request_includes_internal_jwt() -> None:
    """Authenticated proxied requests include X-Internal-JWT header."""
    from api_gateway.oidc import rsa_key_id

    # Create a Zitadel-signed access_token for authentication
    access_token = _make_zitadel_access_token("proxy-user-sub")

    # User cache in Valkey
    valkey = MagicMock()
    user_cache = json.dumps(
        {"user_id": "01900000-0000-7000-8000-000000000003", "tenant_id": "01900000-0000-7000-8000-000000000004"}
    )
    valkey.get = AsyncMock(return_value=user_cache)
    valkey.set = AsyncMock()
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock()

    app = _make_integration_app(valkey=valkey)

    # Capture the headers passed to the rag_chat mock
    captured_headers: dict[str, str] = {}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"response": "ok"}'

    async def _capture_post(path: str, **kwargs: Any) -> Any:
        headers = kwargs.get("headers", {})
        captured_headers.update(headers)
        return mock_response

    app.state.clients.rag_chat.post = _capture_post

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post(
            "/v1/chat",
            content=b'{"message": "hello"}',
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    # The X-Internal-JWT should be forwarded to the downstream service
    assert "X-Internal-JWT" in captured_headers, (
        "Expected X-Internal-JWT in downstream headers — " "check InternalJWTIssuerMiddleware and _auth_headers()"
    )
    # Verify it's a valid RS256 JWT signed by S9
    internal_jwt = captured_headers["X-Internal-JWT"]
    decoded = jwt.decode(
        internal_jwt,
        _S9_PUBLIC,
        algorithms=["RS256"],
        options={"require": ["iss", "sub", "exp", "iat"]},
        issuer="worldview-gateway",
    )
    assert decoded["iss"] == "worldview-gateway"
    assert decoded["kid"] == rsa_key_id(_S9_PUBLIC)
