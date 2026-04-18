"""Shared test fixtures for nlp-pipeline service.

Unit tests use the full app created by create_app() with InternalJWTMiddleware included.
``internal_jwt_skip_verification=True`` is set so that when public_key is None (JWKS server
not running in unit tests), the middleware still decodes tokens without signature verification.
The default ``client`` fixture injects a system JWT via X-Internal-JWT header (BP-134 fix).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.app import create_app
from nlp_pipeline.config import Settings


def _make_system_jwt() -> str:
    """HS256 JWT with role=system for unit tests.

    InternalJWTMiddleware decodes without signature verification when
    skip_verification=True and public_key is None (JWKS server not running
    in unit test environment).
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


def _make_ok_session_factory() -> MagicMock:
    """Session factory whose sessions succeed on SELECT 1."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock())
    return MagicMock(return_value=session)


@pytest.fixture
def app():
    application = create_app(Settings(internal_jwt_skip_verification=True))
    # Populate the state that readyz / other endpoints require so that
    # basic health tests pass without running the full lifespan.
    application.state.nlp_session_factory = _make_ok_session_factory()
    application.state.intelligence_session_factory = _make_ok_session_factory()
    valkey = AsyncMock()
    valkey.ping = AsyncMock(return_value=True)
    application.state.valkey = valkey
    application.state.dispatcher_healthy = True
    return application


@pytest.fixture
async def client(app):
    """Authenticated client with X-Internal-JWT header (system role)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac
