"""Shared test fixtures for api-gateway service."""

from __future__ import annotations

from dataclasses import fields
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware


def _generate_rsa_pem_pair() -> tuple[str, str]:
    """Generate an RSA-2048 key pair and return (private_pem, public_pem)."""
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
    return private_pem, public_pem


# Module-level keypair shared across all non-unit fixtures
_PRIVATE_PEM, _PUBLIC_PEM = _generate_rsa_pem_pair()


def _mock_settings():
    """Settings that don't depend on real infra."""
    from api_gateway.config import Settings

    return Settings(
        valkey_url="redis://localhost:6379/0",
        oidc_issuer_url="https://example.zitadel.cloud",
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        oidc_audience="test-client-id",
        internal_jwt_private_key=_PRIVATE_PEM,
        internal_jwt_public_key=_PUBLIC_PEM,
        cors_origins="http://localhost:3000",
        # F-013: default changed to True in production; keep False in tests so
        # the SecurityHeadersMiddleware does not inject HSTS on HTTP test responses.
        cookie_secure=False,
    )


def _build_app(settings, inject_user_from_bearer: bool = False):
    """Build a test app with mocked state (bypasses lifespan)."""
    from api_gateway.app import create_app
    from api_gateway.clients import ServiceClients

    application = create_app(settings)

    # Build mock clients
    mock_clients = ServiceClients(**{f.name: MagicMock(spec=httpx.AsyncClient) for f in fields(ServiceClients)})
    application.state.clients = mock_clients
    # F-CRIT-003: RateLimitMiddleware now returns 503 when Valkey is None (fail-closed).
    # Provide a mock Valkey that always allows requests through rate limiting in tests.
    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock(return_value=True)
    mock_valkey.ping = AsyncMock(return_value=True)  # readyz probe
    application.state.valkey = mock_valkey
    application.state.oidc_config = None  # no real OIDC; OIDCAuthMiddleware skips
    application.state.rsa_private_key = None
    application.state.rsa_public_key = None
    application.state.rsa_kid = None
    application.state.internal_jwks = None

    if inject_user_from_bearer:
        # Test-only: decode Bearer JWT without verification and inject as request.state.user.
        # This simulates what OIDCAuthMiddleware does in production with real RS256 tokens.
        class TestAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Any, call_next: Any) -> Any:
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    try:
                        payload = pyjwt.decode(
                            auth[7:],
                            options={"verify_signature": False},
                        )
                        request.state.user = {
                            "sub": payload.get("sub", ""),
                            "user_id": payload.get("sub", ""),
                            "tenant_id": payload.get("tenant_id", ""),
                            "email": payload.get("email", "test@example.com"),
                            "email_verified": True,
                            # role is extracted from the JWT so admin tests can set
                            # role="admin" in their token and get it reflected here
                            "role": payload.get("role", "user"),
                        }
                    except Exception:
                        if not hasattr(request.state, "user"):
                            request.state.user = None
                return await call_next(request)

        application.add_middleware(TestAuthMiddleware)

    return application, mock_clients


@pytest.fixture
def settings():
    return _mock_settings()


@pytest.fixture
def app(settings):
    """App with mocked service clients (no auth injection — tests public/unauthenticated routes)."""
    application, _ = _build_app(settings, inject_user_from_bearer=False)
    return application


@pytest.fixture
def authed_app(settings):
    """App that injects user state from a Bearer JWT (simulates OIDC-authenticated requests)."""
    application, _ = _build_app(settings, inject_user_from_bearer=True)
    return application


@pytest.fixture
def mock_clients(app):
    return app.state.clients


@pytest.fixture
def authed_mock_clients(authed_app):
    return authed_app.state.clients


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def authed_client(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
