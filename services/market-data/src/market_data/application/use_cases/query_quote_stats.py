"""Quote-tab statistics use cases (B-Q-2 / B-Q-3 / B-Q-4).

Three read-only use cases that compute per-instrument statistics from data
already materialised in market_data_db (ohlcv_bars + instruments). They back
the instrument Quote tab's RETURNS / INTRADAY STATS / PRICE LEVELS strips.

Honesty contract (shared by all three):
  - Every statistic is ``None`` when the underlying history is insufficient —
    we NEVER fabricate a value (e.g. a 5Y return from 1Y of bars).
  - All computations are pure functions of the fetched bars; no external
    provider calls, no caching at this layer.

R27: all three use cases depend on ``ReadOnlyUnitOfWork`` (read replica).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from market_data.domain.enums import Timeframe
from market_data.domain.errors import InstrumentNotFoundError

if TYPE_CHECKING:
    from datetime import date

    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import OHLCVBar

# ── Shared helpers ────────────────────────────────────────────────────────────


def _f(value: Decimal | float | None) -> float | None:
    """Decimal → float for JSON responses; passes None through."""
    return float(value) if value is not None else None


def _pct(numerator: Decimal, denominator: Decimal) -> float:
    """Percentage change (numerator / denominator - 1) * 100, rounded to 4dp."""
    return round(float((numerator / denominator - Decimal("1")) * Decimal("100")), 4)


async def _require_instrument(uow: ReadOnlyUnitOfWork, instrument_id: str) -> Any:
    """Fetch the instrument or raise InstrumentNotFoundError (mapped to 404)."""
    instrument = await uow.instruments_read.find_by_id(instrument_id)
    if instrument is None:
        raise InstrumentNotFoundError(f"Instrument not found: {instrument_id}")
    return instrument


# ── B-Q-2: Intraday stats ─────────────────────────────────────────────────────

# Daily-bar fetch budget: 30 baseline sessions + the current session + buffer.
_INTRADAY_DAILY_LIMIT = 32
# Calendar look-back wide enough to always contain 31 trading sessions.
_INTRADAY_DAILY_CALENDAR_DAYS = 100


class GetIntradayStatsUseCase:
    """Compute current-session statistics from OHLCV bars.

    Session definition: the most recent 1d bar is "the session". Intraday
    (1m preferred, 5m fallback) bars belonging to that session's calendar
    date refine VWAP / high / low / open; the daily bar provides the
    authoritative volume and the prior bar the prev_close.

    WHY 1m-preferred VWAP: VWAP is sum(typical_price x volume)/sum(volume);
    finer bars yield a closer approximation of the true trade-weighted value.
    5m derived bars are the fallback when the 1m feed is absent for a symbol.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> dict[str, Any]:
        await _require_instrument(self._uow, instrument_id)

        now = datetime.now(tz=UTC)
        daily = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id,
            Timeframe.ONE_DAY,
            (now - timedelta(days=_INTRADAY_DAILY_CALENDAR_DAYS)).date(),
            now.date(),
            limit=_INTRADAY_DAILY_LIMIT,
        )

        if not daily:
            # Instrument exists but has no daily bars at all — return an
            # all-null (but well-shaped) payload rather than 404, so the
            # frontend renders "—" cells instead of an error state.
            return self._empty(instrument_id)

        latest = daily[-1]
        session_date = latest.bar_date.date()
        prev_close: Decimal | None = daily[-2].close if len(daily) >= 2 else None

        intraday, vwap_source = await self._session_intraday_bars(instrument_id, session_date)

        # VWAP — typical price (H+L+C)/3 weighted by per-bar volume.
        vwap: float | None = None
        vol_bars = [b for b in intraday if b.volume]
        total_vol = sum(b.volume for b in vol_bars if b.volume)
        if total_vol > 0:
            weighted = sum((b.high + b.low + b.close) / Decimal("3") * Decimal(b.volume) for b in vol_bars if b.volume)
            vwap = round(float(weighted / Decimal(total_vol)), 4)
        else:
            vwap_source = None

        # Session OHLV — prefer intraday refinement, fall back to the daily bar.
        if intraday:
            day_open = intraday[0].open
            day_high = max(b.high for b in intraday)
            day_low = min(b.low for b in intraday)
        else:
            day_open, day_high, day_low = latest.open, latest.high, latest.low

        # Volume: the daily bar's volume is authoritative (the resampler keeps
        # it current); cumulative intraday volume is the fallback.
        volume: int | None = latest.volume if latest.volume else (total_vol if total_vol > 0 else None)

        # 30-session average volume EXCLUDING the current session (it is
        # incomplete intraday and would deflate the baseline).
        baseline = [b.volume for b in daily[:-1] if b.volume]
        ratio: float | None = None
        if volume is not None and baseline:
            avg_30d = sum(baseline[-30:]) / len(baseline[-30:])
            if avg_30d > 0:
                ratio = round(volume / avg_30d, 4)

        return {
            "instrument_id": instrument_id,
            "session_date": session_date.isoformat(),
            "open": _f(day_open),
            "prev_close": _f(prev_close),
            "day_high": _f(day_high),
            "day_low": _f(day_low),
            "vwap": vwap,
            "vwap_source": vwap_source if vwap is not None else None,
            "volume": volume,
            "volume_vs_30d_ratio": ratio,
        }

    async def _session_intraday_bars(self, instrument_id: str, session_date: date) -> tuple[list[OHLCVBar], str | None]:
        """Return (bars, source_timeframe) for the session — 1m preferred, 5m fallback."""
        start = datetime(session_date.year, session_date.month, session_date.day, tzinfo=UTC)
        end = start + timedelta(days=1)
        for timeframe in (Timeframe.ONE_MIN, Timeframe.FIVE_MIN):
            bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_datetime_range(
                instrument_id, timeframe, start, end
            )
            if bars:
                return bars, timeframe.value
        return [], None

    @staticmethod
    def _empty(instrument_id: str) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "session_date": None,
            "open": None,
            "prev_close": None,
            "day_high": None,
            "day_low": None,
            "vwap": None,
            "vwap_source": None,
            "volume": None,
            "volume_vs_30d_ratio": None,
        }


# ── B-Q-3: Multi-period returns ───────────────────────────────────────────────

# Calendar-day offsets per period label. Calendar anchoring (latest bar at or
# before `as_of - offset`) is preferred over bar-count anchoring because it is
# immune to data gaps (halts, holidays, late backfills) silently shifting the
# measurement window.
_RETURN_PERIODS: tuple[tuple[str, int], ...] = (
    ("1W", 7),
    ("1M", 30),
    ("3M", 91),
    ("6M", 182),
    ("1Y", 365),
    ("3Y", 1095),
    ("5Y", 1825),
)

# 5Y of trading days (~1260) + generous buffer; repo pushes the LIMIT to the DB.
_RETURNS_BAR_LIMIT = 1320
_RETURNS_CALENDAR_DAYS = 2000


class GetMultiPeriodReturnsUseCase:
    """Compute close-on-close % returns over 1D/1W/1M/3M/6M/YTD/1Y/3Y/5Y.

    Anchor rule per period: the most recent daily close at or before
    ``as_of_date - offset``. A period is ``None`` when no bar that old exists
    (insufficient history) — never extrapolated.

    1D is the previous trading session's close (bar-count, not calendar — the
    previous close over a weekend is Friday's, which a 1-calendar-day anchor
    would miss). YTD anchors on the final close of the prior calendar year.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> dict[str, Any]:
        await _require_instrument(self._uow, instrument_id)

        now = datetime.now(tz=UTC)
        bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id,
            Timeframe.ONE_DAY,
            (now - timedelta(days=_RETURNS_CALENDAR_DAYS)).date(),
            now.date(),
            limit=_RETURNS_BAR_LIMIT,
        )

        labels = ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y")
        if len(bars) < 2:
            return {
                "instrument_id": instrument_id,
                "as_of": bars[-1].bar_date.date().isoformat() if bars else None,
                "returns": dict.fromkeys(labels),
            }

        last = bars[-1]
        last_close = last.close
        as_of_date = last.bar_date.date()
        returns: dict[str, float | None] = dict.fromkeys(labels)

        # 1D — previous trading session.
        prev = bars[-2]
        if prev.close > 0:
            returns["1D"] = _pct(last_close, prev.close)

        # Calendar-anchored periods.
        for label, offset_days in _RETURN_PERIODS:
            target = as_of_date - timedelta(days=offset_days)
            anchor = self._latest_at_or_before(bars, target)
            if anchor is not None and anchor.close > 0:
                returns[label] = _pct(last_close, anchor.close)

        # YTD — final close of the prior calendar year.
        jan_1 = as_of_date.replace(month=1, day=1)
        ytd_anchor = self._latest_at_or_before(bars, jan_1 - timedelta(days=1))
        if ytd_anchor is not None and ytd_anchor.close > 0:
            returns["YTD"] = _pct(last_close, ytd_anchor.close)

        return {
            "instrument_id": instrument_id,
            "as_of": as_of_date.isoformat(),
            "returns": returns,
        }

    @staticmethod
    def _latest_at_or_before(bars: list[OHLCVBar], target: date) -> OHLCVBar | None:
        """Most recent bar with bar_date <= target — bars are sorted ASC.

        Linear reverse scan is fine: <=1320 bars, and anchors near the tail
        (1W/1M) exit almost immediately.
        """
        for bar in reversed(bars):
            if bar.bar_date.date() <= target:
                return bar
        return None


# ── B-Q-4: Price levels ───────────────────────────────────────────────────────

# 52 trading weeks ≈ 252 sessions; fetch a little extra for the prior-session
# row and to tolerate boundary gaps.
_LEVELS_BAR_LIMIT = 260
_LEVELS_CALENDAR_DAYS = 380

# Swing-point detection parameters (see GetPriceLevelsUseCase docstring).
_SWING_WINDOW_BARS = 90
_SWING_FRACTAL_K = 2
_SWING_MAX_LEVELS = 3

_SR_METHOD = (
    f"fractal swing points (k={_SWING_FRACTAL_K}) over the last "
    f"{_SWING_WINDOW_BARS} daily bars; nearest {_SWING_MAX_LEVELS} swing "
    "lows below the last close = support, nearest swing highs above = resistance"
)


class GetPriceLevelsUseCase:
    """Compute 52-week range, MA50/MA200, prior-session H/L and simple S/R.

    Support/resistance method (intentionally simple and documented — no
    pretence of a proprietary signal): a *swing high* is a bar whose high is
    the strict maximum of the ±k-bar window around it (k=2 fractal); a *swing
    low* is the strict minimum analogue. Levels are deduplicated to 2dp;
    support = nearest swing lows strictly below the last close, resistance =
    nearest swing highs strictly above it, max 3 each, ordered
    nearest-to-price first.

    52w high/low are reported only when at least ~9 months (190 sessions) of
    bars exist; otherwise null — a "52-week high" computed over 3 months of
    history would be a lie.
    """

    # Minimum sessions for an honest 52-week range (~75% of a trading year).
    _MIN_BARS_FOR_52W = 190

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> dict[str, Any]:
        await _require_instrument(self._uow, instrument_id)

        now = datetime.now(tz=UTC)
        bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument_id,
            Timeframe.ONE_DAY,
            (now - timedelta(days=_LEVELS_CALENDAR_DAYS)).date(),
            now.date(),
            limit=_LEVELS_BAR_LIMIT,
        )

        if not bars:
            return self._empty(instrument_id)

        last = bars[-1]
        last_close = last.close
        as_of = last.bar_date.date().isoformat()

        # ── 52-week range (honest: only with enough history) ────────────────
        high_52w: float | None = None
        low_52w: float | None = None
        pct_from_high: float | None = None
        pct_from_low: float | None = None
        window = bars[-252:]
        if len(window) >= self._MIN_BARS_FOR_52W:
            hi = max(b.high for b in window)
            lo = min(b.low for b in window)
            high_52w = _f(hi)
            low_52w = _f(lo)
            if hi > 0:
                pct_from_high = _pct(last_close, hi)
            if lo > 0:
                pct_from_low = _pct(last_close, lo)

        # ── Moving averages — null when the full window doesn't exist ───────
        closes = [b.close for b in bars]
        ma_50 = round(float(sum(closes[-50:]) / Decimal("50")), 4) if len(closes) >= 50 else None
        ma_200 = round(float(sum(closes[-200:]) / Decimal("200")), 4) if len(closes) >= 200 else None

        # ── Prior session ────────────────────────────────────────────────────
        prior_high = _f(bars[-2].high) if len(bars) >= 2 else None
        prior_low = _f(bars[-2].low) if len(bars) >= 2 else None

        support, resistance = self._swing_levels(bars, last_close)

        return {
            "instrument_id": instrument_id,
            "as_of": as_of,
            "last_close": _f(last_close),
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pct_from_52w_high": pct_from_high,
            "pct_from_52w_low": pct_from_low,
            "ma_50": ma_50,
            "ma_200": ma_200,
            "prior_session_high": prior_high,
            "prior_session_low": prior_low,
            "support": support,
            "resistance": resistance,
            "sr_method": _SR_METHOD,
        }

    @staticmethod
    def _swing_levels(bars: list[OHLCVBar], last_close: Decimal) -> tuple[list[float], list[float]]:
        """Fractal swing-point S/R — see class docstring for the method."""
        window = bars[-_SWING_WINDOW_BARS:]
        k = _SWING_FRACTAL_K
        swing_highs: set[float] = set()
        swing_lows: set[float] = set()
        # Interior bars only — a fractal needs k neighbours on BOTH sides, so
        # the first/last k bars (incl. the current session) can never qualify.
        for i in range(k, len(window) - k):
            neighbourhood = window[i - k : i + k + 1]
            bar = window[i]
            if bar.high == max(b.high for b in neighbourhood) and (
                sum(1 for b in neighbourhood if b.high == bar.high) == 1
            ):
                swing_highs.add(round(float(bar.high), 2))
            if bar.low == min(b.low for b in neighbourhood) and (
                sum(1 for b in neighbourhood if b.low == bar.low) == 1
            ):
                swing_lows.add(round(float(bar.low), 2))

        close_f = float(last_close)
        # Nearest-first ordering: support descending (closest below price first),
        # resistance ascending (closest above price first).
        support = sorted((lv for lv in swing_lows if lv < close_f), reverse=True)[:_SWING_MAX_LEVELS]
        resistance = sorted(lv for lv in swing_highs if lv > close_f)[:_SWING_MAX_LEVELS]
        return support, resistance

    @staticmethod
    def _empty(instrument_id: str) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "as_of": None,
            "last_close": None,
            "high_52w": None,
            "low_52w": None,
            "pct_from_52w_high": None,
            "pct_from_52w_low": None,
            "ma_50": None,
            "ma_200": None,
            "prior_session_high": None,
            "prior_session_low": None,
            "support": [],
            "resistance": [],
            "sr_method": _SR_METHOD,
        }
