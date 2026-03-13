"""Unit tests for Instruments API (MD-022)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_uow
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


def _make_app(mock_uow: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(instruments.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    return app, TestClient(app)


def _make_read_repo(instruments_list: list[Instrument]) -> MagicMock:
    """Build a mock instruments_read repo that returns instruments_list from search() and count()."""
    repo = MagicMock()
    repo.search = AsyncMock(return_value=instruments_list)
    repo.count = AsyncMock(return_value=len(instruments_list))
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_symbol_exchange = AsyncMock(return_value=None)
    return repo


def test_list_instruments_returns_all() -> None:
    """GET /api/v1/instruments returns a paginated list."""
    items = [
        _make_instrument("i1", "AAPL"),
        _make_instrument("i2", "MSFT"),
    ]
    mock_uow = AsyncMock()
    mock_uow.instruments_read = _make_read_repo(items)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_list_instruments_filter_has_ohlcv() -> None:
    """Filtering by has_ohlcv is pushed to DB — mock returns only matching instruments."""
    # The router now delegates filtering to the DB: search() is called with has_ohlcv=True
    # and should return only matching rows. We simulate that by returning 1 result.
    items = [_make_instrument("i1", "AAPL", has_ohlcv=True)]
    mock_uow = AsyncMock()
    mock_uow.instruments_read = _make_read_repo(items)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments?has_ohlcv=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["symbol"] == "AAPL"

    # Verify filters were passed to the repo
    mock_uow.instruments_read.search.assert_called_once()
    call_kwargs = mock_uow.instruments_read.search.call_args.kwargs
    assert call_kwargs.get("has_ohlcv") is True


def test_get_instrument_by_id_found() -> None:
    """GET /api/v1/instruments/{id} returns the correct instrument."""
    instrument = _make_instrument("instr-001")
    mock_uow = AsyncMock()
    mock_uow.instruments_read = MagicMock()
    mock_uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments/instr-001")
    assert resp.status_code == 200
    assert resp.json()["id"] == "instr-001"
    assert resp.json()["symbol"] == "AAPL"


def test_get_instrument_by_id_not_found() -> None:
    """GET /api/v1/instruments/{id} returns 404 for unknown ID."""
    mock_uow = AsyncMock()
    mock_uow.instruments_read = MagicMock()
    mock_uow.instruments_read.find_by_id = AsyncMock(return_value=None)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments/nonexistent")
    assert resp.status_code == 404


def test_get_instrument_by_symbol_found() -> None:
    """GET /api/v1/instruments/symbol/{symbol} returns matching instrument."""
    instrument = _make_instrument("instr-002", symbol="TSLA", exchange="US")
    mock_uow = AsyncMock()
    mock_uow.instruments_read = MagicMock()
    mock_uow.instruments_read.find_by_symbol_exchange = AsyncMock(return_value=instrument)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments/symbol/TSLA?exchange=US")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "TSLA"


def test_get_instrument_by_symbol_not_found() -> None:
    """GET /api/v1/instruments/symbol/{symbol} returns 404 for unknown symbol."""
    mock_uow = AsyncMock()
    mock_uow.instruments_read = MagicMock()
    mock_uow.instruments_read.find_by_symbol_exchange = AsyncMock(return_value=None)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/instruments/symbol/UNKNOWN")
    assert resp.status_code == 404
