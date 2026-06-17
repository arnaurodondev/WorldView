"""Unit tests for market_data domain entities and enums."""

from __future__ import annotations

from decimal import Decimal

import pytest
from market_data.domain.entities import (
    FundamentalsRecord,
    Instrument,
    OHLCVBar,
    PredictionMarket,
    PredictionMarketSnapshot,
    Quote,
    Security,
)
from market_data.domain.enums import (
    DatasetType,
    FundamentalsSection,
    PeriodType,
    Provider,
    Timeframe,
)
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority

pytestmark = pytest.mark.unit


class TestTimeframeEnum:
    def test_timeframe_enum_values(self) -> None:
        assert Timeframe.ONE_MIN == "1m"
        assert Timeframe.FIVE_MIN == "5m"
        assert Timeframe.FIFTEEN_MIN == "15m"
        assert Timeframe.THIRTY_MIN == "30m"
        assert Timeframe.ONE_HOUR == "1h"
        assert Timeframe.FOUR_HOUR == "4h"
        assert Timeframe.ONE_DAY == "1d"
        assert Timeframe.ONE_WEEK == "1w"
        assert Timeframe.ONE_MONTH == "1M"

    def test_timeframe_is_str(self) -> None:
        assert isinstance(Timeframe.ONE_DAY, str)

    def test_timeframe_count(self) -> None:
        assert len(Timeframe) == 9


class TestDatasetTypeEnum:
    def test_dataset_type_enum(self) -> None:
        assert DatasetType.OHLCV == "OHLCV"
        assert DatasetType.QUOTE == "QUOTE"
        assert DatasetType.FUNDAMENTALS == "FUNDAMENTALS"

    def test_dataset_type_is_str(self) -> None:
        assert isinstance(DatasetType.OHLCV, str)


class TestProviderPriorityOrdering:
    def test_provider_priority_ordering(self) -> None:
        assert Provider.POLYGON.priority > Provider.YAHOO.priority
        assert Provider.YAHOO.priority > Provider.ALPHA_VANTAGE.priority
        assert Provider.ALPHA_VANTAGE.priority > Provider.MACROTRENDS.priority
        assert Provider.MACROTRENDS.priority > Provider.UNKNOWN.priority

    def test_unknown_priority_is_zero(self) -> None:
        assert Provider.UNKNOWN.priority == 0

    def test_alpaca_and_derived_outrank_polled_providers(self) -> None:
        # OHLCV-SOURCING REWORK (2026-06-17): Alpaca 1m (and its locally-derived
        # higher timeframes) is the single source of truth, so it must outrank
        # every polled provider — including Polygon — in conflict resolution.
        highest = max(p.priority for p in Provider)
        assert Provider.ALPACA.priority == highest
        assert Provider.DERIVED.priority == highest
        assert Provider.ALPACA.priority > Provider.POLYGON.priority
        # Yahoo (deep daily, free) must beat EODHD (last-resort failover).
        assert Provider.YAHOO_FINANCE.priority > Provider.EODHD.priority


class TestSecurityEntity:
    def test_security_entity(self) -> None:
        sec = Security(name="Apple Inc.", currency="USD")
        assert sec.id  # auto-generated
        assert sec.name == "Apple Inc."
        assert sec.currency == "USD"
        assert sec.figi is None
        assert sec.isin is None

    def test_security_auto_id(self) -> None:
        s1 = Security(name="A")
        s2 = Security(name="B")
        assert s1.id != s2.id

    def test_security_full_fields(self) -> None:
        sec = Security(
            figi="BBG000B9XRY4",
            isin="US0378331005",
            name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            country="US",
            currency="USD",
        )
        assert sec.figi == "BBG000B9XRY4"
        assert sec.isin == "US0378331005"
        assert sec.sector == "Technology"


class TestInstrumentEntity:
    def test_instrument_entity_flags(self) -> None:
        flags = InstrumentFlags(has_ohlcv=True, has_quotes=False, has_fundamentals=False)
        inst = Instrument(symbol="AAPL", exchange="NASDAQ", flags=flags)
        assert inst.symbol == "AAPL"
        assert inst.exchange == "NASDAQ"
        assert inst.flags.has_ohlcv is True
        assert inst.flags.has_quotes is False
        assert inst.flags.has_fundamentals is False

    def test_instrument_default_flags(self) -> None:
        inst = Instrument(symbol="MSFT", exchange="NASDAQ")
        assert inst.flags.has_ohlcv is False
        assert inst.flags.has_quotes is False
        assert inst.flags.has_fundamentals is False

    def test_instrument_is_active_default(self) -> None:
        inst = Instrument(symbol="AAPL", exchange="NASDAQ")
        assert inst.is_active is True


class TestOHLCVBarEntity:
    def test_ohlcv_bar_entity(self) -> None:
        bar = OHLCVBar(
            instrument_id="test-id",
            timeframe=Timeframe.ONE_DAY,
            open=Decimal("150.00"),
            high=Decimal("155.00"),
            low=Decimal("149.50"),
            close=Decimal("152.00"),
            volume=1_000_000,
        )
        assert bar.open == Decimal("150.00")
        assert bar.high == Decimal("155.00")
        assert bar.low == Decimal("149.50")
        assert bar.close == Decimal("152.00")
        assert bar.volume == 1_000_000
        assert bar.timeframe == Timeframe.ONE_DAY
        assert bar.adjusted_close is None

    def test_ohlcv_bar_with_provider_priority(self) -> None:
        pp = ProviderPriority.for_provider(Provider.POLYGON)
        bar = OHLCVBar(instrument_id="id", provider_priority=pp)
        assert bar.provider_priority.provider == "polygon"
        assert bar.provider_priority.priority == 100

    def test_ohlcv_bar_default_timeframe(self) -> None:
        bar = OHLCVBar(instrument_id="id")
        assert bar.timeframe == Timeframe.ONE_DAY

    def test_ohlcv_bar_is_partial_default_false(self) -> None:
        """New OHLCVBar must default is_partial to False."""
        bar = OHLCVBar(instrument_id="id")
        assert bar.is_partial is False

    def test_ohlcv_bar_partial_implies_derived(self) -> None:
        """is_partial=True with is_derived=False must raise ValueError."""
        with pytest.raises(ValueError, match="is_partial=True implies is_derived=True"):
            OHLCVBar(instrument_id="id", is_partial=True, is_derived=False)

    def test_ohlcv_bar_partial_with_derived_ok(self) -> None:
        """is_partial=True with is_derived=True is a valid combination."""
        bar = OHLCVBar(instrument_id="id", is_partial=True, is_derived=True)
        assert bar.is_partial is True
        assert bar.is_derived is True


class TestQuoteEntity:
    def test_quote_entity(self) -> None:
        quote = Quote(
            instrument_id="test-id",
            bid=Decimal("149.90"),
            ask=Decimal("150.10"),
            last=Decimal("150.00"),
            volume=500_000,
        )
        assert quote.bid == Decimal("149.90")
        assert quote.ask == Decimal("150.10")
        assert quote.last == Decimal("150.00")
        assert quote.volume == 500_000

    def test_quote_spread(self) -> None:
        quote = Quote(bid=Decimal("99.50"), ask=Decimal("100.50"))
        spread = quote.ask - quote.bid
        assert spread == Decimal("1.00")


class TestFundamentalsRecordEntity:
    def test_fundamentals_record_section(self) -> None:
        rec = FundamentalsRecord(
            security_id="sec-1",
            section=FundamentalsSection.INCOME_STATEMENT,
            period_type=PeriodType.ANNUAL,
            data={"revenue": 391_035_000_000},
        )
        assert rec.section == FundamentalsSection.INCOME_STATEMENT
        assert rec.period_type == PeriodType.ANNUAL
        assert rec.data["revenue"] == 391_035_000_000

    def test_fundamentals_record_auto_id(self) -> None:
        r1 = FundamentalsRecord(security_id="s1")
        r2 = FundamentalsRecord(security_id="s2")
        assert r1.id != r2.id


class TestPredictionMarketEntity:
    def test_prediction_market_defaults(self) -> None:
        market = PredictionMarket(market_id="0xabc", question="Will X happen?")
        assert market.source == "polymarket"
        assert market.resolution_status == "open"
        assert market.description is None
        assert market.outcomes == []

    def test_prediction_market_auto_id(self) -> None:
        m1 = PredictionMarket(market_id="0x001")
        m2 = PredictionMarket(market_id="0x002")
        assert m1.id != m2.id

    def test_prediction_market_mutable(self) -> None:
        market = PredictionMarket(market_id="0xabc")
        market.resolution_status = "resolved"
        assert market.resolution_status == "resolved"


class TestPredictionMarketSnapshotEntity:
    _NOW = __import__("datetime").datetime(2026, 4, 9, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)

    def test_snapshot_validates_utc_aware(self) -> None:
        import datetime

        naive = datetime.datetime(2026, 4, 9, 12, 0, 0)  # noqa: DTZ001
        with pytest.raises(ValueError, match="UTC-aware"):
            PredictionMarketSnapshot(
                market_id="0xabc",
                snapshot_at=naive,
                outcomes_prices={"Yes": 0.7, "No": 0.3},
                source_event_id="evt-1",
            )

    def test_snapshot_validates_min_two_outcomes(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            PredictionMarketSnapshot(
                market_id="0xabc",
                snapshot_at=self._NOW,
                outcomes_prices={"Yes": 1.0},
                source_event_id="evt-1",
            )

    def test_snapshot_valid_creation(self) -> None:
        snap = PredictionMarketSnapshot(
            market_id="0xabc",
            snapshot_at=self._NOW,
            outcomes_prices={"Yes": 0.72, "No": 0.28},
            source_event_id="evt-1",
            volume_24h=Decimal("1500"),
        )
        assert snap.market_id == "0xabc"
        assert snap.outcomes_prices["Yes"] == 0.72
        assert snap.volume_24h == Decimal("1500")
        assert snap.liquidity is None

    def test_snapshot_is_frozen(self) -> None:
        snap = PredictionMarketSnapshot(
            market_id="0xabc",
            snapshot_at=self._NOW,
            outcomes_prices={"Yes": 0.6, "No": 0.4},
            source_event_id="evt-1",
        )
        with pytest.raises(Exception):  # noqa: B017  # FrozenInstanceError (dataclasses.FrozenInstanceError)
            snap.market_id = "changed"  # type: ignore[misc]

    def test_snapshot_auto_id(self) -> None:
        s1 = PredictionMarketSnapshot(
            market_id="0x001",
            snapshot_at=self._NOW,
            outcomes_prices={"Yes": 0.5, "No": 0.5},
            source_event_id="evt-1",
        )
        s2 = PredictionMarketSnapshot(
            market_id="0x002",
            snapshot_at=self._NOW,
            outcomes_prices={"Yes": 0.5, "No": 0.5},
            source_event_id="evt-2",
        )
        assert s1.id != s2.id
