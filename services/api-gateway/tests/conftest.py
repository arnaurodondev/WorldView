"""Shared test fixtures for api-gateway service."""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import MagicMock

import httpx
import pytest
from api_gateway.app import create_app
from api_gateway.clients import ServiceClients
from api_gateway.config import Settings
from httpx import ASGITransport, AsyncClient


def _mock_settings() -> Settings:
    """Settings that don't depend on real infra."""
    return Settings(
        valkey_url="redis://localhost:6379/0",
        jwt_secret="test-secret",
        cors_origins="http://localhost:3000",
    )


@pytest.fixture
def settings() -> Settings:
    return _mock_settings()


@pytest.fixture
def app(settings):
    """App with mocked service clients injected."""
    application = create_app(settings)

    # Build mock clients
    mock_clients = ServiceClients(**{f.name: MagicMock(spec=httpx.AsyncClient) for f in fields(ServiceClients)})
    application.state.clients = mock_clients
    application.state.valkey = None  # no rate limiting in tests
    return application


@pytest.fixture
def mock_clients(app) -> ServiceClients:
    return app.state.clients


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
