"""Shared test fixtures for rag-chat service.

Unit tests use the full app created by create_app() with InternalJWTMiddleware included.
``internal_jwt_skip_verification=True`` is set so that when public_key is None (JWKS server
not running in unit tests), the middleware still decodes tokens without signature verification.
The default ``client`` fixture injects a system JWT via X-Internal-JWT header (BP-134 fix).
"""

from __future__ import annotations

import time

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings


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
_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _SYSTEM_JWT}


@pytest.fixture
def settings() -> RagChatSettings:
    """Minimal settings suitable for unit tests (no real infra required)."""
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
        internal_jwt_skip_verification=True,
    )


@pytest.fixture
def app(settings: RagChatSettings):  # type: ignore[return]
    return create_app(settings)


@pytest.fixture
async def client(app):  # type: ignore[return]
    """Authenticated client with X-Internal-JWT header (system role)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac


@pytest.fixture
async def unauthenticated_client(app):  # type: ignore[return]
    """Client without X-Internal-JWT — used to test InternalJWTMiddleware 401 behaviour."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
