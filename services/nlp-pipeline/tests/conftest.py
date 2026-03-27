"""Shared test fixtures for nlp-pipeline service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.app import create_app


def _make_ok_session_factory() -> MagicMock:
    """Session factory whose sessions succeed on SELECT 1."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock())
    return MagicMock(return_value=session)


@pytest.fixture
def app():
    application = create_app()
    # Populate the state that readyz / other endpoints require so that
    # basic health tests pass without running the full lifespan.
    application.state.nlp_session_factory = _make_ok_session_factory()
    application.state.intelligence_session_factory = _make_ok_session_factory()
    valkey = AsyncMock()
    valkey.ping = AsyncMock(return_value=True)
    application.state.valkey = valkey
    application.state.dispatcher_healthy = True
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
