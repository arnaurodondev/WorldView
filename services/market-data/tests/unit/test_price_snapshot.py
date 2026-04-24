"""Unit tests for PriceSnapshotResolver and freshness classifier.

These tests are pure domain tests — no mocking needed because
PriceSnapshotResolver is a stateless pure function that takes entities as
parameters.  Quote and OHLCVBar instances are constructed directly.

Run with:
    cd services/market-data && ../../.venv312/bin/python -m pytest tests/unit/test_price_snapshot.py -v -m unit
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from market_data.domain.entities import OHLCVBar, Quote
from market_data.domain.enums import Timeframe
from market_data.domain.price_snapshot import PriceSnapshotResolver, classify_freshness

from contracts.canonical.price_snapshot import (  # type: ignore[import-untyped]
    FreshnessStatus,
    PriceSnapshot,
    PriceSource,
)

pytestmark = pytest.mark.unit

# ── Shared fixtures ──────────────────────────────────────────────────────────

_INSTRUMENT_ID = "0190f3a0-dead-beef-cafe-000000000001"
_SYMBOL = "AAPL"
_EXCHANGE = "NASDAQ"

# A fixed "now" in UTC during NYSE market hours (15:00 UTC = 11:00 EDT)
_NOW: datetime = datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC)

# A fixed "now" OUTSIDE NYSE market hours (00:00 UTC = midnight EDT)
_NOW_OFF_HOURS: datetime = datetime(2024, 3, 15, 0, 0, 0, tzinfo=UTC)


def _make_quote(age_seconds: float, last: str = "150.00") -> Quote:
    """Return a Quote with timestamp = _NOW - age_seconds."""
    ts = _NOW - timedelta(seconds=age_seconds)
    return Quote(
        instrument_id=_INSTRUMENT_ID,
        last=Decimal(last),
        bid=Decimal("149.90"),
        ask=Decimal("150.10"),
        volume=1_000_000,
        timestamp=ts,
        updated_at=ts,
    )


def _make_bar(timeframe: Timeframe, age_seconds: float, close: str = "150.00") -> OHLCVBar:
    """Return an OHLCVBar with bar_date = _NOW - age_seconds."""
    ts = _NOW - timedelta(seconds=age_seconds)
    return OHLCVBar(
        instrument_id=_INSTRUMENT_ID,
        timeframe=timeframe,
        bar_date=ts,
        open=Decimal("148.00"),
        high=Decimal("151.00"),
        low=Decimal("147.00"),
        close=Decimal(close),
        volume=500_000,
    )


def _resolver() -> PriceSnapshotResolver:
    return PriceSnapshotResolver()


# ── Test 1: Fresh quote (<5 min) → FRESH_QUOTE + LIVE ────────────────────────


class TestFreshQuoteReturnsLive:
    def test_fresh_quote_returns_live(self) -> None:
        """A quote less than 5 minutes old → source=FRESH_QUOTE, freshness=LIVE."""
        quote = _make_quote(age_seconds=60)  # 1 min old — well within 5 min
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=quote,
            ohlcv_bars=[],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.FRESH_QUOTE
        assert snapshot.freshness_status == FreshnessStatus.LIVE
        assert snapshot.price == Decimal("150.00")
        assert snapshot.instrument_id == _INSTRUMENT_ID
        assert snapshot.symbol == _SYMBOL

    def test_quote_at_boundary_4min59sec_is_fresh(self) -> None:
        """At exactly 4m59s, quote is still classified as FRESH_QUOTE."""
        quote = _make_quote(age_seconds=299)  # just under 5 min
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=quote,
            ohlcv_bars=[],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.FRESH_QUOTE


# -- Test 2: Bulk quote (5-15 min) -> BULK_QUOTE + RECENT ─────────────────────


class TestBulkQuoteReturnsRecent:
    def test_bulk_quote_returns_recent(self) -> None:
        """A quote 10 minutes old → source=BULK_QUOTE, freshness=RECENT during market hours."""
        quote = _make_quote(age_seconds=600)  # 10 min old
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=quote,
            ohlcv_bars=[],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.BULK_QUOTE
        assert snapshot.freshness_status == FreshnessStatus.RECENT

    def test_quote_exactly_at_14min_is_bulk(self) -> None:
        """At 14 min (< 15 min threshold), still BULK_QUOTE."""
        quote = _make_quote(age_seconds=840)  # 14 min
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=quote,
            ohlcv_bars=[],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.BULK_QUOTE


# ── Test 3: Stale quote → fallback to 5m OHLCV bar ──────────────────────────


class TestFallbackTo5mBarWhenQuoteStale:
    def test_fallback_to_5m_bar_when_quote_stale(self) -> None:
        """A 20-min-old quote is skipped; a fresh 5m bar is used instead."""
        stale_quote = _make_quote(age_seconds=1200)  # 20 min — exceeds 15 min threshold
        fresh_bar_5m = _make_bar(Timeframe.FIVE_MIN, age_seconds=120, close="151.50")  # 2 min old

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=stale_quote,
            ohlcv_bars=[fresh_bar_5m],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.INTRADAY_5M_CLOSE
        assert snapshot.price == Decimal("151.50")

    def test_no_quote_with_5m_bar_uses_intraday(self) -> None:
        """No quote at all: 5m bar is used."""
        fresh_bar_5m = _make_bar(Timeframe.FIVE_MIN, age_seconds=300, close="152.00")  # 5 min old

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[fresh_bar_5m],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.INTRADAY_5M_CLOSE


# ── Test 4: Daily close outside market hours → DAILY_CLOSE + LIVE ─────────


class TestFallbackToDailyCloseOutsideMarketHours:
    def test_fallback_to_daily_close_outside_market_hours(self) -> None:
        """Off market hours: daily bar close → source=DAILY_CLOSE, freshness=LIVE."""
        # bar_date is 2 hours ago — but we're off-hours so it's still LIVE
        bar_1d = OHLCVBar(
            instrument_id=_INSTRUMENT_ID,
            timeframe=Timeframe.ONE_DAY,
            bar_date=_NOW_OFF_HOURS - timedelta(hours=2),
            open=Decimal("148.00"),
            high=Decimal("151.00"),
            low=Decimal("147.00"),
            close=Decimal("149.00"),
            volume=10_000_000,
        )

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[bar_1d],
            resolved_at=_NOW_OFF_HOURS,  # midnight UTC — off hours
        )
        assert snapshot.source == PriceSource.DAILY_CLOSE
        # Outside market hours, daily close is the live authoritative price
        assert snapshot.freshness_status == FreshnessStatus.LIVE
        assert snapshot.price == Decimal("149.00")

    def test_daily_close_during_market_hours_is_delayed(self) -> None:
        """During market hours, a daily close from yesterday → DELAYED."""
        # Yesterday's EOD bar
        yesterday = _NOW - timedelta(hours=20)
        bar_1d = OHLCVBar(
            instrument_id=_INSTRUMENT_ID,
            timeframe=Timeframe.ONE_DAY,
            bar_date=yesterday,
            open=Decimal("148.00"),
            high=Decimal("151.00"),
            low=Decimal("147.00"),
            close=Decimal("149.00"),
            volume=10_000_000,
        )

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[bar_1d],
            resolved_at=_NOW,  # during market hours
        )
        assert snapshot.source == PriceSource.DAILY_CLOSE
        assert snapshot.freshness_status == FreshnessStatus.DELAYED


# ── Test 5: No data + prior snapshot → STALE_SNAPSHOT ────────────────────────


class TestFallbackToStaleSnapshot:
    def test_fallback_to_stale_snapshot(self) -> None:
        """When all DB sources are absent, a prior cached snapshot is used as STALE."""
        prior_snapshot = PriceSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            price=Decimal("145.00"),
            price_change=Decimal("-2.00"),
            price_change_pct=Decimal("-1.36"),
            timestamp=_NOW - timedelta(hours=3),
            fetched_at=_NOW - timedelta(hours=3),
            source=PriceSource.DAILY_CLOSE,
            freshness_status=FreshnessStatus.LIVE,
            stale_reason=None,
        )

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[],
            resolved_at=_NOW,
            prior_snapshot=prior_snapshot,
        )
        assert snapshot.source == PriceSource.STALE_SNAPSHOT
        assert snapshot.freshness_status == FreshnessStatus.STALE
        # Price is preserved from prior snapshot
        assert snapshot.price == Decimal("145.00")
        # stale_reason is set
        assert snapshot.stale_reason is not None

    def test_stale_snapshot_preserves_price_change(self) -> None:
        """STALE_SNAPSHOT preserves price_change and price_change_pct from prior snapshot."""
        prior_snapshot = PriceSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            price=Decimal("200.00"),
            price_change=Decimal("5.00"),
            price_change_pct=Decimal("2.56"),
            timestamp=_NOW - timedelta(hours=5),
            fetched_at=_NOW - timedelta(hours=5),
            source=PriceSource.DAILY_CLOSE,
            freshness_status=FreshnessStatus.LIVE,
            stale_reason=None,
        )

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[],
            resolved_at=_NOW,
            prior_snapshot=prior_snapshot,
        )
        assert snapshot.price_change == Decimal("5.00")
        assert snapshot.price_change_pct == Decimal("2.56")


# ── Test 6: No data at all → UNAVAILABLE ────────────────────────────────────


class TestUnavailableWhenNoData:
    def test_unavailable_when_no_data(self) -> None:
        """With no quote, no bars, and no prior snapshot → UNAVAILABLE, price=0."""
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[],
            resolved_at=_NOW,
            prior_snapshot=None,
        )
        assert snapshot.source == PriceSource.UNAVAILABLE
        assert snapshot.freshness_status == FreshnessStatus.UNAVAILABLE
        assert snapshot.price == Decimal("0")
        assert snapshot.stale_reason is not None

    def test_unavailable_has_zero_price(self) -> None:
        """UNAVAILABLE snapshot uses Decimal("0") as sentinel price."""
        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[],
            resolved_at=_NOW,
        )
        assert snapshot.price == Decimal("0")
        assert snapshot.price_change is None
        assert snapshot.price_change_pct is None


# ── Test 7: 24h market (CC exchange) ignores market hours ────────────────────


class TestClassifyFreshness24hMarket:
    def test_classify_freshness_cc_exchange_is_always_time_based(self) -> None:
        """CC (crypto) exchange uses pure age thresholds — no market-hours concept."""
        # Off-hours UTC time that would be "not market hours" for NYSE
        off_hours_ts = datetime(2024, 3, 15, 2, 0, 0, tzinfo=UTC)  # 02:00 UTC
        price_ts = off_hours_ts - timedelta(seconds=60)  # 1 min old

        # For CC: < 5 min → LIVE regardless of UTC hour
        status = classify_freshness(
            PriceSource.FRESH_QUOTE,
            price_ts,
            off_hours_ts,
            exchange="CC",
        )
        assert status == FreshnessStatus.LIVE

    def test_classify_freshness_cc_delayed_when_old(self) -> None:
        """CC exchange: 2-hour-old price → DELAYED (not LIVE as would be for NYSE off-hours)."""
        now = datetime(2024, 3, 15, 2, 0, 0, tzinfo=UTC)  # 02:00 UTC — off NYSE hours
        price_ts = now - timedelta(hours=2)  # 2 hours old

        # For NYSE off-hours, daily close would be LIVE.
        # For CC, we strictly use time thresholds → 2h is DELAYED.
        status = classify_freshness(
            PriceSource.DAILY_CLOSE,
            price_ts,
            now,
            exchange="CC",
        )
        assert status == FreshnessStatus.DELAYED

    def test_classify_freshness_cc_stale_when_very_old(self) -> None:
        """CC exchange: 2-day-old price → STALE."""
        now = datetime(2024, 3, 15, 2, 0, 0, tzinfo=UTC)
        price_ts = now - timedelta(days=2)

        status = classify_freshness(
            PriceSource.DAILY_CLOSE,
            price_ts,
            now,
            exchange="CC",
        )
        assert status == FreshnessStatus.STALE


# ── Test 8: PriceSnapshot to_dict / from_dict round-trip ─────────────────────


class TestPriceSnapshotToFromDict:
    def test_round_trip_with_all_fields(self) -> None:
        """PriceSnapshot.to_dict() → from_dict() round-trip preserves all fields."""
        original = PriceSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            price=Decimal("150.123456"),
            price_change=Decimal("-1.50"),
            price_change_pct=Decimal("-0.99"),
            timestamp=datetime(2024, 3, 15, 14, 30, 0, tzinfo=UTC),
            fetched_at=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
            source=PriceSource.FRESH_QUOTE,
            freshness_status=FreshnessStatus.LIVE,
            stale_reason=None,
            refresh_available=True,
            refresh_cooldown_remaining_sec=0,
        )

        serialised = original.to_dict()
        restored = PriceSnapshot.from_dict(serialised)

        assert restored.instrument_id == original.instrument_id
        assert restored.symbol == original.symbol
        assert restored.exchange == original.exchange
        assert restored.price == original.price
        assert restored.price_change == original.price_change
        assert restored.price_change_pct == original.price_change_pct
        assert restored.timestamp == original.timestamp
        assert restored.fetched_at == original.fetched_at
        assert restored.source == original.source
        assert restored.freshness_status == original.freshness_status
        assert restored.stale_reason == original.stale_reason
        assert restored.refresh_available == original.refresh_available
        assert restored.refresh_cooldown_remaining_sec == original.refresh_cooldown_remaining_sec

    def test_round_trip_with_none_fields(self) -> None:
        """Round-trip preserves None for optional price_change fields."""
        original = PriceSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="BTC-USD",
            exchange="CC",
            price=Decimal("65000.00"),
            price_change=None,  # unavailable
            price_change_pct=None,
            timestamp=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
            fetched_at=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
            source=PriceSource.UNAVAILABLE,
            freshness_status=FreshnessStatus.UNAVAILABLE,
            stale_reason="No price data available from any source",
            refresh_available=True,
            refresh_cooldown_remaining_sec=0,
        )

        restored = PriceSnapshot.from_dict(original.to_dict())

        assert restored.price_change is None
        assert restored.price_change_pct is None
        assert restored.stale_reason == "No price data available from any source"

    def test_to_dict_contains_expected_keys(self) -> None:
        """to_dict() output has exactly the expected keys for Valkey storage."""
        snapshot = PriceSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            price=Decimal("100.00"),
            price_change=None,
            price_change_pct=None,
            timestamp=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
            fetched_at=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
            source=PriceSource.DAILY_CLOSE,
            freshness_status=FreshnessStatus.DELAYED,
            stale_reason=None,
        )
        d = snapshot.to_dict()
        expected_keys = {
            "instrument_id",
            "symbol",
            "exchange",
            "price",
            "price_change",
            "price_change_pct",
            "timestamp",
            "fetched_at",
            "source",
            "freshness_status",
            "stale_reason",
            "refresh_available",
            "refresh_cooldown_remaining_sec",
        }
        assert set(d.keys()) == expected_keys
        # Price is a string (not float) to preserve Decimal precision
        assert isinstance(d["price"], str)


# ── Test 9: Resolver picks the latest bar when multiple present ──────────────


class TestResolverPicksLatestBar:
    def test_resolver_picks_latest_5m_bar(self) -> None:
        """When multiple 5m bars exist, the resolver uses the most recent one."""
        older_bar = _make_bar(Timeframe.FIVE_MIN, age_seconds=600, close="140.00")  # 10 min old
        newer_bar = _make_bar(Timeframe.FIVE_MIN, age_seconds=120, close="155.00")  # 2 min old

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[older_bar, newer_bar],  # order shouldn't matter
            resolved_at=_NOW,
        )
        # Should pick the newer bar's close price
        assert snapshot.price == Decimal("155.00")
        assert snapshot.source == PriceSource.INTRADAY_5M_CLOSE

    def test_resolver_prefers_5m_over_1h_when_both_fresh(self) -> None:
        """When both 5m and 1h bars are available, 5m bar takes priority."""
        bar_5m = _make_bar(Timeframe.FIVE_MIN, age_seconds=300, close="155.00")  # fresh 5m
        bar_1h = _make_bar(Timeframe.ONE_HOUR, age_seconds=1800, close="153.00")  # 30min 1h bar

        snapshot = _resolver().resolve(
            instrument_id=_INSTRUMENT_ID,
            symbol=_SYMBOL,
            exchange=_EXCHANGE,
            quote=None,
            ohlcv_bars=[bar_5m, bar_1h],
            resolved_at=_NOW,
        )
        assert snapshot.source == PriceSource.INTRADAY_5M_CLOSE
        assert snapshot.price == Decimal("155.00")
