"""Shared test fixtures for content-store service.

Unit tests use a lightweight app without the full lifespan (no DB/Kafka/MinIO).
State attributes are set directly on the app — ASGI transport doesn't trigger lifespan.
InternalJWTMiddleware is included (PRD-0025) with a system JWT in the default client.
"""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock

# PLAN-0093 T-A-1-03: pin APP_ENV before app imports so the new
# observability.assert_app_env_or_die() lifespan guard never aborts tests
# that enable internal_jwt_skip_verification.
os.environ.setdefault("APP_ENV", "test")

import jwt as _jwt
import pytest
from content_store.api.dlq import router as dlq_router
from content_store.api.documents import router as documents_router
from content_store.api.health import router as health_router
from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_system_jwt() -> str:
    """HS256 JWT with role=system for unit tests.

    InternalJWTMiddleware decodes without signature verification when public_key is None
    (JWKS server not running in unit test environment).
    """
    payload = {
        "iss": "worldview-gateway",
        "sub": "unit-test-system",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "unit-test-secret", algorithm="HS256")


_SYSTEM_JWT = _make_system_jwt()


@pytest.fixture
def app():
    test_app = FastAPI(title="content-store-test")
    test_app.include_router(health_router)
    test_app.include_router(dlq_router)
    test_app.include_router(documents_router)

    # InternalJWTMiddleware (PRD-0025) — public_key is None in tests (no JWKS at startup).
    # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
    # F-001: skip_verification=True allows unverified decode in unit tests only.
    test_app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://api-gateway:8000/internal/jwks",
        skip_verification=True,
    )

    # Set mock state (ASGI transport does not trigger lifespan)
    settings = MagicMock()
    settings.admin_token = "test-admin-token"  # noqa: S105

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    test_app.state.settings = settings
    test_app.state.session_factory = lambda: cm
    test_app.state.read_factory = lambda: cm
    test_app.state.valkey = None
    test_app.state.consumer_alive = True
    # NOTE: Do NOT set _internal_jwt_public_key here.  InternalJWTMiddleware
    # is configured with skip_verification=True for unit tests.  When the
    # public key is set, dispatch() bypasses the skip_verification path and
    # attempts RS256 signature verification — which fails for HS256 test
    # tokens (InvalidAlgorithmError → 401 on every request).
    # Readyz tests that need the key set should do so in their own fixture.

    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _SYSTEM_JWT},
    ) as ac:
        yield ac


@pytest.fixture
async def unauthenticated_client(app):
    """Client without X-Internal-JWT — used to test InternalJWTMiddleware 401 behaviour."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
