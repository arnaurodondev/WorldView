"""Tests for GET /v1/alerts/stream/ws-url (PLAN-0089 Wave A-3).

The ws-url endpoint issues a 30-second WS JWT and returns the full
WebSocket URL ready for use with ``new WebSocket(ws_url)`` — eliminating
the client-side two-step of calling /v1/auth/ws-token then constructing
the URL manually.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

# ── Helpers ──────────────────────────────────────────────────────────────────

_JWT_SECRET = "test-secret"  # noqa: S105
# A minimal valid JWT payload: sub (OIDC subject) and tenant_id are required by
# the ws-url endpoint; exp keeps the token from expiring during the test run.
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "tenant-1", "exp": 9999999999}


def _make_jwt(payload: dict | None = None) -> str:
    """Encode a test HS256 JWT — the TestAuthMiddleware decodes it without
    verifying the signature so we can inject arbitrary claims."""
    return pyjwt.encode(payload or _JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _generate_rsa_key_pair():
    """Generate an RSA-2048 private key and a test kid string."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, "test-kid-ws-url"


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_alerts_ws_url_happy_path(authed_app) -> None:
    """GET /v1/alerts/stream/ws-url with valid auth → {ws_url, token, expires_in}.

    Verifies:
    - HTTP 200 is returned.
    - Response body contains 'ws_url', 'token', and 'expires_in'.
    - 'ws_url' begins with the configured alert_ws_url prefix.
    - 'ws_url' contains the token as a query parameter.
    - 'expires_in' is 30 (matches _WS_TTL in jwt_utils).
    """
    private_key, kid = _generate_rsa_key_pair()
    authed_app.state.rsa_private_key = private_key
    authed_app.state.rsa_kid = kid

    # Store the ws_url setting so we can verify the response prefix.
    # The Settings default is "ws://localhost:8010" — configure it explicitly
    # to avoid coupling the test to the default value.
    authed_app.state.settings.alert_ws_url = "ws://localhost:8010"  # type: ignore[attr-defined]

    # Mock time and uuid so the issued JWT has deterministic claims.
    mock_uuid = MagicMock(return_value="00000000-0000-7000-0000-000000000001")
    mock_now = MagicMock()
    mock_now.return_value.timestamp.return_value = 1_000_000_000.0

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("api_gateway.jwt_utils.new_uuid7", mock_uuid),
            patch("api_gateway.jwt_utils.utc_now", mock_now),
        ):
            resp = await client.get(
                "/v1/alerts/stream/ws-url",
                headers={"Authorization": f"Bearer {_make_jwt()}"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # All three fields must be present.
    assert "ws_url" in body, "response missing 'ws_url'"
    assert "token" in body, "response missing 'token'"
    assert "expires_in" in body, "response missing 'expires_in'"

    # ws_url must point at the alert WebSocket service and carry the token.
    assert body["ws_url"].startswith("ws://localhost:8010"), f"ws_url has unexpected prefix: {body['ws_url']}"
    assert body["token"] in body["ws_url"], "token not embedded in ws_url query param"


@pytest.mark.asyncio
async def test_get_alerts_ws_url_no_auth(app) -> None:
    """GET /v1/alerts/stream/ws-url without authentication → 401.

    Unauthenticated requests (no Authorization header) must be rejected before
    any JWT is issued.  Uses the ``app`` fixture (no TestAuthMiddleware) so
    request.state.user is never set.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/alerts/stream/ws-url")

    # Endpoint raises HTTPException(401) when request.state.user is absent.
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_get_alerts_ws_url_expires_in_30(authed_app) -> None:
    """GET /v1/alerts/stream/ws-url → expires_in == 30 (matches _WS_TTL).

    The WS token TTL is intentionally short (30 s) because the token appears
    in server logs via the WebSocket URL.  This test pins the contract so that
    a jwt_utils change that accidentally extends _WS_TTL would be caught here.
    """
    private_key, kid = _generate_rsa_key_pair()
    authed_app.state.rsa_private_key = private_key
    authed_app.state.rsa_kid = kid

    mock_uuid = MagicMock(return_value="00000000-0000-7000-0000-000000000002")
    mock_now = MagicMock()
    mock_now.return_value.timestamp.return_value = 1_000_000_000.0

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch("api_gateway.jwt_utils.new_uuid7", mock_uuid),
            patch("api_gateway.jwt_utils.utc_now", mock_now),
        ):
            resp = await client.get(
                "/v1/alerts/stream/ws-url",
                headers={"Authorization": f"Bearer {_make_jwt()}"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # expires_in must be exactly 30 — this is the documented contract.
    assert body["expires_in"] == 30, f"Expected expires_in=30 (matching _WS_TTL), got {body['expires_in']}"

    # Additionally verify the JWT exp claim matches iat + 30 so the expires_in
    # value is not just hardcoded in the response but reflects the actual token.
    public_key = private_key.public_key()
    claims = pyjwt.decode(
        body["token"],
        public_key,
        algorithms=["RS256"],
        audience="worldview-internal",
        options={"verify_exp": False},
    )
    expected_exp = 1_000_000_000 + 30  # iat + _WS_TTL
    assert claims["exp"] == expected_exp, f"Token exp claim {claims['exp']} does not match expected {expected_exp}"
