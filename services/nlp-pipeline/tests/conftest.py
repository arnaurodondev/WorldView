"""Shared test fixtures for nlp-pipeline service."""

import pytest
from httpx import ASGITransport, AsyncClient

from nlp_pipeline.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
