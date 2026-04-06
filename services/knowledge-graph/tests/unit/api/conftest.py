"""Fixtures for knowledge-graph API unit tests.

Overrides the read-only session dependency so tests don't need a real DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.api.dependencies import get_readonly_session
from knowledge_graph.app import create_app


@pytest.fixture
def api_app():
    """FastAPI app with readonly session dependency overridden."""
    app = create_app()

    async def _mock_readonly_session():
        yield AsyncMock()

    app.dependency_overrides[get_readonly_session] = _mock_readonly_session
    return app


@pytest.fixture
async def api_client(api_app):
    """ASGI test client using the overridden app."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
