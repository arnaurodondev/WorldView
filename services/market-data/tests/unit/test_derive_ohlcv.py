"""Unit tests for DeriveOHLCVUseCase and GetOrDeriveOHLCVBarsUseCase.

All tests mock the UnitOfWork at the port-interface level so no real DB or
network I/O is required.  Each test is decorated with ``@pytest.mark.unit``
per project convention (PLAN-0036 W2-4/W2-5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.derive_ohlcv import DeriveOHLCVUseCase
from market_data.application.use_cases.get_or_derive_ohlcv import GetOrDeriveOHLCVBarsUseCase
from market_data.domain.entities import Instrument, OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_instrument(instrument_id: str = "instr-001", symbol: str = "AAPL", exchange: str = "US") -> Instrument:
    """Return a minimal Instrument domain object for testing."""
    return Instrument(
        id=instrument_id,
        security_id="sec-001",
        symbol=symbol,
        exchange=exchange,
    )


def _make_daily_bar(
    instrument_id: str,
    bar_date: datetime,
    open_: Decimal = Decimal("100"),
    high: Decimal = Decimal("110"),
    low: Decimal = Decimal("90"),
    close: Decimal = Decimal("105"),
    volume: int = 1_000,
) -> OHLCVBar:
    """Return a daily OHLCVBar with sensible defaults."""
    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=Timeframe.ONE_DAY,
        bar_date=bar_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        adjusted_close=None,
        source="polygon",
        provider_priority=ProviderPriority(provider="polygon", priority=100),
        is_derived=False,
    )


def _make_uow(
    instrument: Instrument | None = None,
    daily_bars: list[OHLCVBar] | None = None,
    derived_bars: list[OHLCVBar] | None = None,
    date_range: tuple | None = None,
) -> MagicMock:
    """Build a fully-mocked UoW that satisfies the ports used by the two use cases."""
    uow = MagicMock()

    # instruments_read
    instruments_read = MagicMock()
    instruments_read.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    uow.instruments_read = instruments_read

    # ohlcv_read
    ohlcv_read = MagicMock()
    ohlcv_read.get_date_range = AsyncMock(return_value=date_range)
    ohlcv_read.find_by_instrument_timeframe_range = AsyncMock(return_value=daily_bars or [])
    ohlcv_read.find_derived = AsyncMock(return_value=derived_bars or [])
    uow.ohlcv_read = ohlcv_read

    # ohlcv (write)
    ohlcv_write = MagicMock()
    ohlcv_write.bulk_upsert_derived = AsyncMock(return_value=None)
    uow.ohlcv = ohlcv_write

    # commit / rollback
    uow.commit = AsyncMock(return_value=None)
    uow.rollback = AsyncMock(return_value=None)

    return uow


# ── DeriveOHLCVUseCase tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_aggregation_correct_bars() -> None:
    """Two ISO weeks of daily bars → 2 weekly bars with correct OHLCV values."""
    instrument = _make_instrument()

    # Week 1: Mon 2024-01-01 to Fri 2024-01-05
    D = Decimal  # local alias
    iid = instrument.id

    def _bar(day: int, o: str, h: str, lo: str, c: str, v: int, month: int = 1) -> OHLCVBar:
        return _make_daily_bar(
            iid,
            datetime(2024, month, day, tzinfo=UTC),
            open_=D(o),
            high=D(h),
            low=D(lo),
            close=D(c),
            volume=v,
        )

    week1_bars = [
        _bar(1, "100", "102", "98", "101", 1000),
        _bar(2, "101", "108", "100", "107", 1200),
        _bar(3, "107", "110", "105", "106", 900),
        _bar(4, "106", "107", "103", "104", 800),
        _bar(5, "104", "106", "102", "105", 1100),
    ]
    # Week 2: Mon 2024-01-08 to Wed 2024-01-10
    week2_bars = [
        _bar(8, "105", "112", "104", "110", 1500),
        _bar(9, "110", "115", "109", "113", 1300),
        _bar(10, "113", "116", "111", "114", 1100),
    ]

    all_bars = week1_bars + week2_bars
    # date_range is a tuple of (date, date) — the repo returns date objects
    from datetime import date

    dr = (date(2024, 1, 1), date(2024, 1, 10))

    uow = _make_uow(instrument=instrument, daily_bars=all_bars, date_range=dr)
    uc = DeriveOHLCVUseCase(uow)
    count = await uc.execute(symbol="AAPL", exchange="US", target_timeframe="1w")

    assert count == 2

    # Verify the bars passed to bulk_upsert_derived
    uow.ohlcv.bulk_upsert_derived.assert_awaited_once()
    derived = uow.ohlcv.bulk_upsert_derived.call_args[0][0]

    # Week 1 bar
    w1 = derived[0]
    assert w1.open == Decimal("100")  # first day of week 1
    assert w1.high == Decimal("110")  # max high across all 5 days
    assert w1.low == Decimal("98")  # min low across all 5 days
    assert w1.close == Decimal("105")  # last day of week 1
    assert w1.volume == 5000  # sum of volumes
    assert w1.is_derived is True

    # Week 2 bar
    w2 = derived[1]
    assert w2.open == Decimal("105")
    assert w2.high == Decimal("116")
    assert w2.low == Decimal("104")
    assert w2.close == Decimal("114")
    assert w2.volume == 3900


@pytest.mark.asyncio
async def test_monthly_aggregation_correct_bars() -> None:
    """Daily bars across 2 months → 2 monthly bars with correct OHLCV."""
    instrument = _make_instrument()
    from datetime import date

    iid = instrument.id

    def _bar(month: int, day: int, o: str, h: str, lo: str, c: str, v: int) -> OHLCVBar:
        return _make_daily_bar(
            iid,
            datetime(2024, month, day, tzinfo=UTC),
            open_=Decimal(o),
            high=Decimal(h),
            low=Decimal(lo),
            close=Decimal(c),
            volume=v,
        )

    jan_bars = [
        _bar(1, 2, "100", "120", "95", "110", 2000),
        _bar(1, 31, "110", "115", "108", "112", 1800),
    ]
    feb_bars = [
        _bar(2, 1, "112", "125", "111", "122", 2500),
        _bar(2, 29, "122", "130", "120", "128", 2200),
    ]
    all_bars = jan_bars + feb_bars
    dr = (date(2024, 1, 2), date(2024, 2, 29))

    uow = _make_uow(instrument=instrument, daily_bars=all_bars, date_range=dr)
    uc = DeriveOHLCVUseCase(uow)
    count = await uc.execute(symbol="AAPL", exchange="US", target_timeframe="1M")

    assert count == 2
    derived = uow.ohlcv.bulk_upsert_derived.call_args[0][0]

    jan = derived[0]
    assert jan.open == Decimal("100")
    assert jan.high == Decimal("120")
    assert jan.low == Decimal("95")
    assert jan.close == Decimal("112")
    assert jan.volume == 3800

    feb = derived[1]
    assert feb.open == Decimal("112")
    assert feb.high == Decimal("130")
    assert feb.low == Decimal("111")
    assert feb.close == Decimal("128")
    assert feb.volume == 4700


@pytest.mark.asyncio
async def test_weekly_bar_date_is_monday() -> None:
    """Weekly derived bar's ``bar_date`` must be the Monday of the ISO week."""
    instrument = _make_instrument()
    from datetime import date

    # Wednesday 2024-01-03 — belongs to the week starting Monday 2024-01-01
    bars = [
        _make_daily_bar(instrument.id, datetime(2024, 1, 3, tzinfo=UTC)),
        _make_daily_bar(instrument.id, datetime(2024, 1, 4, tzinfo=UTC)),
    ]
    dr = (date(2024, 1, 3), date(2024, 1, 4))

    uow = _make_uow(instrument=instrument, daily_bars=bars, date_range=dr)
    uc = DeriveOHLCVUseCase(uow)
    await uc.execute(symbol="AAPL", exchange="US", target_timeframe="1w")

    derived = uow.ohlcv.bulk_upsert_derived.call_args[0][0]
    assert len(derived) == 1
    # bar_date should be Monday 2024-01-01 (UTC midnight)
    assert derived[0].bar_date == datetime(2024, 1, 1, tzinfo=UTC)
    # weekday() == 0 means Monday
    assert derived[0].bar_date.weekday() == 0


@pytest.mark.asyncio
async def test_monthly_bar_date_is_first() -> None:
    """Monthly derived bar's ``bar_date`` must be the 1st of the month."""
    instrument = _make_instrument()
    from datetime import date

    # Mid-month bars for March 2024
    bars = [
        _make_daily_bar(instrument.id, datetime(2024, 3, 15, tzinfo=UTC)),
        _make_daily_bar(instrument.id, datetime(2024, 3, 20, tzinfo=UTC)),
    ]
    dr = (date(2024, 3, 15), date(2024, 3, 20))

    uow = _make_uow(instrument=instrument, daily_bars=bars, date_range=dr)
    uc = DeriveOHLCVUseCase(uow)
    await uc.execute(symbol="AAPL", exchange="US", target_timeframe="1M")

    derived = uow.ohlcv.bulk_upsert_derived.call_args[0][0]
    assert len(derived) == 1
    # bar_date must be 2024-03-01 (first of month, UTC midnight)
    assert derived[0].bar_date == datetime(2024, 3, 1, tzinfo=UTC)
    assert derived[0].bar_date.day == 1


@pytest.mark.asyncio
async def test_empty_input_returns_zero() -> None:
    """No daily bars stored → derive returns 0 and writes nothing."""
    instrument = _make_instrument()
    # get_date_range returns None → no bars exist
    uow = _make_uow(instrument=instrument, daily_bars=[], date_range=None)
    uc = DeriveOHLCVUseCase(uow)
    count = await uc.execute(symbol="AAPL", exchange="US", target_timeframe="1w")

    assert count == 0
    uow.ohlcv.bulk_upsert_derived.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_input_instrument_not_found_returns_zero() -> None:
    """Instrument not found → derive returns 0 and writes nothing."""
    # instrument=None simulates a symbol that doesn't exist in the DB
    uow = _make_uow(instrument=None)
    uc = DeriveOHLCVUseCase(uow)
    count = await uc.execute(symbol="UNKNOWN", exchange="US", target_timeframe="1w")

    assert count == 0
    uow.ohlcv.bulk_upsert_derived.assert_not_awaited()


# ── GetOrDeriveOHLCVBarsUseCase tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_or_derive_passthrough_for_daily() -> None:
    """Timeframe '1d' → no derivation triggered; bars returned directly from repo."""
    instrument = _make_instrument()
    from datetime import date

    daily_bar = _make_daily_bar(instrument.id, datetime(2024, 1, 2, tzinfo=UTC))
    dr = (date(2024, 1, 2), date(2024, 1, 2))

    uow = _make_uow(instrument=instrument, daily_bars=[daily_bar], date_range=dr)
    uc = GetOrDeriveOHLCVBarsUseCase(uow)
    result = await uc.execute(symbol="AAPL", exchange="US", timeframe="1d")

    # bulk_upsert_derived must NOT have been called (no derivation for 1d)
    uow.ohlcv.bulk_upsert_derived.assert_not_awaited()
    # find_derived must NOT have been called either
    uow.ohlcv_read.find_derived.assert_not_awaited()
    # Result contains the bar from direct fetch
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_or_derive_cache_hit() -> None:
    """Enough derived weekly bars exist → no re-derivation; derived bars returned."""
    instrument = _make_instrument()
    # Create 200 fake derived bars (equal to the default limit)
    derived = [
        OHLCVBar(
            instrument_id=instrument.id,
            timeframe=Timeframe.ONE_WEEK,
            bar_date=datetime(2024, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=5000,
            source="derived",
            provider_priority=ProviderPriority(provider="unknown", priority=0),
            is_derived=True,
        )
    ] * 200  # 200 bars satisfies the default limit=200

    uow = _make_uow(instrument=instrument, derived_bars=derived)
    uc = GetOrDeriveOHLCVBarsUseCase(uow)
    result = await uc.execute(symbol="AAPL", exchange="US", timeframe="1w", limit=200)

    # No derivation should have been triggered
    uow.ohlcv.bulk_upsert_derived.assert_not_awaited()
    assert len(result) == 200


@pytest.mark.asyncio
async def test_get_or_derive_triggers_derivation_on_miss() -> None:
    """Fewer derived bars than limit → DeriveOHLCVUseCase is triggered, then re-fetch."""
    instrument = _make_instrument()
    from datetime import date

    # Only 3 derived bars exist (well below limit=10)
    existing_derived = [
        OHLCVBar(
            instrument_id=instrument.id,
            timeframe=Timeframe.ONE_WEEK,
            bar_date=datetime(2024, 1, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=5000,
            source="derived",
            provider_priority=ProviderPriority(provider="unknown", priority=0),
            is_derived=True,
        )
    ] * 3

    # The derive pass will produce 2 new bars (re-fetch returns 5 total)
    refreshed_derived = (
        existing_derived
        + [
            OHLCVBar(
                instrument_id=instrument.id,
                timeframe=Timeframe.ONE_WEEK,
                bar_date=datetime(2024, 1, 8, tzinfo=UTC),
                open=Decimal("105"),
                high=Decimal("115"),
                low=Decimal("103"),
                close=Decimal("112"),
                volume=6000,
                source="derived",
                provider_priority=ProviderPriority(provider="unknown", priority=0),
                is_derived=True,
            )
        ]
        * 2
    )

    # 10 daily source bars for the derivation pass
    daily_bars = [_make_daily_bar(instrument.id, datetime(2024, 1, i, tzinfo=UTC)) for i in range(1, 11)]
    dr = (date(2024, 1, 1), date(2024, 1, 10))

    # find_derived is called twice: first returns 3 (miss), second returns 5 (after derive)
    uow = _make_uow(instrument=instrument, daily_bars=daily_bars, date_range=dr)
    uow.ohlcv_read.find_derived = AsyncMock(side_effect=[existing_derived, refreshed_derived])

    uc = GetOrDeriveOHLCVBarsUseCase(uow)
    result = await uc.execute(symbol="AAPL", exchange="US", timeframe="1w", limit=10)

    # bulk_upsert_derived was called (derivation happened)
    uow.ohlcv.bulk_upsert_derived.assert_awaited_once()
    # Final result is the re-fetched refreshed bars
    assert len(result) == 5
