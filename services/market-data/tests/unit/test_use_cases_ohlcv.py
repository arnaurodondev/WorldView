"""Unit tests for OHLCV query use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_ohlcv import (
    GetAvailableTimeframesUseCase,
    GetOHLCVBarsUseCase,
    GetOHLCVBulkUseCase,
    GetOHLCVRangeUseCase,
)
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority

pytestmark = pytest.mark.unit


def _make_bar(instrument_id: str = "instr-001") -> OHLCVBar:
    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=Timeframe.ONE_DAY,
        bar_date=datetime(2024, 1, 15, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("102"),
        volume=1_000_000,
        adjusted_close=None,
        source="polygon",
        provider_priority=ProviderPriority(provider="polygon", priority=100),
        ingested_at=datetime(2024, 1, 16, tzinfo=UTC),
    )


def _make_uow(
    bars: list[OHLCVBar] | None = None,
    timeframes: list[Timeframe] | None = None,
    date_range: tuple[date, date] | None = None,
) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_instrument_timeframe_range = AsyncMock(return_value=bars or [])
    repo.find_by_instrument_timeframe_datetime_range = AsyncMock(return_value=bars or [])
    repo.get_available_timeframes = AsyncMock(return_value=timeframes or [])
    repo.get_date_range = AsyncMock(return_value=date_range)
    uow.ohlcv_read = repo
    return uow


@pytest.mark.asyncio
async def test_get_ohlcv_bars() -> None:
    bars = [_make_bar()]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31))
    assert result == bars


@pytest.mark.asyncio
async def test_get_ohlcv_bars_empty() -> None:
    uow = _make_uow(bars=[])
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31))
    assert result == []


@pytest.mark.asyncio
async def test_get_ohlcv_bars_limit_trims_to_newest() -> None:
    """limit= returns the last N bars (newest), not the first N."""
    # Create 5 bars with distinct dates so we can verify tail-slice semantics.
    from datetime import UTC, datetime

    bars = [
        _make_bar("instr-001")._replace(bar_date=datetime(2024, 1, d, tzinfo=UTC))  # type: ignore[call-arg]
        if hasattr(_make_bar("instr-001"), "_replace")
        else _make_bar("instr-001")
        for d in range(1, 6)
    ]
    # Rebuild with distinct bar_dates using the OHLCVBar dataclass directly.
    from decimal import Decimal

    from market_data.domain.value_objects import ProviderPriority

    bars = [
        OHLCVBar(
            instrument_id="instr-001",
            timeframe=Timeframe.ONE_DAY,
            bar_date=datetime(2024, 1, d, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("102"),
            volume=1_000_000,
            adjusted_close=None,
            source="polygon",
            provider_priority=ProviderPriority(provider="polygon", priority=100),
            ingested_at=datetime(2024, 1, 16, tzinfo=UTC),
        )
        for d in range(1, 6)
    ]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBarsUseCase(uow)
    # Ask for only the last 3 bars — should return bars 3, 4, 5 (newest)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31), limit=3)
    assert len(result) == 3
    # The tail slice must be the chronologically newest bars (indices 2, 3, 4)
    assert result[0].bar_date == bars[2].bar_date
    assert result[-1].bar_date == bars[4].bar_date


@pytest.mark.asyncio
async def test_get_ohlcv_bars_limit_larger_than_result_returns_all() -> None:
    """When limit > available bars, all bars are returned (no truncation)."""
    bars = [_make_bar()]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31), limit=1000)
    assert result == bars


@pytest.mark.asyncio
async def test_get_ohlcv_bulk_returns_list_per_instrument() -> None:
    bars = [_make_bar("instr-001")]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBulkUseCase(uow)
    result = await uc.execute(["instr-001", "instr-002"], Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31))
    assert len(result) == 2
    assert result[0] == bars
    assert result[1] == bars  # both get the same bars from the mock


@pytest.mark.asyncio
async def test_get_available_timeframes() -> None:
    uow = _make_uow(timeframes=[Timeframe.ONE_DAY, Timeframe.ONE_WEEK])
    uc = GetAvailableTimeframesUseCase(uow)
    result = await uc.execute("instr-001")
    assert Timeframe.ONE_DAY in result
    assert Timeframe.ONE_WEEK in result


@pytest.mark.asyncio
async def test_get_ohlcv_range_with_data() -> None:
    bars = [_make_bar()]
    uow = _make_uow(bars=bars, date_range=(date(2024, 1, 1), date(2024, 6, 30)))
    uc = GetOHLCVRangeUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY)
    assert result is not None
    min_d, max_d, count = result
    assert min_d == date(2024, 1, 1)
    assert max_d == date(2024, 6, 30)
    assert count == 1


@pytest.mark.asyncio
async def test_get_ohlcv_range_no_data() -> None:
    uow = _make_uow(date_range=None)
    uc = GetOHLCVRangeUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY)
    assert result is None
