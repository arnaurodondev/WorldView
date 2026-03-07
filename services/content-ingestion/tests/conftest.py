"""Shared test fixtures for content-ingestion service."""

import pytest
from httpx import ASGITransport, AsyncClient

from content_ingestion.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
