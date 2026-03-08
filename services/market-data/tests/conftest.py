"""Shared test fixtures for market-data service."""

import pytest
from httpx import ASGITransport, AsyncClient
from market_data.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
