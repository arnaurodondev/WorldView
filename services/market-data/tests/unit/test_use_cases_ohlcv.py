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
async def test_get_ohlcv_bars_limit_forwarded_to_repo() -> None:
    """limit= is forwarded to the repository as a keyword arg (DB-side pushdown).

    WHY: the use case no longer slices in Python — it delegates the limit to the
    repository via ``find_by_instrument_timeframe_range(..., limit=N)``.  The repo
    performs ``ORDER BY bar_date DESC LIMIT N`` and reverses to ASC.  At this unit
    test level the mock returns whatever it was configured with, so we only verify
    that the use case passes ``limit=`` through rather than post-processing the
    full list.
    """
    from datetime import UTC, datetime
    from decimal import Decimal

    from market_data.domain.value_objects import ProviderPriority

    # The mock repo returns the last 3 bars (simulating the DB-side limit).
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
        for d in range(3, 6)  # bars 3, 4, 5 — simulating DB returning newest 3
    ]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31), limit=3)
    # Use case must return exactly what the repo returned (no extra slicing).
    assert result == bars
    # Verify the limit was forwarded to the repo via keyword arg.
    uow.ohlcv_read.find_by_instrument_timeframe_range.assert_called_once()
    call_kwargs = uow.ohlcv_read.find_by_instrument_timeframe_range.call_args.kwargs
    assert call_kwargs.get("limit") == 3


@pytest.mark.asyncio
async def test_get_ohlcv_bars_default_limit_forwarded() -> None:
    """Default limit=200 is forwarded to the repository."""
    bars = [_make_bar()]
    uow = _make_uow(bars=bars)
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-001", Timeframe.ONE_DAY, date(2024, 1, 1), date(2024, 12, 31))
    assert result == bars
    call_kwargs = uow.ohlcv_read.find_by_instrument_timeframe_range.call_args.kwargs
    assert call_kwargs.get("limit") == 200


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


# ── PATH endpoint weekly/monthly derivation (chart 5Y/MAX path) ────────────────


def _daily(instrument_id: str, d: date, o: float, h: float, low: float, c: float, vol: int) -> OHLCVBar:
    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=Timeframe.ONE_DAY,
        bar_date=datetime(d.year, d.month, d.day, tzinfo=UTC),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
        volume=vol,
        source="eodhd",
        provider_priority=ProviderPriority(provider="eodhd", priority=50),
        ingested_at=datetime.now(tz=UTC),
    )


@pytest.mark.asyncio
async def test_get_ohlcv_bars_derives_weekly_from_daily() -> None:
    """timeframe=ONE_WEEK derives ISO-week bars in-memory from daily bars.

    This is the PATH endpoint the quote chart's 5Y/MAX view calls
    (S9 GET /v1/ohlcv/{id}?timeframe=1w).
    """
    iid = "instr-week"
    daily = [
        _daily(iid, date(2024, 1, 1), 100, 110, 95, 105, 10),  # Mon
        _daily(iid, date(2024, 1, 5), 105, 120, 90, 115, 30),  # Fri (same ISO week)
        _daily(iid, date(2024, 1, 8), 115, 130, 111, 128, 50),  # next Mon
    ]
    uow = _make_uow(bars=daily)
    uc = GetOHLCVBarsUseCase(uow)

    result = await uc.execute(iid, Timeframe.ONE_WEEK, date(2024, 1, 1), date(2024, 1, 8))

    assert len(result) == 2
    w1, w2 = result
    assert w1.timeframe == Timeframe.ONE_WEEK and w1.is_derived
    assert w1.bar_date.date() == date(2024, 1, 1)
    assert float(w1.open) == 100.0 and float(w1.close) == 115.0
    assert float(w1.high) == 120.0 and float(w1.low) == 90.0
    assert w2.bar_date.date() == date(2024, 1, 8)
    # Daily bars were fetched (ONE_DAY), not weekly.
    assert uow.ohlcv_read.find_by_instrument_timeframe_range.call_args.args[1] == Timeframe.ONE_DAY


@pytest.mark.asyncio
async def test_get_ohlcv_bars_derives_monthly_from_daily() -> None:
    """timeframe=ONE_MONTH derives calendar-month bars in-memory from daily bars."""
    iid = "instr-month"
    daily = [
        _daily(iid, date(2024, 1, 3), 100, 110, 95, 105, 10),
        _daily(iid, date(2024, 1, 31), 105, 125, 90, 120, 20),
        _daily(iid, date(2024, 2, 15), 121, 140, 100, 135, 40),
    ]
    uow = _make_uow(bars=daily)
    uc = GetOHLCVBarsUseCase(uow)

    result = await uc.execute(iid, Timeframe.ONE_MONTH, date(2024, 1, 1), date(2024, 2, 28))

    assert len(result) == 2
    jan, feb = result
    assert jan.timeframe == Timeframe.ONE_MONTH and jan.is_derived
    assert jan.bar_date.date() == date(2024, 1, 1)
    assert float(jan.high) == 125.0 and float(jan.low) == 90.0
    assert feb.bar_date.date() == date(2024, 2, 1)


@pytest.mark.asyncio
async def test_get_ohlcv_bars_weekly_empty_when_no_daily() -> None:
    uow = _make_uow(bars=[])
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute("instr-x", Timeframe.ONE_WEEK, date(2024, 1, 1), date(2024, 6, 30))
    assert result == []


@pytest.mark.asyncio
async def test_get_ohlcv_bars_weekly_tail_slice_limit() -> None:
    iid = "instr-lim"
    daily = [
        _daily(iid, date(2024, 1, 1), 100, 110, 95, 105, 10),
        _daily(iid, date(2024, 1, 8), 115, 130, 111, 128, 50),
        _daily(iid, date(2024, 1, 15), 128, 135, 120, 130, 60),
    ]
    uow = _make_uow(bars=daily)
    uc = GetOHLCVBarsUseCase(uow)
    result = await uc.execute(iid, Timeframe.ONE_WEEK, date(2024, 1, 1), date(2024, 1, 15), limit=1)
    assert len(result) == 1
    assert result[0].bar_date.date() == date(2024, 1, 15)  # most recent week
