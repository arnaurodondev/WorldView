"""Unit tests for FastAPI app factory (MD-031)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    """Minimal no-op lifespan for testing without real infrastructure."""
    app.state.session_factory = MagicMock()
    app.state.valkey_client = AsyncMock()
    app.state.quote_cache = AsyncMock()
    app.state.object_storage = None
    yield


def _make_test_app() -> FastAPI:
    """Create app with null lifespan and null session factory for tests."""
    import market_data.app as app_module

    with patch.object(app_module, "lifespan", _null_lifespan):
        from market_data.app import create_app

        return create_app()


def test_healthz_returns_ok() -> None:
    """GET /healthz always returns {status: ok}."""
    app = _make_test_app()
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_routes_registered() -> None:
    """All expected API routes are registered."""
    from market_data.app import create_app

    app = create_app()
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]

    # Core probes
    assert "/healthz" in routes
    assert "/readyz" in routes

    # Instruments
    assert "/api/v1/instruments" in routes
    assert "/api/v1/instruments/{instrument_id}" in routes
    assert "/api/v1/instruments/symbol/{symbol}" in routes

    # OHLCV
    assert "/api/v1/ohlcv/{instrument_id}" in routes
    assert "/api/v1/ohlcv/bulk" in routes

    # Quotes
    assert "/api/v1/quotes/{instrument_id}" in routes

    # Securities
    assert "/api/v1/securities" in routes


def test_readyz_returns_503_when_db_down() -> None:
    """GET /readyz returns 503 when the DB is unreachable.

    The lifespan runs on TestClient entry and sets app.state.session_factory to the
    real engine factory.  We overwrite the state *inside* the `with` block (after
    startup) so our error-raising mock takes effect for the readyz probe call.
    """
    from market_data.app import create_app

    app = create_app()

    mock_sf = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))
    mock_sf.return_value = mock_session

    mock_valkey = AsyncMock()
    mock_valkey.ping = AsyncMock(return_value=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        # Override state after lifespan startup so the mock is used by readyz
        app.state.session_factory = mock_sf
        app.state.valkey_client = mock_valkey
        app.state.object_storage = None
        resp = client.get("/readyz")

    assert resp.status_code == 503
