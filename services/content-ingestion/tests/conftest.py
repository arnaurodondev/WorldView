"""Shared test fixtures for content-ingestion service."""

from __future__ import annotations

import time

import jwt as _jwt
import pytest
from content_ingestion.app import create_app
from httpx import ASGITransport, AsyncClient


def _make_system_jwt() -> str:
    """HS256 JWT with role=system for unit tests.

    InternalJWTMiddleware decodes without signature verification when public_key is None
    (JWKS server not running in unit test environment).  The middleware will still populate
    request.state.role so downstream guards work correctly.
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
    from content_ingestion.config import Settings

    # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
    settings = Settings(internal_jwt_skip_verification=True)  # type: ignore[call-arg]
    return create_app(settings)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _SYSTEM_JWT},
    ) as ac:
        yield ac
