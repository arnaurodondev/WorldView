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

    # Instruments (PLAN-0073 Wave B-1: old /symbol/{symbol} and /{id} replaced by /lookup)
    assert "/api/v1/instruments" in routes
    assert "/api/v1/instruments/lookup" in routes
    assert "/api/v1/instruments/on-demand-profile" in routes

    # OHLCV
    assert "/api/v1/ohlcv/{instrument_id}" in routes
    assert "/api/v1/ohlcv/bulk" in routes

    # Quotes
    assert "/api/v1/quotes/{instrument_id}" in routes

    # Securities
    assert "/api/v1/securities" in routes


def test_static_screen_fields_have_constraint_compatible_field_type() -> None:
    """Every static ScreenFieldMetadata must have field_type in {'numeric','text'}.

    Regression test for BP-585 (PLAN-0098 W3): the DB check constraint
    `ck_screen_field_metadata_field_type` only allows 'numeric' or 'text'.
    Previously `has_fundamentals` and `has_ohlcv` used 'boolean', which caused
    a CheckViolation every ~60s during the periodic refresh.
    """
    from market_data.app import _get_static_screen_fields

    fields = _get_static_screen_fields()
    assert fields, "expected at least one static screen field"
    for field in fields:
        assert field.field_type in {"numeric", "text"}, (
            f"field {field.name!r} has invalid field_type={field.field_type!r} "
            "(must be 'numeric' or 'text' per ck_screen_field_metadata_field_type)"
        )


def test_readyz_returns_503_when_db_down() -> None:
    """GET /readyz returns 503 when the DB is unreachable.

    Uses the null lifespan to avoid real JWKS fetch (F-003: startup now raises
    RuntimeError on failure).  Injects error-raising DB mock after startup.
    """
    app = _make_test_app()

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
