"""Health endpoint tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_ok(app, client) -> None:
    """readyz returns 200 when DB probe succeeds."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)

    # Directly set the engine on app.state
    app.state.engine = mock_engine

    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_db_down(app, client) -> None:
    """readyz returns 503 when DB connection raises."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=OSError("connection refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)

    app.state.engine = mock_engine

    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "db"


@pytest.mark.asyncio
async def test_readyz_no_engine(app, client) -> None:
    """readyz returns 503 when engine is not yet initialized."""
    # Ensure engine is absent
    if hasattr(app.state, "engine"):
        del app.state.engine

    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
