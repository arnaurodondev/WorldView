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


# ── TestScreenInstrumentsUseCase (edge cases) ─────────────────────────────────


class TestScreenInstrumentsUseCase:
    """Edge-case tests for ScreenInstrumentsUseCase."""

    @pytest.mark.asyncio
    async def test_screen_with_empty_filters_returns_all(self) -> None:
        """Calling with filters=[] must forward an empty list to repo.screen."""
        uow = _make_uow(screen_results=[], screen_total=0)
        uc = ScreenInstrumentsUseCase(uow)

        await uc.execute([])

        uow.fundamental_metrics_query.screen.assert_awaited_once_with(
            [],
            limit=50,
            offset=0,
            sort_by=None,
            sort_order="asc",
        )

    @pytest.mark.asyncio
    async def test_screen_with_conflicting_filters(self) -> None:
        """A filter where min_value > max_value must be forwarded to the repo.

        The use case itself does not validate range logic; it is the repo or
        API layer's responsibility.  The use case must not raise on conflicting
        filters — it should return whatever the repo returns (empty list).
        """
        uow = _make_uow(screen_results=[], screen_total=0)
        uc = ScreenInstrumentsUseCase(uow)

        conflicting = [ScreenFilter(metric="pe_ratio", min_value=Decimal("100"), max_value=Decimal("1"))]
        result_list, total = await uc.execute(conflicting)

        # Use case must not raise — just pass through to repo
        assert result_list == []
        assert total == 0
        uow.fundamental_metrics_query.screen.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_screen_forwards_limit_and_offset(self) -> None:
        """limit and offset must be forwarded exactly to repo.screen."""
        uow = _make_uow(screen_results=[], screen_total=0)
        uc = ScreenInstrumentsUseCase(uow)

        await uc.execute([], limit=50, offset=10)

        uow.fundamental_metrics_query.screen.assert_awaited_once_with(
            [],
            limit=50,
            offset=10,
            sort_by=None,
            sort_order="asc",
        )

    @pytest.mark.asyncio
    async def test_screen_with_none_optional_params(self) -> None:
        """None values for sort_by must be forwarded as None (not omitted or coerced)."""
        uow = _make_uow(screen_results=[], screen_total=0)
        uc = ScreenInstrumentsUseCase(uow)

        await uc.execute([], sort_by=None)

        call_kwargs = uow.fundamental_metrics_query.screen.call_args
        assert call_kwargs.kwargs.get("sort_by") is None


# ── TestGetFundamentalMetricsTimeseriesUseCase (edge cases) ──────────────────


class TestGetFundamentalMetricsTimeseriesUseCase:
    """Edge-case tests for GetFundamentalMetricsTimeseriesUseCase."""

    @pytest.mark.asyncio
    async def test_timeseries_with_none_optional_params(self) -> None:
        """None start_date and end_date must be forwarded as None to the repo."""
        uow = _make_uow(timeseries=[])
        uc = GetFundamentalMetricsTimeseriesUseCase(uow)

        await uc.execute("instr-001", "pe_ratio", start_date=None, end_date=None)

        uow.fundamental_metrics_query.get_timeseries.assert_awaited_once_with(
            "instr-001",
            "pe_ratio",
            start_date=None,
            end_date=None,
            period_type=None,
            limit=1000,
        )

    @pytest.mark.asyncio
    async def test_timeseries_preserves_param_types(self) -> None:
        """date params must be forwarded as-is without type coercion."""
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        uow = _make_uow(timeseries=[])
        uc = GetFundamentalMetricsTimeseriesUseCase(uow)

        await uc.execute("instr-001", "revenue_ttm", start_date=start, end_date=end, limit=500)

        call = uow.fundamental_metrics_query.get_timeseries.call_args
        # Verify types are preserved — not cast to strings or other types
        assert call.kwargs["start_date"] is start
        assert call.kwargs["end_date"] is end
        assert isinstance(call.kwargs["limit"], int)
        assert call.kwargs["limit"] == 500
