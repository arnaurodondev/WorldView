"""Shared test fixtures for content-store service."""

import pytest
from content_store.app import create_app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
