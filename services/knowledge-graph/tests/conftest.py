"""Shared test fixtures for knowledge-graph service."""

from __future__ import annotations

import os
import time

# Required fields with no defaults (security hardening) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "minioadmin-test")

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.app import create_app


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
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Internal-JWT": _SYSTEM_JWT},
    ) as ac:
        yield ac
