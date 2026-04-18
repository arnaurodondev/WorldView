"""Tests for GET /v1/auth/ws-token endpoint (PRD-0028 Wave S9-2 T-S9-2-04).

The ws-token endpoint issues a 30-second RS256 JWT for WebSocket authentication.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}


def _make_jwt() -> str:
    return pyjwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _generate_rsa_key_pair():
    """Generate a test RSA-2048 private key and kid."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, "test-kid-001"


@pytest.mark.asyncio
async def test_ws_token_requires_auth(app) -> None:
    """GET /v1/auth/ws-token without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/auth/ws-token")

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "authentication_required"


@pytest.mark.asyncio
async def test_ws_token_returns_jwt_30s(authed_app) -> None:
    """GET /v1/auth/ws-token with valid auth → {token, expires_in: 30}."""
    # Inject RSA private key + kid into app state so ws-token can sign
    private_key, kid = _generate_rsa_key_pair()
    authed_app.state.rsa_private_key = private_key
    authed_app.state.rsa_kid = kid

    # Mock common.ids.new_uuid7 and common.time.utc_now used by issue_ws_jwt
    mock_uuid = MagicMock(return_value="00000000-0000-7000-0000-000000000001")
    mock_now = MagicMock()
    mock_now.return_value.timestamp.return_value = 1000000000.0

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("api_gateway.jwt_utils.new_uuid7", mock_uuid),
            patch("api_gateway.jwt_utils.utc_now", mock_now),
        ):
            resp = await client.get(
                "/v1/auth/ws-token",
                headers={"Authorization": f"Bearer {_make_jwt()}"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["expires_in"] == 30

    # Decode the returned JWT and verify claims (disable exp check — mocked iat is in the past)
    public_key = private_key.public_key()
    claims = pyjwt.decode(body["token"], public_key, algorithms=["RS256"], options={"verify_exp": False})
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "t-1"
    assert claims["scope"] == "alerts:stream"
    assert claims["iss"] == "worldview-gateway"
    assert claims["exp"] == 1000000030  # iat(1000000000) + 30s TTL


@pytest.mark.asyncio
async def test_ws_token_503_without_rsa_key(authed_app) -> None:
    """GET /v1/auth/ws-token with auth but no RSA key → 503."""
    # Ensure no RSA key is available (default from conftest)
    authed_app.state.rsa_private_key = None
    authed_app.state.rsa_kid = None

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/auth/ws-token",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "jwt_signing_unavailable"


@pytest.mark.asyncio
async def test_ws_token_rejects_incomplete_claims(authed_app) -> None:
    """GET /v1/auth/ws-token with missing tenant_id in user claims → 401.

    F-004: The ws-token endpoint validates that both sub and tenant_id are
    present before issuing a token. A user dict with missing tenant_id should
    be rejected with 'incomplete_auth_claims'.
    """
    # Inject RSA key so we pass the signing-availability check
    private_key, kid = _generate_rsa_key_pair()
    authed_app.state.rsa_private_key = private_key
    authed_app.state.rsa_kid = kid

    # Create a JWT with missing tenant_id (sub present but no tenant_id)
    incomplete_payload = {"sub": "user-1", "exp": 9999999999}
    incomplete_token = pyjwt.encode(incomplete_payload, _JWT_SECRET, algorithm="HS256")

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/auth/ws-token",
            headers={"Authorization": f"Bearer {incomplete_token}"},
        )

    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "incomplete_auth_claims"
