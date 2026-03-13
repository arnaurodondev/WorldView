"""Unit tests for market_data domain entities and enums."""

from __future__ import annotations

from decimal import Decimal

import pytest
from market_data.domain.entities import (
    FundamentalsRecord,
    Instrument,
    OHLCVBar,
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

    def test_polygon_is_highest_priority(self) -> None:
        highest = max(Provider, key=lambda p: p.priority)
        assert highest == Provider.POLYGON


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
