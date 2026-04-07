"""Shared test fixtures for rag-chat service."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings


@pytest.fixture
def settings() -> RagChatSettings:
    """Minimal settings suitable for unit tests (no real infra required)."""
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        internal_service_token="test-internal-token",
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture
def app(settings: RagChatSettings):  # type: ignore[return]
    return create_app(settings)


@pytest.fixture
async def client(app):  # type: ignore[return]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
