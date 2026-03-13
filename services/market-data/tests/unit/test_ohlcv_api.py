"""Unit tests for OHLCV API (MD-023)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_uow
from market_data.api.routers import ohlcv as ohlcv_router
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority

pytestmark = pytest.mark.unit


def _make_bar(
    instrument_id: str = "instr-001",
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


def _make_app(mock_uow: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(ohlcv_router.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    return app, TestClient(app)


def _make_ohlcv_read_repo(bars: list[OHLCVBar] | None = None) -> MagicMock:
    """Build a mock ohlcv_read repo."""
    repo = MagicMock()
    repo.find_by_instrument_timeframe_range = AsyncMock(return_value=bars or [])
    repo.get_available_timeframes = AsyncMock(return_value=[])
    repo.get_date_range = AsyncMock(return_value=None)
    return repo


def test_get_ohlcv_bars_returns_list() -> None:
    """GET /api/v1/ohlcv/{id} returns bars with Decimal-as-string."""
    mock_uow = AsyncMock()
    mock_uow.ohlcv_read = _make_ohlcv_read_repo(bars=[_make_bar(), _make_bar()])

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["timeframe"] == "1d"
    assert data["items"][0]["open"] == "100"


def test_get_ohlcv_invalid_date_range_422() -> None:
    """start > end returns HTTP 422."""
    mock_uow = AsyncMock()
    mock_uow.ohlcv_read = _make_ohlcv_read_repo()

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001?start=2024-12-31&end=2024-01-01")
    assert resp.status_code == 422


def test_get_available_timeframes() -> None:
    """GET /api/v1/ohlcv/{id}/timeframes returns list of timeframe strings."""
    mock_uow = AsyncMock()
    repo = _make_ohlcv_read_repo()
    repo.get_available_timeframes = AsyncMock(return_value=[Timeframe.ONE_DAY, Timeframe.ONE_WEEK])
    mock_uow.ohlcv_read = repo

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001/timeframes")
    assert resp.status_code == 200
    assert "1d" in resp.json()
    assert "1w" in resp.json()


def test_get_ohlcv_range_with_data() -> None:
    """GET /api/v1/ohlcv/{id}/range returns min/max dates."""
    mock_uow = AsyncMock()
    repo = _make_ohlcv_read_repo(bars=[_make_bar()])
    repo.get_date_range = AsyncMock(return_value=(date(2024, 1, 1), date(2024, 6, 30)))
    mock_uow.ohlcv_read = repo

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001/range?timeframe=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["min_date"] == "2024-01-01"
    assert data["max_date"] == "2024-06-30"
    assert data["count"] == 1


def test_get_ohlcv_range_no_data() -> None:
    """GET /api/v1/ohlcv/{id}/range returns nulls when no data exists."""
    mock_uow = AsyncMock()
    repo = _make_ohlcv_read_repo()
    repo.get_date_range = AsyncMock(return_value=None)
    mock_uow.ohlcv_read = repo

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001/range")
    assert resp.status_code == 200
    data = resp.json()
    assert data["min_date"] is None
    assert data["count"] == 0


def test_get_ohlcv_invalid_timeframe_422() -> None:
    """Invalid timeframe string returns HTTP 422."""
    mock_uow = AsyncMock()
    mock_uow.ohlcv_read = _make_ohlcv_read_repo()

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/instr-001?timeframe=INVALID")
    assert resp.status_code == 422


def test_get_ohlcv_bulk() -> None:
    """GET /api/v1/ohlcv/bulk returns a list of OHLCVListResponse."""
    mock_uow = AsyncMock()
    mock_uow.ohlcv_read = _make_ohlcv_read_repo(bars=[_make_bar()])

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/ohlcv/bulk?instrument_ids=instr-001&instrument_ids=instr-002")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
