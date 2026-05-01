"""Unit tests for POST /internal/v1/service-token (PLAN-0057 Wave A-1 / BP-303).

These tests cover the service-account JWT minting endpoint that lets background
workers (e.g. nlp-pipeline price-impact worker) authenticate to S9 via a shared
secret instead of the production-disabled ``POST /v1/auth/dev-login``.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


# ── Helpers (mirror the shape used by test_auth_routes.py) ───────────────────


def _make_oidc_config() -> Any:
    """Minimal OIDCProviderConfig for the auth app fixture."""
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


def _make_mock_valkey() -> MagicMock:
    """Build a mock ValkeyClient that lets requests through rate limiting."""
    valkey = MagicMock()
    valkey.set = AsyncMock()
    valkey.get = AsyncMock(return_value=None)
    valkey.delete = AsyncMock(return_value=0)
    valkey.getdel = AsyncMock(return_value=None)
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock(return_value=True)
    return valkey


def _make_app(*, service_account_token: str | None = "shared-secret-xyz") -> Any:  # noqa: S107 — test fixture default
    """Build a FastAPI test app wired with a real RSA keypair + the service secret.

    ``service_account_token=None`` simulates the misconfiguration case where
    the operator forgot to set ``API_GATEWAY_SERVICE_ACCOUNT_TOKEN`` — the
    endpoint should respond with 503.
    """
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

    settings_kwargs: dict[str, Any] = {
        "valkey_url": "redis://localhost:6379/0",
        "oidc_issuer_url": "https://example.zitadel.cloud",
        "oidc_client_id": "test-client-id",
        "oidc_client_secret": "test-client-secret",
        "oidc_audience": "test-client-id",
        "internal_jwt_private_key": private_pem,
        "internal_jwt_public_key": public_pem,
        "cors_origins": "http://localhost:3000",
        "frontend_url": "http://localhost:5173",
        "cookie_secure": False,
        "portfolio_url": "http://s1:8001",
    }
    if service_account_token is not None:
        settings_kwargs["service_account_token"] = service_account_token

    settings = Settings(**settings_kwargs)  # type: ignore[arg-type]

    app = create_app(settings)
    app.state.clients = ServiceClients(**{f.name: MagicMock(spec=httpx.AsyncClient) for f in fields(ServiceClients)})
    app.state.valkey = _make_mock_valkey()
    app.state.oidc_config = _make_oidc_config()
    app.state.rsa_private_key = private_key
    app.state.rsa_public_key = private_key.public_key()
    from api_gateway.oidc import rsa_key_id

    app.state.rsa_kid = rsa_key_id(private_key.public_key())
    app.state.internal_jwks = None
    app.state.httpx_client = MagicMock(spec=httpx.AsyncClient)
    return app


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_token_happy_path_mints_jwt() -> None:
    """Correct secret + allow-listed service_name → 200 with a valid RS256 JWT."""
    app = _make_app(service_account_token="shared-secret-xyz")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/internal/v1/service-token",
            json={"service_name": "nlp-pipeline-price-impact", "secret": "shared-secret-xyz"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "Bearer"  # noqa: S105
    assert body["expires_in"] == 300
    assert isinstance(body["access_token"], str) and body["access_token"]

    # Decode with the gateway's public key — verifies RS256 signature.
    claims = jwt.decode(
        body["access_token"],
        app.state.rsa_public_key,
        algorithms=["RS256"],
        options={"require": ["iss", "sub", "exp"]},
        issuer="worldview-gateway",
    )
    assert claims["sub"] == "service:nlp-pipeline-price-impact"
    assert claims["tenant_id"] == "system"
    assert claims["role"] == "system"
    assert claims["service_name"] == "nlp-pipeline-price-impact"


# ── Failure paths ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_token_wrong_secret_returns_401() -> None:
    """Allow-listed service_name + wrong secret → 401 unauthorized."""
    app = _make_app(service_account_token="shared-secret-xyz")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/internal/v1/service-token",
            json={"service_name": "nlp-pipeline-price-impact", "secret": "wrong-secret"},
        )

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_service_token_unknown_service_name_returns_401() -> None:
    """Correct secret but service_name not on allow-list → 401 (same error shape)."""
    app = _make_app(service_account_token="shared-secret-xyz")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/internal/v1/service-token",
            json={"service_name": "evil-impostor", "secret": "shared-secret-xyz"},
        )

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_service_token_unconfigured_secret_returns_503() -> None:
    """When the gateway secret is unset → 503 misconfiguration error."""
    app = _make_app(service_account_token="")  # explicitly empty

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/internal/v1/service-token",
            json={"service_name": "nlp-pipeline-price-impact", "secret": "anything"},
        )

    assert resp.status_code == 503
    assert resp.json()["error"] == "service_account_unconfigured"


@pytest.mark.asyncio
async def test_service_token_missing_body_returns_422() -> None:
    """No body → FastAPI validation error before any auth check."""
    app = _make_app(service_account_token="shared-secret-xyz")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/internal/v1/service-token", json={})

    assert resp.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
async def test_service_token_works_when_app_env_production() -> None:
    """The endpoint must remain available in production — the shared secret is the auth."""
    app = _make_app(service_account_token="shared-secret-xyz")
    app.state.settings.app_env = "production"  # type: ignore[assignment]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/internal/v1/service-token",
            json={"service_name": "nlp-pipeline-price-impact", "secret": "shared-secret-xyz"},
        )

    assert resp.status_code == 200, resp.text
