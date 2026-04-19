"""Integration tests for S9 cross-cutting concerns (T-F-1-06).

Tests cover security headers, JWKS public endpoint, rate limiting, and CORS.
All tests use the ASGI test client — no real Zitadel instance required.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


# ── Helpers ────────────────────────────────────────────────────────────────────


def _gen_rsa_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return private_key, private_key.public_key()


_S9_PRIVATE, _S9_PUBLIC = _gen_rsa_pair()


def _make_app(*, valkey: object | None = "auto"):
    """Build a test app with RSA keys and optional Valkey.

    ``valkey="auto"`` (default) creates a mock Valkey that always allows
    requests through rate limiting. Pass ``valkey=None`` explicitly to test
    the fail-closed (503) path, or a mock with specific return values for
    rate limit threshold tests.
    """
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
    )

    app = create_app(settings)
    app.state.clients = ServiceClients(**{f.name: MagicMock(spec=httpx.AsyncClient) for f in fields(ServiceClients)})
    app.state.oidc_config = None  # OIDCAuthMiddleware skips when None
    from api_gateway.oidc import build_jwks_response

    kid = rsa_key_id(_S9_PUBLIC)
    app.state.rsa_private_key = _S9_PRIVATE
    app.state.rsa_public_key = _S9_PUBLIC
    app.state.rsa_kid = kid
    app.state.internal_jwks = build_jwks_response(_S9_PUBLIC, kid)
    if valkey == "auto":
        # Default: mock Valkey that always allows requests through rate limiting
        mock_valkey = MagicMock()
        mock_valkey.incr = AsyncMock(return_value=1)
        mock_valkey.expire = AsyncMock(return_value=True)
        app.state.valkey = mock_valkey
    else:
        app.state.valkey = valkey
    app.state.httpx_client = MagicMock(spec=httpx.AsyncClient)
    return app


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_on_all_responses() -> None:
    """SecurityHeadersMiddleware injects all 5 required headers on every response."""
    app = _make_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_200 = await ac.get("/health")
        resp_401 = await ac.get("/api/v1/instruments")

    for resp, label in [(resp_200, "200"), (resp_401, "401")]:
        headers = resp.headers
        assert "x-frame-options" in headers, f"Missing X-Frame-Options on {label}"
        assert headers["x-frame-options"] == "DENY", f"Wrong X-Frame-Options on {label}"
        assert "x-content-type-options" in headers, f"Missing X-Content-Type-Options on {label}"
        assert headers["x-content-type-options"] == "nosniff", f"Wrong X-Content-Type-Options on {label}"
        assert "referrer-policy" in headers, f"Missing Referrer-Policy on {label}"
        assert "x-xss-protection" in headers, f"Missing X-XSS-Protection on {label}"
        assert "permissions-policy" in headers, f"Missing Permissions-Policy on {label}"


@pytest.mark.asyncio
async def test_jwks_endpoint_public() -> None:
    """/internal/jwks returns 200 without auth — backends use this at startup."""
    app = _make_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/internal/jwks")

    assert resp.status_code == 200
    body = resp.json()
    # Must return a JWKS structure with at least one key
    assert "keys" in body, "JWKS response must have 'keys' field"
    assert len(body["keys"]) >= 1, "JWKS must contain at least one key"
    key = body["keys"][0]
    assert key.get("kty") == "RSA", "Key type must be RSA"
    assert "n" in key and "e" in key, "RSA public key must have 'n' and 'e'"


@pytest.mark.asyncio
async def test_rate_limit_429_after_threshold() -> None:
    """21st unauthenticated request in the window is rejected with 429."""
    # Mock Valkey: incr returns 21 (over the 20/min unauthenticated limit)
    valkey = MagicMock()
    valkey.incr = AsyncMock(return_value=21)
    valkey.expire = AsyncMock()

    app = _make_app(valkey=valkey)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 429
    body = resp.json()
    assert "detail" in body


@pytest.mark.asyncio
async def test_rate_limit_503_when_valkey_unavailable() -> None:
    """D-001: When Valkey is None (unavailable), return 503 (fail-closed)."""
    app = _make_app(valkey=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"] == "Service temporarily unavailable"


@pytest.mark.asyncio
async def test_cors_preflight_explicit_methods() -> None:
    """CORS preflight returns explicit method allowlist — never '*' (SEC-003)."""
    app = _make_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.options(
            "/api/v1/instruments",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

    # CORS middleware responds to preflight with 200 (or 204)
    assert resp.status_code in (200, 204)

    allowed_methods = resp.headers.get("access-control-allow-methods", "")
    # Must not be a wildcard
    assert allowed_methods != "*", "CORS allow-methods must not be '*' (SEC-003)"
    # Must include expected methods
    assert "GET" in allowed_methods
    assert "POST" in allowed_methods
