"""Unit tests for the Quote-tab statistics use cases (B-Q-2/3/4).

Covers query_quote_stats.py:
  - GetIntradayStatsUseCase: 404 path, no-bars empty payload, daily-only
    fallback, 1m VWAP + intraday refinement, 30d volume ratio.
  - GetMultiPeriodReturnsUseCase: 404 path, <2 bars → all-null, calendar
    anchoring, insufficient-history nulls (3Y/5Y), YTD anchor.
  - GetPriceLevelsUseCase: 404 path, empty payload, 52w range + honesty
    threshold, MA50/MA200 thresholds, prior session, fractal swing S/R.

All use a fake ReadOnlyUnitOfWork — no DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from market_data.application.use_cases.query_quote_stats import (
    GetIntradayStatsUseCase,
    GetMultiPeriodReturnsUseCase,
    GetPriceLevelsUseCase,
)
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.errors import InstrumentNotFoundError

pytestmark = pytest.mark.unit

_IID = "11111111-1111-1111-1111-111111111111"


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeInstrumentsRepo:
    def __init__(self, exists: bool = True) -> None:
        self._exists = exists

    async def find_by_id(self, instrument_id: str):
        return SimpleNamespace(id=instrument_id, symbol="TEST") if self._exists else None


class _FakeOhlcvRepo:
    """Returns canned bars keyed by timeframe; records the requested ranges."""

    def __init__(self, daily: list[OHLCVBar] | None = None, intraday: dict[Timeframe, list[OHLCVBar]] | None = None):
        self._daily = daily or []
        self._intraday = intraday or {}

    async def find_by_instrument_timeframe_range(self, instrument_id, timeframe, start, end, *, limit=None):
        assert timeframe == Timeframe.ONE_DAY
        bars = self._daily
        # Mirror the repo contract: most-recent `limit` bars, ASC order.
        return bars[-limit:] if limit else bars

    async def find_by_instrument_timeframe_datetime_range(self, instrument_id, timeframe, start_dt, end_dt):
        return self._intraday.get(timeframe, [])


class _FakeReadUoW:
    def __init__(self, instruments: _FakeInstrumentsRepo, ohlcv: _FakeOhlcvRepo) -> None:
        self.instruments_read = instruments
        self.ohlcv_read = ohlcv


def _daily_bar(
    bar_date: datetime,
    close: float,
    *,
    o: float | None = None,
    h: float | None = None,
    lo: float | None = None,
    volume: int = 1_000_000,
) -> OHLCVBar:
    """Build a 1d bar; high/low default to ±1 around close."""
    return OHLCVBar(
        instrument_id=_IID,
        timeframe=Timeframe.ONE_DAY,
        bar_date=bar_date,
        open=Decimal(str(o if o is not None else close - 0.5)),
        high=Decimal(str(h if h is not None else close + 1)),
        low=Decimal(str(lo if lo is not None else close - 1)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _trading_days_back(n: int) -> list[datetime]:
    """Return n weekday datetimes (UTC midnight) ending today (or last weekday)."""
    days: list[datetime] = []
    cursor = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor.weekday() >= 5:  # roll back off weekends
        cursor -= timedelta(days=1)
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


# ── GetIntradayStatsUseCase ───────────────────────────────────────────────────


async def test_intraday_stats_raises_for_unknown_instrument() -> None:
    uc = GetIntradayStatsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(exists=False), _FakeOhlcvRepo()))
    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(_IID)


async def test_intraday_stats_all_null_when_no_bars() -> None:
    uc = GetIntradayStatsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo()))
    result = await uc.execute(_IID)
    assert result["instrument_id"] == _IID
    assert result["session_date"] is None
    assert result["open"] is None
    assert result["vwap"] is None
    assert result["volume_vs_30d_ratio"] is None


async def test_intraday_stats_daily_only_fallback() -> None:
    """With no intraday bars, session OHLV comes from the latest daily bar."""
    days = _trading_days_back(3)
    daily = [
        _daily_bar(days[0], 100.0, volume=2_000_000),
        _daily_bar(days[1], 102.0, volume=2_000_000),
        _daily_bar(days[2], 105.0, o=103.0, h=106.0, lo=102.5, volume=1_000_000),
    ]
    uc = GetIntradayStatsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily)))
    result = await uc.execute(_IID)

    assert result["session_date"] == days[2].date().isoformat()
    assert result["open"] == pytest.approx(103.0)
    assert result["prev_close"] == pytest.approx(102.0)
    assert result["day_high"] == pytest.approx(106.0)
    assert result["day_low"] == pytest.approx(102.5)
    assert result["vwap"] is None
    assert result["vwap_source"] is None
    assert result["volume"] == 1_000_000
    # baseline = mean(2M, 2M) = 2M → ratio = 1M / 2M = 0.5
    assert result["volume_vs_30d_ratio"] == pytest.approx(0.5)


async def test_intraday_stats_vwap_from_1m_bars() -> None:
    """VWAP = Σ(typical x vol)/Σvol over 1m bars; intraday refines OHL."""
    days = _trading_days_back(2)
    session = days[-1]
    daily = [_daily_bar(days[0], 100.0), _daily_bar(session, 101.0, volume=500)]

    def _bar_1m(minute: int, h: float, lo: float, c: float, vol: int) -> OHLCVBar:
        return OHLCVBar(
            instrument_id=_IID,
            timeframe=Timeframe.ONE_MIN,
            bar_date=session + timedelta(hours=14, minutes=minute),
            open=Decimal(str(c)),
            high=Decimal(str(h)),
            low=Decimal(str(lo)),
            close=Decimal(str(c)),
            volume=vol,
        )

    # typical prices: (102+98+100)/3 = 100 ; (104+100+102)/3 = 102
    m1 = _bar_1m(0, 102.0, 98.0, 100.0, 100)
    m2 = _bar_1m(1, 104.0, 100.0, 102.0, 300)
    uc = GetIntradayStatsUseCase(
        _FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily, intraday={Timeframe.ONE_MIN: [m1, m2]}))
    )
    result = await uc.execute(_IID)

    # VWAP = (100*100 + 102*300) / 400 = 101.5
    assert result["vwap"] == pytest.approx(101.5)
    assert result["vwap_source"] == "1m"
    assert result["day_high"] == pytest.approx(104.0)  # refined from intraday
    assert result["day_low"] == pytest.approx(98.0)
    assert result["open"] == pytest.approx(100.0)  # first 1m bar open
    assert result["volume"] == 500  # daily bar volume is authoritative


async def test_intraday_stats_5m_fallback_when_no_1m() -> None:
    days = _trading_days_back(2)
    session = days[-1]
    daily = [_daily_bar(days[0], 100.0), _daily_bar(session, 101.0)]
    bar_5m = OHLCVBar(
        instrument_id=_IID,
        timeframe=Timeframe.FIVE_MIN,
        bar_date=session + timedelta(hours=14),
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=50,
    )
    uc = GetIntradayStatsUseCase(
        _FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily, intraday={Timeframe.FIVE_MIN: [bar_5m]}))
    )
    result = await uc.execute(_IID)
    assert result["vwap_source"] == "5m"
    assert result["vwap"] == pytest.approx(101.0)  # (103+99+101)/3


# ── GetMultiPeriodReturnsUseCase ──────────────────────────────────────────────


async def test_returns_raises_for_unknown_instrument() -> None:
    uc = GetMultiPeriodReturnsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(exists=False), _FakeOhlcvRepo()))
    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(_IID)


async def test_returns_all_null_with_insufficient_bars() -> None:
    days = _trading_days_back(1)
    uc = GetMultiPeriodReturnsUseCase(
        _FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=[_daily_bar(days[0], 100.0)]))
    )
    result = await uc.execute(_IID)
    assert set(result["returns"].keys()) == {"1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"}
    assert all(v is None for v in result["returns"].values())


async def test_returns_computed_and_long_periods_null() -> None:
    """~300 sessions: 1D..1Y computed; 3Y/5Y null (insufficient history)."""
    days = _trading_days_back(300)
    # Deterministic monotonic closes: 100, 100.1, 100.2, ...
    daily = [_daily_bar(d, 100.0 + i * 0.1) for i, d in enumerate(days)]
    uc = GetMultiPeriodReturnsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily)))
    result = await uc.execute(_IID)

    rets = result["returns"]
    last_close = 100.0 + 299 * 0.1
    prev_close = 100.0 + 298 * 0.1
    assert rets["1D"] == pytest.approx((last_close / prev_close - 1) * 100, abs=1e-3)
    for label in ("1W", "1M", "3M", "6M", "1Y"):
        assert rets[label] is not None, f"{label} should be computable from 300 sessions"
        assert rets[label] > 0  # monotonic series → positive returns
    # 300 weekday sessions span ~420 calendar days — 3Y/5Y anchors don't exist.
    assert rets["3Y"] is None
    assert rets["5Y"] is None
    assert result["as_of"] == days[-1].date().isoformat()


async def test_returns_ytd_anchor_is_prior_year_close() -> None:
    """YTD return anchors on the final close of the prior calendar year."""
    now = datetime.now(tz=UTC)
    prior_year_bar = _daily_bar(datetime(now.year - 1, 12, 30, tzinfo=UTC), 200.0)
    this_year_bar1 = _daily_bar(datetime(now.year, 1, 5, tzinfo=UTC), 210.0)
    this_year_bar2 = _daily_bar(datetime(now.year, 1, 6, tzinfo=UTC), 220.0)
    uc = GetMultiPeriodReturnsUseCase(
        _FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=[prior_year_bar, this_year_bar1, this_year_bar2]))
    )
    result = await uc.execute(_IID)
    assert result["returns"]["YTD"] == pytest.approx(10.0)  # 220/200 - 1


# ── GetPriceLevelsUseCase ─────────────────────────────────────────────────────


async def test_price_levels_raises_for_unknown_instrument() -> None:
    uc = GetPriceLevelsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(exists=False), _FakeOhlcvRepo()))
    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(_IID)


async def test_price_levels_empty_when_no_bars() -> None:
    uc = GetPriceLevelsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo()))
    result = await uc.execute(_IID)
    assert result["last_close"] is None
    assert result["support"] == []
    assert result["resistance"] == []
    assert "fractal swing points" in result["sr_method"]


async def test_price_levels_full_history() -> None:
    """260 sessions: 52w range, MA50/MA200, prior session and S/R populated."""
    days = _trading_days_back(260)
    daily = [_daily_bar(d, 100.0) for d in days]
    # Carve a swing high at -10 and a swing low at -20 (interior, k=2 clear).
    daily[-10] = _daily_bar(days[-10], 100.0, h=120.0)
    daily[-20] = _daily_bar(days[-20], 100.0, lo=80.0)
    uc = GetPriceLevelsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily)))
    result = await uc.execute(_IID)

    assert result["last_close"] == pytest.approx(100.0)
    assert result["high_52w"] == pytest.approx(120.0)
    assert result["low_52w"] == pytest.approx(80.0)
    # last_close 100 vs 52w high 120 → -16.667%; vs low 80 → +25%
    assert result["pct_from_52w_high"] == pytest.approx(-16.6667, abs=1e-3)
    assert result["pct_from_52w_low"] == pytest.approx(25.0, abs=1e-3)
    assert result["ma_50"] == pytest.approx(100.0)
    assert result["ma_200"] == pytest.approx(100.0)
    assert result["prior_session_high"] == pytest.approx(101.0)
    assert result["prior_session_low"] == pytest.approx(99.0)
    # The carved swing high (120) is the only level above last_close=100.
    assert 120.0 in result["resistance"]
    # The carved swing low (80) is below last_close.
    assert 80.0 in result["support"]
    assert len(result["support"]) <= 3
    assert len(result["resistance"]) <= 3


async def test_price_levels_52w_null_below_honesty_threshold() -> None:
    """<190 sessions → 52w range null, but MA50 still computable."""
    days = _trading_days_back(60)
    daily = [_daily_bar(d, 50.0) for d in days]
    uc = GetPriceLevelsUseCase(_FakeReadUoW(_FakeInstrumentsRepo(), _FakeOhlcvRepo(daily=daily)))
    result = await uc.execute(_IID)
    assert result["high_52w"] is None
    assert result["low_52w"] is None
    assert result["pct_from_52w_high"] is None
    assert result["ma_50"] == pytest.approx(50.0)
    assert result["ma_200"] is None  # only 60 bars
