"""Unit tests for fundamental metrics query use cases."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
from market_data.application.use_cases.query_fundamental_metrics import (
    GetAvailableFundamentalMetricsUseCase,
    GetFundamentalMetricsTimeseriesUseCase,
    ScreenInstrumentsUseCase,
)

pytestmark = pytest.mark.unit


def _make_data_point(as_of: date = date(2024, 1, 1)) -> MetricDataPoint:
    return MetricDataPoint(
        as_of_date=as_of,
        value_numeric=Decimal("15.5"),
        value_text=None,
        period_type="ANNUAL",
    )


def _make_uow(
    timeseries: list[MetricDataPoint] | None = None,
    screen_results: list[ScreenResult] | None = None,
    screen_total: int | None = None,
    metrics: list[str] | None = None,
) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.get_timeseries = AsyncMock(return_value=timeseries or [])
    result_list = screen_results or []
    total_count = screen_total if screen_total is not None else len(result_list)
    repo.screen = AsyncMock(return_value=(result_list, total_count))
    repo.get_available_metrics = AsyncMock(return_value=metrics or [])
    uow.fundamental_metrics_query = repo
    return uow


# ── GetFundamentalMetricsTimeseriesUseCase ─────────────────────────────────────


@pytest.mark.asyncio
async def test_timeseries_returns_data_points() -> None:
    points = [_make_data_point(date(2024, 1, 1)), _make_data_point(date(2024, 6, 30))]
    uow = _make_uow(timeseries=points)
    uc = GetFundamentalMetricsTimeseriesUseCase(uow)
    result = await uc.execute("instr-001", "pe_ratio")
    assert result == points


@pytest.mark.asyncio
async def test_timeseries_forwards_optional_params() -> None:
    uow = _make_uow(timeseries=[])
    uc = GetFundamentalMetricsTimeseriesUseCase(uow)
    await uc.execute(
        "instr-001",
        "pe_ratio",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        period_type="ANNUAL",
        limit=50,
    )
    uow.fundamental_metrics_query.get_timeseries.assert_awaited_once_with(
        "instr-001",
        "pe_ratio",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        period_type="ANNUAL",
        limit=50,
    )


@pytest.mark.asyncio
async def test_timeseries_empty_result() -> None:
    uow = _make_uow(timeseries=[])
    uc = GetFundamentalMetricsTimeseriesUseCase(uow)
    result = await uc.execute("instr-001", "revenue_ttm")
    assert result == []


# ── ScreenInstrumentsUseCase ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screen_returns_results() -> None:
    results = [
        ScreenResult(instrument_id="instr-001", metrics={"pe_ratio": Decimal("14.0")}),
        ScreenResult(instrument_id="instr-002", metrics={"pe_ratio": Decimal("17.0")}),
    ]
    uow = _make_uow(screen_results=results, screen_total=2)
    uc = ScreenInstrumentsUseCase(uow)
    filters = [ScreenFilter(metric="pe_ratio", max_value=Decimal("20.0"))]
    result_list, total = await uc.execute(filters)
    assert result_list == results
    assert total == 2


@pytest.mark.asyncio
async def test_screen_forwards_limit_offset() -> None:
    uow = _make_uow(screen_results=[])
    uc = ScreenInstrumentsUseCase(uow)
    filters = [ScreenFilter(metric="roe_ttm", min_value=Decimal("0.15"))]
    await uc.execute(filters, limit=25, offset=50)
    uow.fundamental_metrics_query.screen.assert_awaited_once_with(
        filters,
        limit=25,
        offset=50,
        sort_by=None,
        sort_order="asc",
    )


@pytest.mark.asyncio
async def test_screen_empty_results() -> None:
    uow = _make_uow(screen_results=[])
    uc = ScreenInstrumentsUseCase(uow)
    filters = [ScreenFilter(metric="pe_ratio", max_value=Decimal("1.0"))]
    result_list, total = await uc.execute(filters)
    assert result_list == []
    assert total == 0


# ── GetAvailableFundamentalMetricsUseCase ─────────────────────────────────────


@pytest.mark.asyncio
async def test_available_metrics_returns_names() -> None:
    metrics = ["pe_ratio", "target_price", "revenue_ttm"]
    uow = _make_uow(metrics=metrics)
    uc = GetAvailableFundamentalMetricsUseCase(uow)
    result = await uc.execute("instr-001")
    assert set(result) == set(metrics)
    uow.fundamental_metrics_query.get_available_metrics.assert_awaited_once_with("instr-001")


@pytest.mark.asyncio
async def test_available_metrics_empty_instrument() -> None:
    uow = _make_uow(metrics=[])
    uc = GetAvailableFundamentalMetricsUseCase(uow)
    result = await uc.execute("unknown-instr")
    assert result == []
