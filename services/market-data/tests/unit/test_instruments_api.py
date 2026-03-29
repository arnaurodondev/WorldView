"""Unit tests for Instruments API (MD-022)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_instrument_by_id_uc,
    get_instrument_by_symbol_uc,
    get_search_instruments_uc,
)
from market_data.api.routers import instruments
from market_data.domain.entities import Instrument
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit


def _make_instrument(
    instrument_id: str = "instr-001",
    symbol: str = "AAPL",
    exchange: str = "US",
    has_ohlcv: bool = True,
    has_quotes: bool = False,
    has_fundamentals: bool = False,
) -> Instrument:
    return Instrument(
        id=instrument_id,
        security_id="sec-001",
        symbol=symbol,
        exchange=exchange,
        flags=InstrumentFlags(has_ohlcv=has_ohlcv, has_quotes=has_quotes, has_fundamentals=has_fundamentals),
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(
    mock_get_by_id: AsyncMock | None = None,
    mock_get_by_symbol: AsyncMock | None = None,
    mock_search: AsyncMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(instruments.router, prefix="/api/v1")

    if mock_get_by_id is not None:
        app.dependency_overrides[get_instrument_by_id_uc] = lambda: mock_get_by_id
    if mock_get_by_symbol is not None:
        app.dependency_overrides[get_instrument_by_symbol_uc] = lambda: mock_get_by_symbol
    if mock_search is not None:
        app.dependency_overrides[get_search_instruments_uc] = lambda: mock_search

    return app, TestClient(app)


def _make_get_by_id_uc(result: Instrument | None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def _make_get_by_symbol_uc(result: Instrument | None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def _make_search_uc(items: list[Instrument]) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=(len(items), items))
    return uc


def test_list_instruments_returns_all() -> None:
    """GET /api/v1/instruments returns a paginated list."""
    items = [
        _make_instrument("i1", "AAPL"),
        _make_instrument("i2", "MSFT"),
    ]
    _, client = _make_app(mock_search=_make_search_uc(items))
    resp = client.get("/api/v1/instruments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_list_instruments_filter_has_ohlcv() -> None:
    """Filtering by has_ohlcv is pushed through to the use case."""
    items = [_make_instrument("i1", "AAPL", has_ohlcv=True)]
    mock_uc = _make_search_uc(items)
    _, client = _make_app(mock_search=mock_uc)

    resp = client.get("/api/v1/instruments?has_ohlcv=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["symbol"] == "AAPL"

    mock_uc.execute.assert_called_once()
    call_kwargs = mock_uc.execute.call_args.kwargs
    assert call_kwargs.get("has_ohlcv") is True


def test_get_instrument_by_id_found() -> None:
    """GET /api/v1/instruments/{id} returns the correct instrument."""
    instrument = _make_instrument("instr-001")
    _, client = _make_app(mock_get_by_id=_make_get_by_id_uc(instrument))
    resp = client.get("/api/v1/instruments/instr-001")
    assert resp.status_code == 200
    assert resp.json()["id"] == "instr-001"
    assert resp.json()["symbol"] == "AAPL"


def test_get_instrument_by_id_not_found() -> None:
    """GET /api/v1/instruments/{id} returns 404 for unknown ID."""
    _, client = _make_app(mock_get_by_id=_make_get_by_id_uc(None))
    resp = client.get("/api/v1/instruments/nonexistent")
    assert resp.status_code == 404


def test_get_instrument_by_symbol_found() -> None:
    """GET /api/v1/instruments/symbol/{symbol} returns matching instrument."""
    instrument = _make_instrument("instr-002", symbol="TSLA", exchange="US")
    _, client = _make_app(mock_get_by_symbol=_make_get_by_symbol_uc(instrument))
    resp = client.get("/api/v1/instruments/symbol/TSLA?exchange=US")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "TSLA"


def test_get_instrument_by_symbol_not_found() -> None:
    """GET /api/v1/instruments/symbol/{symbol} returns 404 for unknown symbol."""
    _, client = _make_app(mock_get_by_symbol=_make_get_by_symbol_uc(None))
    resp = client.get("/api/v1/instruments/symbol/UNKNOWN")
    assert resp.status_code == 404
