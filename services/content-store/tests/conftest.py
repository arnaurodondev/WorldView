"""Shared test fixtures for content-store service.

Unit tests use a lightweight app without the full lifespan (no DB/Kafka/MinIO).
State attributes are set directly on the app — ASGI transport doesn't trigger lifespan.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_store.api.dlq import router as dlq_router
from content_store.api.documents import router as documents_router
from content_store.api.health import router as health_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    test_app = FastAPI(title="content-store-test")
    test_app.include_router(health_router)
    test_app.include_router(dlq_router)
    test_app.include_router(documents_router)

    # Set mock state (ASGI transport does not trigger lifespan)
    settings = MagicMock()
    settings.admin_token = "test-admin-token"  # noqa: S105

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    test_app.state.settings = settings
    test_app.state.session_factory = lambda: cm
    test_app.state.read_factory = lambda: cm
    test_app.state.valkey = None
    test_app.state.consumer_alive = True

    return test_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
