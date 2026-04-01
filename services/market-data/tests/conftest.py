"""Shared test fixtures for market-data service."""

import os

import pytest

# Required fields with no defaults (security hardening C-001) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("MARKET_DATA_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("MARKET_DATA_STORAGE_SECRET_KEY", "minioadmin-test")
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
