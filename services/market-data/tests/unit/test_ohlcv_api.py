"""Unit tests for OHLCV API (MD-023)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_available_timeframes_uc,
    get_ohlcv_bars_uc,
    get_ohlcv_bulk_uc,
    get_ohlcv_range_uc,
)
from market_data.api.routers import ohlcv as ohlcv_router
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority

pytestmark = pytest.mark.unit

# Valid UUIDs for test data (instrument_id is UUID in prod)
_UUID_1 = "00000000-0000-0000-0000-000000000001"
_UUID_2 = "00000000-0000-0000-0000-000000000002"


def _make_bar(
    instrument_id: str = _UUID_1,
    timeframe: Timeframe = Timeframe.ONE_DAY,
    bar_date: datetime | None = None,
) -> OHLCVBar:
    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        bar_date=bar_date or datetime(2024, 1, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("102"),
        volume=1_000_000,
        adjusted_close=Decimal("102"),
        source="polygon",
        provider_priority=ProviderPriority(provider="polygon", priority=100),
        ingested_at=datetime.now(tz=UTC),
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(
    mock_bars_uc: MagicMock | None = None,
    mock_bulk_uc: MagicMock | None = None,
    mock_timeframes_uc: MagicMock | None = None,
    mock_range_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(ohlcv_router.router, prefix="/api/v1")

    if mock_bars_uc is not None:
        app.dependency_overrides[get_ohlcv_bars_uc] = lambda: mock_bars_uc
    if mock_bulk_uc is not None:
        app.dependency_overrides[get_ohlcv_bulk_uc] = lambda: mock_bulk_uc
    if mock_timeframes_uc is not None:
        app.dependency_overrides[get_available_timeframes_uc] = lambda: mock_timeframes_uc
    if mock_range_uc is not None:
        app.dependency_overrides[get_ohlcv_range_uc] = lambda: mock_range_uc

    return app, TestClient(app)


def _make_bars_uc(bars: list[OHLCVBar] | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=bars or [])
    return uc


def _make_bulk_uc(bars_per_instrument: list[list[OHLCVBar]] | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=bars_per_instrument or [])
    return uc


def _make_timeframes_uc(timeframes: list[Timeframe] | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=timeframes or [])
    return uc


def _make_range_uc(result: tuple[date, date, int] | None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def test_get_ohlcv_bars_returns_list() -> None:
    """GET /api/v1/ohlcv/{id} returns bars with Decimal-as-string."""
    _, client = _make_app(mock_bars_uc=_make_bars_uc([_make_bar(), _make_bar()]))
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["timeframe"] == "1d"
    assert data["items"][0]["open"] == "100"


def test_get_ohlcv_invalid_date_range_422() -> None:
    """start > end returns HTTP 422."""
    _, client = _make_app(mock_bars_uc=_make_bars_uc())
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}?start=2024-12-31&end=2024-01-01")
    assert resp.status_code == 422


def test_get_ohlcv_invalid_instrument_id_422() -> None:
    """Non-UUID instrument_id returns HTTP 422 (not 500 from DB layer)."""
    _, client = _make_app(mock_bars_uc=_make_bars_uc())
    for bad_id in ("ins-aapl", "not-a-uuid", "12345", "AAPL"):
        resp = client.get(f"/api/v1/ohlcv/{bad_id}")
        assert resp.status_code == 422, f"Expected 422 for instrument_id='{bad_id}'"


def test_get_available_timeframes() -> None:
    """GET /api/v1/ohlcv/{id}/timeframes returns list of timeframe strings."""
    _, client = _make_app(mock_timeframes_uc=_make_timeframes_uc([Timeframe.ONE_DAY, Timeframe.ONE_WEEK]))
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}/timeframes")
    assert resp.status_code == 200
    assert "1d" in resp.json()
    assert "1w" in resp.json()


def test_get_ohlcv_range_with_data() -> None:
    """GET /api/v1/ohlcv/{id}/range returns min/max dates."""
    _, client = _make_app(mock_range_uc=_make_range_uc((date(2024, 1, 1), date(2024, 6, 30), 1)))
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}/range?timeframe=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["min_date"] == "2024-01-01"
    assert data["max_date"] == "2024-06-30"
    assert data["count"] == 1


def test_get_ohlcv_range_no_data() -> None:
    """GET /api/v1/ohlcv/{id}/range returns nulls when no data exists."""
    _, client = _make_app(mock_range_uc=_make_range_uc(None))
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}/range")
    assert resp.status_code == 200
    data = resp.json()
    assert data["min_date"] is None
    assert data["count"] == 0


def test_get_ohlcv_invalid_timeframe_422() -> None:
    """Invalid timeframe string returns HTTP 422."""
    _, client = _make_app(mock_bars_uc=_make_bars_uc())
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}?timeframe=INVALID")
    assert resp.status_code == 422


def test_get_ohlcv_bulk() -> None:
    """GET /api/v1/ohlcv/bulk returns a list of OHLCVListResponse."""
    bars = [_make_bar()]
    # bulk returns one list per instrument_id
    _, client = _make_app(mock_bulk_uc=_make_bulk_uc([bars, bars]))
    resp = client.get(f"/api/v1/ohlcv/bulk?instrument_ids={_UUID_1}&instrument_ids={_UUID_2}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_get_ohlcv_bars_limit_param_accepted() -> None:
    """GET /api/v1/ohlcv/{id}?limit=30 is accepted and forwarded to use case."""
    uc = _make_bars_uc([_make_bar(), _make_bar()])
    _, client = _make_app(mock_bars_uc=uc)
    resp = client.get(f"/api/v1/ohlcv/{_UUID_1}?limit=30")
    assert resp.status_code == 200
    # The use case execute() should have been called with limit=30
    uc.execute.assert_awaited_once()
    _, call_kwargs = uc.execute.call_args
    assert call_kwargs.get("limit") == 30


def test_get_ohlcv_bars_limit_out_of_range_422() -> None:
    """limit=0 and limit=9999 both return HTTP 422 (validation guards)."""
    _, client = _make_app(mock_bars_uc=_make_bars_uc())
    assert client.get(f"/api/v1/ohlcv/{_UUID_1}?limit=0").status_code == 422
    assert client.get(f"/api/v1/ohlcv/{_UUID_1}?limit=9999").status_code == 422
