"""Shared test fixtures for knowledge-graph service."""

import os

import pytest

# Required fields with no defaults (security hardening) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "minioadmin-test")

from httpx import ASGITransport, AsyncClient
from knowledge_graph.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
