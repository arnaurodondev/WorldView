"""Fixtures for knowledge-graph API unit tests.

Overrides the read-only session dependency so tests don't need a real DB.
InternalJWTMiddleware (PRD-0025) is included via create_app() with
``internal_jwt_skip_verification=True``. The api_client fixture includes
a system JWT so protected endpoints are accessible in unit tests.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.api.dependencies import get_readonly_session
from knowledge_graph.app import create_app
from knowledge_graph.config import Settings


def _make_system_jwt() -> str:
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
def api_app():
    """FastAPI app with readonly session dependency overridden."""
    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]

    async def _mock_readonly_session():
        yield AsyncMock()

    app.dependency_overrides[get_readonly_session] = _mock_readonly_session
    return app


@pytest.fixture
async def api_client(api_app):
    """ASGI test client using the overridden app.

    Includes X-Internal-JWT for InternalJWTMiddleware (PRD-0025).
    With skip_verification=True and public_key=None, the middleware
    decodes without signature verification — any structurally-valid JWT works.
    """
    transport = ASGITransport(app=api_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_INTERNAL_HEADERS,
    ) as ac:
        yield ac
