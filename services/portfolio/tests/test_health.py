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

    # Satisfy both the JWKS and DB checks added by PRD-0025
    app.state._internal_jwt_public_key = "fake-pub-key"
    app.state.engine = mock_engine

    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_jwks_not_loaded(app, client) -> None:
    """readyz returns 503 when JWKS public key is not yet loaded."""
    # Ensure JWKS key is absent
    if hasattr(app.state, "_internal_jwt_public_key"):
        del app.state._internal_jwt_public_key

    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["reason"] == "jwks_not_loaded"


@pytest.mark.asyncio
async def test_readyz_db_down(app, client) -> None:
    """readyz returns 503 when DB connection raises."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=OSError("connection refused"))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)

    # JWKS key must be present so we actually reach the DB check
    app.state._internal_jwt_public_key = "fake-pub-key"
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
