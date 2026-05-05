"""Unit tests for Instruments API (MD-022).

PLAN-0073 Wave B-1: Updated to use the new /instruments/lookup endpoint that
replaces the removed /instruments/{id} and /instruments/symbol/{symbol} routes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_lookup_instrument_uc,
    get_search_instruments_uc,
)
from market_data.api.routers import instruments
from market_data.application.use_cases.lookup_instrument import InstrumentLookupResult
from market_data.domain.entities import Instrument
from market_data.domain.errors import InstrumentNotFoundError
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
    mock_lookup: AsyncMock | None = None,
    mock_search: AsyncMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(instruments.router, prefix="/api/v1")

    if mock_lookup is not None:
        app.dependency_overrides[get_lookup_instrument_uc] = lambda: mock_lookup
    if mock_search is not None:
        app.dependency_overrides[get_search_instruments_uc] = lambda: mock_search

    return app, TestClient(app)


def _make_lookup_uc_found(instrument: Instrument) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=InstrumentLookupResult(instrument=instrument, security=None))
    return uc


def _make_lookup_uc_not_found() -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=InstrumentNotFoundError("not found"))
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


_VALID_UUID = "018e8e8e-0000-7000-b000-000000000001"


def test_get_instrument_by_id_found() -> None:
    """GET /api/v1/instruments/lookup?id=<uuid> returns the correct instrument."""
    instrument = _make_instrument(_VALID_UUID)
    _, client = _make_app(mock_lookup=_make_lookup_uc_found(instrument))
    resp = client.get(f"/api/v1/instruments/lookup?id={_VALID_UUID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == _VALID_UUID
    assert resp.json()["symbol"] == "AAPL"


def test_get_instrument_by_id_not_found() -> None:
    """GET /api/v1/instruments/lookup?id=<uuid> returns 404 for unknown ID."""
    _, client = _make_app(mock_lookup=_make_lookup_uc_not_found())
    resp = client.get(f"/api/v1/instruments/lookup?id={_VALID_UUID}")
    assert resp.status_code == 404


def test_get_instrument_by_symbol_found() -> None:
    """GET /api/v1/instruments/lookup?symbol=<symbol> returns matching instrument."""
    instrument = _make_instrument("instr-002", symbol="TSLA", exchange="US")
    _, client = _make_app(mock_lookup=_make_lookup_uc_found(instrument))
    resp = client.get("/api/v1/instruments/lookup?symbol=TSLA")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "TSLA"


def test_get_instrument_by_symbol_not_found() -> None:
    """GET /api/v1/instruments/lookup?symbol=<symbol> returns 404 for unknown symbol."""
    _, client = _make_app(mock_lookup=_make_lookup_uc_not_found())
    resp = client.get("/api/v1/instruments/lookup?symbol=UNKNOWN")
    assert resp.status_code == 404


def test_lookup_no_params_returns_400() -> None:
    """GET /api/v1/instruments/lookup without params returns 400."""
    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=ValueError("At least one param required"))
    _, client = _make_app(mock_lookup=uc)
    resp = client.get("/api/v1/instruments/lookup")
    assert resp.status_code == 400
