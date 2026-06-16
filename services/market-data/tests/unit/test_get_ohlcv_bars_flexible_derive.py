"""Unit tests for GetOHLCVBarsFlexibleUseCase query-time weekly/monthly derivation.

P0b: weekly (``week``/``1w``) and monthly (``month``/``1mo``/``1M``) intervals are
DERIVED on the fly from stored daily bars — no provider polling, no storage growth,
no write-on-read.  These tests assert correct ISO-week/calendar-month bucketing,
alias handling, and that the daily/intraday direct path is unaffected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from market_data.application.use_cases.get_ohlcv_bars_flexible import GetOHLCVBarsFlexibleUseCase
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority

pytestmark = pytest.mark.unit

_IID = str(uuid4())


def _bar(d: date, o: float, h: float, low: float, c: float, vol: int) -> OHLCVBar:
    return OHLCVBar(
        instrument_id=_IID,
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


def _uow_with_daily(daily: list[OHLCVBar]) -> MagicMock:
    uow = MagicMock()
    uow.ohlcv_read = MagicMock()
    uow.ohlcv_read.find_by_instrument_timeframe_range = AsyncMock(return_value=daily)
    return uow


# Two ISO weeks of daily bars.
# Week of Mon 2024-01-01..Fri 2024-01-05; week of Mon 2024-01-08..Tue 2024-01-09.
_WEEK1 = [
    _bar(date(2024, 1, 1), 100, 110, 95, 105, 10),
    _bar(date(2024, 1, 2), 105, 112, 100, 108, 20),
    _bar(date(2024, 1, 5), 108, 120, 90, 115, 30),
]
_WEEK2 = [
    _bar(date(2024, 1, 8), 115, 118, 111, 116, 40),
    _bar(date(2024, 1, 9), 116, 130, 114, 128, 50),
]


@pytest.mark.asyncio
async def test_weekly_derivation_buckets_by_iso_week() -> None:
    uow = _uow_with_daily(_WEEK1 + _WEEK2)
    uc = GetOHLCVBarsFlexibleUseCase(uow)

    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 1, 9), interval="week")  # type: ignore[arg-type]

    assert out["bar_count"] == 2
    w1, w2 = out["bars"]
    # Bucket anchored to Monday of the ISO week.
    assert w1["date"] == "2024-01-01"
    assert w2["date"] == "2024-01-08"
    # open=first, close=last, high=max, low=min, volume=sum.
    assert w1["open"] == 100.0
    assert w1["close"] == 115.0
    assert w1["high"] == 120.0
    assert w1["low"] == 90.0
    assert w1["volume"] == 60
    assert w2["open"] == 115.0
    assert w2["close"] == 128.0
    assert w2["high"] == 130.0
    assert w2["low"] == 111.0
    assert w2["volume"] == 90


@pytest.mark.asyncio
async def test_monthly_derivation_buckets_by_calendar_month() -> None:
    daily = [
        _bar(date(2024, 1, 3), 100, 110, 95, 105, 10),
        _bar(date(2024, 1, 31), 105, 125, 90, 120, 20),
        _bar(date(2024, 2, 1), 120, 122, 118, 121, 30),
        _bar(date(2024, 2, 15), 121, 140, 100, 135, 40),
    ]
    uow = _uow_with_daily(daily)
    uc = GetOHLCVBarsFlexibleUseCase(uow)

    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 2, 28), interval="month")  # type: ignore[arg-type]

    assert out["bar_count"] == 2
    jan, feb = out["bars"]
    assert jan["date"] == "2024-01-01"
    assert feb["date"] == "2024-02-01"
    assert jan["open"] == 100.0 and jan["close"] == 120.0
    assert jan["high"] == 125.0 and jan["low"] == 90.0 and jan["volume"] == 30
    assert feb["open"] == 120.0 and feb["close"] == 135.0
    assert feb["high"] == 140.0 and feb["low"] == 100.0 and feb["volume"] == 70


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["1w", "week"])
async def test_weekly_aliases_both_derive(alias: str) -> None:
    uow = _uow_with_daily(_WEEK1)
    uc = GetOHLCVBarsFlexibleUseCase(uow)
    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 1, 5), interval=alias)  # type: ignore[arg-type]
    assert out["bar_count"] == 1
    # Derivation fetches DAILY bars regardless of the requested weekly alias.
    call = uow.ohlcv_read.find_by_instrument_timeframe_range.call_args
    assert call.args[1] == Timeframe.ONE_DAY


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["1mo", "month", "1M"])
async def test_monthly_aliases_both_derive(alias: str) -> None:
    daily = [
        _bar(date(2024, 1, 3), 100, 110, 95, 105, 10),
        _bar(date(2024, 1, 31), 105, 125, 90, 120, 20),
    ]
    uow = _uow_with_daily(daily)
    uc = GetOHLCVBarsFlexibleUseCase(uow)
    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 1, 31), interval=alias)  # type: ignore[arg-type]
    assert out["bar_count"] == 1
    assert out["bars"][0]["date"] == "2024-01-01"
    call = uow.ohlcv_read.find_by_instrument_timeframe_range.call_args
    assert call.args[1] == Timeframe.ONE_DAY


@pytest.mark.asyncio
async def test_empty_daily_returns_empty_derived() -> None:
    uow = _uow_with_daily([])
    uc = GetOHLCVBarsFlexibleUseCase(uow)
    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 6, 30), interval="week")  # type: ignore[arg-type]
    assert out == {"bars": [], "bar_count": 0}


@pytest.mark.asyncio
async def test_max_bars_tail_slices_derived() -> None:
    uow = _uow_with_daily(_WEEK1 + _WEEK2)
    uc = GetOHLCVBarsFlexibleUseCase(uow)
    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 1, 9), interval="week", max_bars=1)  # type: ignore[arg-type]
    # Newest week only.
    assert out["bar_count"] == 1
    assert out["bars"][0]["date"] == "2024-01-08"


@pytest.mark.asyncio
async def test_daily_path_unaffected_no_derivation() -> None:
    daily = _WEEK1
    uow = _uow_with_daily(daily)
    uc = GetOHLCVBarsFlexibleUseCase(uow)
    out = await uc.execute(_IID, date(2024, 1, 1), date(2024, 1, 5), interval="day")  # type: ignore[arg-type]
    # Direct read: one row per daily bar, no aggregation.
    assert out["bar_count"] == 3
    call = uow.ohlcv_read.find_by_instrument_timeframe_range.call_args
    assert call.args[1] == Timeframe.ONE_DAY
