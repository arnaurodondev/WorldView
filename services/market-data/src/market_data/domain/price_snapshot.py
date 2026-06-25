"""PriceSnapshotResolver — pure domain service for resolving a PriceSnapshot.

This module is infrastructure-free: it accepts pre-fetched domain entities as
parameters and returns a PriceSnapshot without touching the DB, Valkey, or any
I/O boundary.

Fallback priority chain (descending preference):
  1. FRESH_QUOTE      — quotes table, age < 5 min  → LIVE
  2. BULK_QUOTE       — quotes table, 5-15 min      -> RECENT
  3. INTRADAY_5M_CLOSE — latest 5m bar, age < 1h   → RECENT
  4. INTRADAY_1H_CLOSE — latest 1h bar, age < 24h  → DELAYED / LIVE (off-hours)
  5. DAILY_CLOSE      — latest 1d bar               → DELAYED / LIVE (off-hours)
  6. STALE_SNAPSHOT   — prior Valkey snapshot        → STALE
  7. UNAVAILABLE      — nothing found               → UNAVAILABLE, price=Decimal("0")

Market-hours-aware freshness classification:
  - 24/7 exchanges (CC, FOREX): pure age thresholds, no market-hours concept.
  - Off market hours for other exchanges: daily close (and quotes) are LIVE
    because that IS the authoritative price while markets are closed.
  - During market hours: strict age-based thresholds apply.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from contracts.canonical.price_snapshot import (  # type: ignore[import-untyped]
    FreshnessStatus,
    PriceSnapshot,
    PriceSource,
)
from market_data.domain.enums import Timeframe

if TYPE_CHECKING:
    from market_data.domain.entities import OHLCVBar, Quote

# ── Market-hours constants ────────────────────────────────────────────────────

# 24/7 exchange codes — freshness is always time-based, no "market hours" concept.
_ALWAYS_OPEN_EXCHANGES: frozenset[str] = frozenset({"CC", "FOREX"})

# NYSE/NASDAQ approximate session in UTC - covers both EST (14:30-21:00) and
# EDT (13:30-20:00).  We use the wider window (13:30-21:00 UTC) to avoid
# false "market closed" readings during edge hours.
_MARKET_OPEN_UTC_HOUR_MIN: tuple[int, int] = (13, 30)  # 13:30 UTC
_MARKET_CLOSE_UTC_HOUR_MIN: tuple[int, int] = (21, 0)  # 21:00 UTC

# Age thresholds (seconds)
_FRESH_QUOTE_MAX_AGE_SEC = 300  # 5 min
_BULK_QUOTE_MAX_AGE_SEC = 900  # 15 min
_INTRADAY_5M_MAX_AGE_SEC = 3600  # 1 hour
_INTRADAY_1H_MAX_AGE_SEC = 86400  # 24 hours


def _is_market_hours(dt: datetime, exchange: str) -> bool:
    """Return True if ``dt`` (UTC-aware) falls within approximate market hours.

    24/7 exchanges (CC, FOREX) are always considered open.  All other
    exchanges use the NYSE/NASDAQ approximate window: 13:30-21:00 UTC.
    """
    if exchange in _ALWAYS_OPEN_EXCHANGES:
        return True

    # Convert to UTC minutes-since-midnight for comparison
    utc_dt = dt.astimezone(UTC)
    minutes = utc_dt.hour * 60 + utc_dt.minute

    open_minutes = _MARKET_OPEN_UTC_HOUR_MIN[0] * 60 + _MARKET_OPEN_UTC_HOUR_MIN[1]
    close_minutes = _MARKET_CLOSE_UTC_HOUR_MIN[0] * 60 + _MARKET_CLOSE_UTC_HOUR_MIN[1]

    return open_minutes <= minutes < close_minutes


def classify_freshness(
    source: PriceSource,
    price_timestamp: datetime,
    resolved_at: datetime,
    exchange: str,
) -> FreshnessStatus:
    """Market-hours-aware freshness classification.

    Args:
        source:          The PriceSource that produced the price.
        price_timestamp: UTC datetime when the underlying price was valid.
        resolved_at:     UTC datetime when resolution happened (= now).
        exchange:        Exchange code used to detect 24/7 markets.

    Returns:
        FreshnessStatus enum member.
    """
    age = (resolved_at - price_timestamp).total_seconds()
    is_mkt_hours = _is_market_hours(resolved_at, exchange)

    # ── 24/7 exchanges — pure time-based, no market-hours concept ────────────
    if exchange in _ALWAYS_OPEN_EXCHANGES:
        if age < _FRESH_QUOTE_MAX_AGE_SEC:
            return FreshnessStatus.LIVE
        if age < _INTRADAY_5M_MAX_AGE_SEC:
            return FreshnessStatus.RECENT
        if age < _INTRADAY_1H_MAX_AGE_SEC:
            return FreshnessStatus.DELAYED
        return FreshnessStatus.STALE

    # ── Off market hours — daily close IS the live authoritative price ────────
    if not is_mkt_hours:
        # Fresh/bulk quote and daily close are the correct "live" price outside hours.
        if source in (PriceSource.DAILY_CLOSE, PriceSource.FRESH_QUOTE, PriceSource.BULK_QUOTE):
            return FreshnessStatus.LIVE
        # Intraday bars are still "recent" if within a day
        if age < _INTRADAY_1H_MAX_AGE_SEC:
            return FreshnessStatus.RECENT
        return FreshnessStatus.STALE

    # ── During market hours — strict age-based thresholds ────────────────────
    if age < _FRESH_QUOTE_MAX_AGE_SEC:
        return FreshnessStatus.LIVE
    if age < _BULK_QUOTE_MAX_AGE_SEC:
        return FreshnessStatus.RECENT
    if age < _INTRADAY_1H_MAX_AGE_SEC:
        return FreshnessStatus.DELAYED
    return FreshnessStatus.STALE


def _latest_bar(bars: list[OHLCVBar], timeframe: Timeframe) -> OHLCVBar | None:
    """Return the most recent bar for the given timeframe, or None."""
    matching = [b for b in bars if b.timeframe == timeframe]
    if not matching:
        return None
    # bar_date is the bar's timestamp — take the latest
    return max(matching, key=lambda b: b.bar_date)


def _prev_daily_close(bars: list[OHLCVBar], latest: OHLCVBar) -> Decimal | None:
    """Return the close of the second-most-recent 1d bar (i.e., previous session's close).

    Used to compute price_change and price_change_pct vs prior close.
    Returns None when fewer than two 1d bars are available.
    """
    candidates = sorted(
        [b for b in bars if b.timeframe == Timeframe.ONE_DAY and b.bar_date < latest.bar_date],
        key=lambda b: b.bar_date,
        reverse=True,
    )
    return candidates[0].close if candidates else None


def _prior_session_close(bars: list[OHLCVBar], price_timestamp: datetime) -> Decimal | None:
    """Return the close of the latest 1d bar from a session BEFORE ``price_timestamp``'s day.

    2026-06-10 day-change fix (frontend audit "+0.00% everywhere"): the quote
    and intraday resolution paths never passed ``prev_close`` into ``_build``,
    so every FRESH_QUOTE / BULK_QUOTE / INTRADAY_5M / INTRADAY_1H snapshot
    carried ``price_change=None`` — which S9 coerces to ``0.0`` for the
    frontend Quote shape. Only the DAILY_CLOSE path computed a real change.

    WHY date comparison (not ``bar_date < price_timestamp``): derived 1d bars
    are floored to midnight UTC of the session they belong to, so a price taken
    DURING session day D must be compared against the close of the latest bar
    strictly BEFORE day D — comparing raw timestamps would wrongly select day
    D's own (partial) bar as the "previous close" and report a near-zero change.

    Returns None when no earlier-session 1d bar exists (e.g. only one session
    ingested) — the snapshot then truthfully reports ``price_change=None``
    ("unknown") instead of a fake 0.00.
    """
    ref_day = price_timestamp.astimezone(UTC).date()
    candidates = sorted(
        [b for b in bars if b.timeframe == Timeframe.ONE_DAY and b.bar_date.astimezone(UTC).date() < ref_day],
        key=lambda b: b.bar_date,
        reverse=True,
    )
    return candidates[0].close if candidates else None


class PriceSnapshotResolver:
    """Pure domain service — resolves the best available PriceSnapshot.

    Accepts pre-fetched domain entities (Quote and OHLCVBar instances) and
    walks the fallback chain to produce the richest, freshest PriceSnapshot.

    No I/O: callers are responsible for fetching the data.  This keeps the
    domain layer infrastructure-free and trivially testable.

    Usage::

        resolver = PriceSnapshotResolver()
        snapshot = resolver.resolve(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            quote=quote,          # from QuoteRepository, may be None
            ohlcv_bars=bars,      # from OHLCVRepository, may be []
            resolved_at=utc_now(),
            prior_snapshot=cached,  # from Valkey, may be None
        )
    """

    def resolve(
        self,
        instrument_id: str,
        symbol: str,
        exchange: str,
        quote: Quote | None,
        ohlcv_bars: list[OHLCVBar],
        resolved_at: datetime,
        prior_snapshot: PriceSnapshot | None = None,
    ) -> PriceSnapshot:
        """Walk the fallback chain and return the best available PriceSnapshot.

        Args:
            instrument_id:   UUIDv7 of the instrument.
            symbol:          Ticker symbol.
            exchange:        Exchange code.
            quote:           Latest Quote entity from the DB, or None.
            ohlcv_bars:      List of recent OHLCVBar entities (any timeframes).
            resolved_at:     UTC-aware datetime for age calculations.
            prior_snapshot:  A stale PriceSnapshot from Valkey, used as last resort.

        Returns:
            A PriceSnapshot — never None.  Falls back to UNAVAILABLE if all
            sources are absent.
        """
        # ── Step 1 & 2: Check quote freshness ────────────────────────────────
        if quote is not None and quote.last is not None:
            age = (resolved_at - quote.timestamp).total_seconds()

            if age < _FRESH_QUOTE_MAX_AGE_SEC:
                # FRESH_QUOTE: < 5 min old
                source = PriceSource.FRESH_QUOTE
                price = quote.last
                price_timestamp = quote.timestamp
                freshness = classify_freshness(source, price_timestamp, resolved_at, exchange)
                return self._build(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange=exchange,
                    price=price,
                    price_timestamp=price_timestamp,
                    resolved_at=resolved_at,
                    source=source,
                    freshness=freshness,
                    stale_reason=None,
                    # Day-change fix (2026-06-10): compare against the prior
                    # session's daily close so price_change is non-null on the
                    # quote path (was always None → rendered as +0.00%).
                    prev_close=_prior_session_close(ohlcv_bars, price_timestamp),
                    # B-Q bid/ask plumbing (2026-06-10): only quote-sourced
                    # snapshots carry order-book context (see contract docstring).
                    bid=quote.bid,
                    ask=quote.ask,
                )

            if age < _BULK_QUOTE_MAX_AGE_SEC:
                # BULK_QUOTE: 5-15 min old
                source = PriceSource.BULK_QUOTE
                price = quote.last
                price_timestamp = quote.timestamp
                freshness = classify_freshness(source, price_timestamp, resolved_at, exchange)
                return self._build(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange=exchange,
                    price=price,
                    price_timestamp=price_timestamp,
                    resolved_at=resolved_at,
                    source=source,
                    freshness=freshness,
                    stale_reason=None,
                    # Day-change fix (2026-06-10): see FRESH_QUOTE path above.
                    prev_close=_prior_session_close(ohlcv_bars, price_timestamp),
                    # B-Q bid/ask plumbing (2026-06-10): a 5-15 min old bid/ask
                    # is still actionable order-book context; older quotes never
                    # reach this branch.
                    bid=quote.bid,
                    ask=quote.ask,
                )

        # ── Step 3: Try 5-minute OHLCV bar ───────────────────────────────────
        bar_5m = _latest_bar(ohlcv_bars, Timeframe.FIVE_MIN)
        if bar_5m is not None:
            age = (resolved_at - bar_5m.bar_date).total_seconds()
            if age < _INTRADAY_5M_MAX_AGE_SEC:
                source = PriceSource.INTRADAY_5M_CLOSE
                freshness = classify_freshness(source, bar_5m.bar_date, resolved_at, exchange)
                return self._build(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange=exchange,
                    price=bar_5m.close,
                    price_timestamp=bar_5m.bar_date,
                    resolved_at=resolved_at,
                    source=source,
                    freshness=freshness,
                    stale_reason=None,
                    # Day-change fix (2026-06-10): intraday price vs prior session close.
                    prev_close=_prior_session_close(ohlcv_bars, bar_5m.bar_date),
                )

        # ── Step 4: Try 1-hour OHLCV bar ─────────────────────────────────────
        bar_1h = _latest_bar(ohlcv_bars, Timeframe.ONE_HOUR)
        if bar_1h is not None:
            age = (resolved_at - bar_1h.bar_date).total_seconds()
            if age < _INTRADAY_1H_MAX_AGE_SEC:
                source = PriceSource.INTRADAY_1H_CLOSE
                freshness = classify_freshness(source, bar_1h.bar_date, resolved_at, exchange)
                return self._build(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange=exchange,
                    price=bar_1h.close,
                    price_timestamp=bar_1h.bar_date,
                    resolved_at=resolved_at,
                    source=source,
                    freshness=freshness,
                    stale_reason=None,
                    # Day-change fix (2026-06-10): intraday price vs prior session close.
                    prev_close=_prior_session_close(ohlcv_bars, bar_1h.bar_date),
                )

        # ── Step 5: Try daily OHLCV bar (no age limit — EOD is always valid) ─
        bar_1d = _latest_bar(ohlcv_bars, Timeframe.ONE_DAY)
        if bar_1d is not None:
            source = PriceSource.DAILY_CLOSE
            freshness = classify_freshness(source, bar_1d.bar_date, resolved_at, exchange)
            stale_reason = (
                f"Daily close from {bar_1d.bar_date.date().isoformat()}"
                if freshness in (FreshnessStatus.STALE, FreshnessStatus.DELAYED)
                else None
            )
            return self._build(
                instrument_id=instrument_id,
                symbol=symbol,
                exchange=exchange,
                price=bar_1d.close,
                price_timestamp=bar_1d.bar_date,
                resolved_at=resolved_at,
                source=source,
                freshness=freshness,
                stale_reason=stale_reason,
                prev_close=_prev_daily_close(ohlcv_bars, bar_1d),
            )

        # ── Step 6: Fall back to prior Valkey snapshot ────────────────────────
        if prior_snapshot is not None:
            return PriceSnapshot(
                instrument_id=instrument_id,
                symbol=symbol,
                exchange=exchange,
                price=prior_snapshot.price,
                price_change=prior_snapshot.price_change,
                price_change_pct=prior_snapshot.price_change_pct,
                timestamp=prior_snapshot.timestamp,
                fetched_at=resolved_at,
                source=PriceSource.STALE_SNAPSHOT,
                freshness_status=FreshnessStatus.STALE,
                stale_reason="No fresh data; using last known cached price",
                refresh_available=True,
                refresh_cooldown_remaining_sec=0,
            )

        # ── Step 7: Truly unavailable ─────────────────────────────────────────
        return PriceSnapshot(
            instrument_id=instrument_id,
            symbol=symbol,
            exchange=exchange,
            price=Decimal("0"),
            price_change=None,
            price_change_pct=None,
            timestamp=resolved_at,  # use resolution time as sentinel
            fetched_at=resolved_at,
            source=PriceSource.UNAVAILABLE,
            freshness_status=FreshnessStatus.UNAVAILABLE,
            stale_reason="No price data available from any source",
            refresh_available=True,
            refresh_cooldown_remaining_sec=0,
        )

    @staticmethod
    def _build(
        instrument_id: str,
        symbol: str,
        exchange: str,
        price: Decimal,
        price_timestamp: datetime,
        resolved_at: datetime,
        source: PriceSource,
        freshness: FreshnessStatus,
        stale_reason: str | None,
        prev_close: Decimal | None = None,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ) -> PriceSnapshot:
        """Construct a PriceSnapshot from resolved components."""
        price_change: Decimal | None = None
        price_change_pct: Decimal | None = None
        if prev_close is not None and prev_close != Decimal("0"):
            price_change = price - prev_close
            price_change_pct = (price_change / prev_close) * Decimal("100")
        return PriceSnapshot(
            instrument_id=instrument_id,
            symbol=symbol,
            exchange=exchange,
            price=price,
            price_change=price_change,
            price_change_pct=price_change_pct,
            timestamp=price_timestamp,
            fetched_at=resolved_at,
            source=source,
            freshness_status=freshness,
            stale_reason=stale_reason,
            refresh_available=True,
            refresh_cooldown_remaining_sec=0,
            bid=bid,
            ask=ask,
        )
