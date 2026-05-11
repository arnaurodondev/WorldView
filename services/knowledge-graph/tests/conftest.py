"""Shared test fixtures for knowledge-graph service.

Unit tests use the full app created by create_app() with InternalJWTMiddleware included.
``internal_jwt_skip_verification=True`` is set so that when public_key is None (JWKS server
not running in unit tests), the middleware still decodes tokens without signature verification.
The default ``client`` fixture injects a system JWT via X-Internal-JWT header (BP-134 fix).
"""

from __future__ import annotations

import os
import time

# Required fields with no defaults (security hardening) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "minioadmin-test")
# DEF-001: database_url no longer has a default (fail-fast hardening).
# Unit tests provide a fake DSN — no real DB connection is made in unit tests.
os.environ.setdefault(
    "KNOWLEDGE_GRAPH_DATABASE_URL",
    "postgresql+asyncpg://postgres:test@localhost:5432/intelligence_db_test",
)

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.app import create_app
from knowledge_graph.config import Settings


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


@pytest.fixture
def app():
    # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
    return create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_INTERNAL_HEADERS,
    ) as ac:
        yield ac
