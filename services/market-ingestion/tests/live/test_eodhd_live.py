"""Live EODHD API tests — real HTTP calls against eodhd.com with demo key.

These tests verify that every adapter method returns valid data and that the
raw responses can be parsed by the corresponding canonical models.

The EODHD demo key (``demo``) grants access to AAPL.US for a subset of
endpoints.  Endpoints that require a paid plan (earnings calendar, economic
events, macro indicators, insider transactions, yield curve, exchanges-list)
are tested with ``pytest.mark.xfail`` so a 403 is reported cleanly.

Run:
    cd services/market-ingestion
    .venv/bin/pytest tests/live/ -v

Skip conditions:
    - Network unreachable → all tests are skipped (not failed)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderAuthError, ProviderDataError
from market_ingestion.infrastructure.adapters.providers.eodhd import (
    EODHDProviderAdapter,
)

# ---------------------------------------------------------------------------
# Fixtures & constants
# ---------------------------------------------------------------------------

_DEMO_KEY = "demo"
_SYMBOL = "AAPL"
_EXCHANGE = "US"
_TICKER = f"{_SYMBOL}.{_EXCHANGE}"


def _is_network_available() -> bool:
    """Quick connectivity probe — avoids marking all tests as FAILED when offline."""
    try:
        import socket

        socket.create_connection(("eodhd.com", 443), timeout=5)
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not _is_network_available(), reason="No network connectivity to eodhd.com"),
]

# Marker for endpoints that require a paid plan (403 with demo key)
_PAID_ONLY = pytest.mark.xfail(
    reason="Demo key returns 403 for this endpoint (paid plan required)",
    raises=ProviderAuthError,
    strict=True,
)


@pytest.fixture(scope="module")
async def adapter():
    """Module-scoped EODHD adapter backed by a real httpx client with the demo key."""
    async with httpx.AsyncClient(timeout=30) as client:
        yield EODHDProviderAdapter(api_key=_DEMO_KEY, client=client)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_json(raw: bytes) -> list | dict:
    """Parse raw bytes as JSON, returning the decoded value."""
    return json.loads(raw.decode())


# =========================================================================
# Part A — Adapter fetch methods (real API calls)
# =========================================================================


class TestFetchOHLCV:
    """Tests for the /eod/{ticker} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_non_empty_bars(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 31, tzinfo=UTC),
            exchange=_EXCHANGE,
        )

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.OHLCV
        assert result.symbol == _SYMBOL
        assert len(result.raw_data) > 10

        bars = _parse_json(result.raw_data)
        assert isinstance(bars, list)
        assert len(bars) >= 1

    @pytest.mark.asyncio
    async def test_bars_have_expected_fields(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            exchange=_EXCHANGE,
        )
        bars = _parse_json(result.raw_data)
        bar = bars[0]
        for field in ("date", "open", "high", "low", "close", "volume", "adjusted_close"):
            assert field in bar, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_weekly_timeframe(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1w",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 3, 31, tzinfo=UTC),
            exchange=_EXCHANGE,
        )
        bars = _parse_json(result.raw_data)
        assert isinstance(bars, list)
        assert len(bars) >= 1

    @pytest.mark.asyncio
    async def test_empty_range_returns_empty_list(self, adapter: EODHDProviderAdapter):
        """A date range in the far future should return an empty list (no error)."""
        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1d",
            start=datetime(2099, 1, 1, tzinfo=UTC),
            end=datetime(2099, 1, 5, tzinfo=UTC),
            exchange=_EXCHANGE,
        )
        bars = _parse_json(result.raw_data)
        assert isinstance(bars, list)
        assert len(bars) == 0


class TestFetchIntraday:
    """Tests for the /intraday/{ticker} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_intraday_bars(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_intraday(
            symbol=_SYMBOL,
            interval="5m",
            exchange=_EXCHANGE,
        )

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.OHLCV
        assert result.symbol == _SYMBOL
        assert result.provider_metadata == {"interval": "5m"}

        data = _parse_json(result.raw_data)
        # Intraday may return a list or sometimes an error dict for demo key
        if isinstance(data, list) and len(data) > 0:
            bar = data[0]
            # Intraday uses "datetime" key, not "date"
            assert "datetime" in bar or "date" in bar
            assert "open" in bar
            assert "close" in bar
            assert "volume" in bar


class TestFetchQuotes:
    """Tests for the /real-time/{ticker} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_quote(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_quotes(symbol=_SYMBOL, exchange=_EXCHANGE)

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.QUOTES
        assert result.symbol == _SYMBOL

        quote = _parse_json(result.raw_data)
        assert isinstance(quote, dict)
        assert "close" in quote or "last" in quote

    @pytest.mark.asyncio
    async def test_quote_has_volume_and_timestamp(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_quotes(symbol=_SYMBOL, exchange=_EXCHANGE)
        quote = _parse_json(result.raw_data)
        assert "volume" in quote
        assert "timestamp" in quote


class TestFetchFundamentals:
    """Tests for the /fundamentals/{ticker} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_full_fundamentals(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_fundamentals(
            symbol=_SYMBOL,
            variant="annual",
            exchange=_EXCHANGE,
        )

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.FUNDAMENTALS
        assert result.provider_metadata == {"variant": "annual"}

        data = _parse_json(result.raw_data)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_fundamentals_has_general_section(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        assert "General" in data
        general = data["General"]
        assert general.get("Name") or general.get("Code")

    @pytest.mark.asyncio
    async def test_fundamentals_has_financials(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        assert "Financials" in data
        financials = data["Financials"]
        assert "Income_Statement" in financials
        assert "Balance_Sheet" in financials
        assert "Cash_Flow" in financials

    @pytest.mark.asyncio
    async def test_fundamentals_has_highlights_and_valuation(self, adapter: EODHDProviderAdapter):
        """FIX-F10: Highlights and Valuation are separate sections."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        assert "Highlights" in data
        assert "Valuation" in data
        # They should be separate dicts, not merged
        assert isinstance(data["Highlights"], dict)
        assert isinstance(data["Valuation"], dict)

    @pytest.mark.asyncio
    async def test_fundamentals_has_earnings(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        assert "Earnings" in data
        earnings = data["Earnings"]
        assert "History" in earnings
        assert "Trend" in earnings
        assert "Annual" in earnings

    @pytest.mark.asyncio
    async def test_fundamentals_has_holders(self, adapter: EODHDProviderAdapter):
        """FIX-F6: Holders section contains Institutions and Funds."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        holders = data.get("Holders")
        if holders:  # may be None for some tickers, but AAPL should have it
            assert "Institutions" in holders or "Funds" in holders

    @pytest.mark.asyncio
    async def test_fundamentals_has_splits_dividends(self, adapter: EODHDProviderAdapter):
        """FIX-F5: SplitsDividends should contain NumberDividendsByYear."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        splits_divs = data.get("SplitsDividends") or {}
        # AAPL pays dividends, so this should be present
        assert "NumberDividendsByYear" in splits_divs

    @pytest.mark.asyncio
    async def test_fundamentals_has_insider_transactions(self, adapter: EODHDProviderAdapter):
        """FIX-F7: InsiderTransactions section at the top level."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        # InsiderTransactions may be present as a dict or None
        assert "InsiderTransactions" in data

    @pytest.mark.asyncio
    async def test_financials_have_quarterly_and_yearly(self, adapter: EODHDProviderAdapter):
        """FIX-F2/F3: Financial statements have quarterly + yearly sub-dicts."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        data = _parse_json(result.raw_data)
        income = data["Financials"]["Income_Statement"]
        assert "quarterly" in income
        assert "yearly" in income
        # Each should be a dict of date-keyed entries
        assert isinstance(income["quarterly"], dict)
        assert isinstance(income["yearly"], dict)
        # At least one entry in each
        assert len(income["quarterly"]) >= 1
        assert len(income["yearly"]) >= 1


class TestFetchEarningsCalendar:
    """Tests for the /calendar/earnings endpoint (paid plan only)."""

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_returns_earnings_events(self, adapter: EODHDProviderAdapter):
        today = datetime.now(tz=UTC).date()
        result = await adapter.fetch_earnings_calendar(
            from_date=(today - timedelta(days=30)).isoformat(),
            to_date=today.isoformat(),
        )
        assert result.dataset_type == DatasetType.EARNINGS_CALENDAR

    @pytest.mark.asyncio
    async def test_with_symbol_filter(self, adapter: EODHDProviderAdapter):
        """Earnings calendar with explicit symbols filter works with demo key."""
        today = datetime.now(tz=UTC).date()
        result = await adapter.fetch_earnings_calendar(
            from_date=(today - timedelta(days=90)).isoformat(),
            to_date=today.isoformat(),
            symbols=["AAPL.US"],
        )
        assert result.dataset_type == DatasetType.EARNINGS_CALENDAR
        data = _parse_json(result.raw_data)
        # The earnings endpoint with symbols filter returns an object with "earnings" key
        events = data.get("earnings", data) if isinstance(data, dict) else data
        assert events is not None


class TestFetchEconomicEvents:
    """Tests for the /economic-events endpoint (paid plan only)."""

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_returns_events_for_usa(self, adapter: EODHDProviderAdapter):
        today = datetime.now(tz=UTC).date()
        result = await adapter.fetch_economic_events(
            from_date=(today - timedelta(days=14)).isoformat(),
            to_date=today.isoformat(),
            country="USA",
        )
        assert result.dataset_type == DatasetType.ECONOMIC_EVENTS

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_with_limit_and_offset(self, adapter: EODHDProviderAdapter):
        today = datetime.now(tz=UTC).date()
        result = await adapter.fetch_economic_events(
            from_date=(today - timedelta(days=14)).isoformat(),
            to_date=today.isoformat(),
            country="USA",
            limit=5,
            offset=0,
        )
        assert result is not None


class TestFetchMacroIndicator:
    """Tests for the /macro-indicator/{country} endpoint (paid plan only)."""

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_usa_gdp(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_macro_indicator(symbol="USA.gdp_current_usd")
        assert result.dataset_type == DatasetType.MACRO_INDICATOR

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_usa_inflation(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_macro_indicator(symbol="USA.inflation_consumer_prices_annual")
        assert result is not None


class TestFetchNewsSentiment:
    """Tests for the /news endpoint."""

    @pytest.mark.asyncio
    async def test_returns_news_articles(self, adapter: EODHDProviderAdapter):
        today = datetime.now(tz=UTC).date()
        result = await adapter.fetch_news_sentiment(
            symbol=f"{_SYMBOL}.{_EXCHANGE}",
            from_date=(today - timedelta(days=7)).isoformat(),
            to_date=today.isoformat(),
            limit=5,
        )

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.NEWS_SENTIMENT

        data = _parse_json(result.raw_data)
        assert isinstance(data, list)
        if len(data) > 0:
            article = data[0]
            assert "title" in article
            # EODHD news endpoint includes sentiment in the response
            assert "sentiment" in article or "date" in article

    @pytest.mark.asyncio
    async def test_respects_limit(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_news_sentiment(
            symbol=f"{_SYMBOL}.{_EXCHANGE}",
            limit=3,
        )
        data = _parse_json(result.raw_data)
        assert isinstance(data, list)
        assert len(data) <= 3


class TestFetchInsiderTransactions:
    """Tests for the /insider-transactions endpoint (paid plan only)."""

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_returns_insider_data(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_insider_transactions(ticker=_TICKER, limit=10)
        assert result.dataset_type == DatasetType.INSIDER_TRANSACTIONS


class TestFetchYieldCurve:
    """Tests for the /ust/yield-rates endpoint (paid plan only)."""

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_returns_yield_rates(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_yield_curve(
            series_symbol="UST.yield",
            from_date="2024-01-01",
            to_date="2024-01-31",
        )
        assert result.dataset_type == DatasetType.YIELD_CURVE

    @pytest.mark.asyncio
    async def test_invalid_series_raises_data_error(self, adapter: EODHDProviderAdapter):
        """Unknown yield series should raise ProviderDataError before any HTTP call."""
        with pytest.raises(ProviderDataError, match="Unknown yield series"):
            await adapter.fetch_yield_curve(series_symbol="UST.invalid")

    @_PAID_ONLY
    @pytest.mark.asyncio
    async def test_bill_rates(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_yield_curve(
            series_symbol="UST.bill",
            from_date="2024-01-01",
            to_date="2024-01-31",
        )
        assert result is not None


class TestFetchHistoricalMarketCap:
    """Tests for the /historical-market-cap/{ticker} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_market_cap_data(self, adapter: EODHDProviderAdapter):
        result = await adapter.fetch_historical_market_cap(
            ticker=_TICKER,
            from_date="2024-01-01",
            to_date="2024-03-31",
        )

        assert result.provider == Provider.EODHD
        assert result.dataset_type == DatasetType.MARKET_CAP
        assert result.symbol == _TICKER

        data = _parse_json(result.raw_data)
        # May return a list or dict; demo key may have limited access
        if isinstance(data, list) and len(data) > 0:
            point = data[0]
            assert "date" in point or "Date" in point


class TestHealthCheck:
    """Tests for the health_check() method."""

    @pytest.mark.asyncio
    async def test_health_check_with_demo_key(self, adapter: EODHDProviderAdapter):
        """Demo key gets 403 on exchanges-list, so health_check returns False."""
        result = await adapter.health_check()
        # The demo key cannot access /exchanges-list (403), so health check fails.
        # This is expected — a valid paid key would return True.
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_with_invalid_key(self):
        async with httpx.AsyncClient(timeout=15) as client:
            bad_adapter = EODHDProviderAdapter(api_key="invalid_key_12345", client=client)
            result = await bad_adapter.health_check()
            assert result is False


# =========================================================================
# Part B — Canonical model parsing of real responses
# =========================================================================


class TestCanonicalOHLCVParsing:
    """Verify CanonicalOHLCVBar.from_dict works with real EODHD EOD responses."""

    @pytest.mark.asyncio
    async def test_parse_eod_bars(self, adapter: EODHDProviderAdapter):
        from contracts.canonical.ohlcv import CanonicalOHLCVBar

        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 10, tzinfo=UTC),
            exchange=_EXCHANGE,
        )
        bars = _parse_json(result.raw_data)
        assert len(bars) >= 1

        for raw_bar in bars:
            enriched = {
                **raw_bar,
                "symbol": _SYMBOL,
                "exchange": _EXCHANGE,
                "source": "eodhd",
            }
            bar = CanonicalOHLCVBar.from_dict(enriched)
            assert bar.symbol == _SYMBOL
            assert bar.exchange == _EXCHANGE
            assert bar.open > 0
            assert bar.high >= bar.low
            assert bar.volume >= 0
            # EOD bars should have adjusted_close
            assert bar.adjusted_close is not None
            # date should be parsed correctly
            assert bar.date.year == 2024

    @pytest.mark.asyncio
    async def test_parse_eod_bar_roundtrip(self, adapter: EODHDProviderAdapter):
        """from_dict → to_dict → from_dict roundtrip."""
        from contracts.canonical.ohlcv import CanonicalOHLCVBar

        result = await adapter.fetch_ohlcv(
            symbol=_SYMBOL,
            timeframe="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 3, tzinfo=UTC),
            exchange=_EXCHANGE,
        )
        bars = _parse_json(result.raw_data)
        raw_bar = {**bars[0], "symbol": _SYMBOL, "exchange": _EXCHANGE, "source": "eodhd"}

        bar1 = CanonicalOHLCVBar.from_dict(raw_bar)
        bar2 = CanonicalOHLCVBar.from_dict(bar1.to_dict())
        assert bar1.open == bar2.open
        assert bar1.close == bar2.close
        assert bar1.volume == bar2.volume

    @pytest.mark.asyncio
    async def test_intraday_bars_use_datetime_key(self, adapter: EODHDProviderAdapter):
        """FIX-O1: Intraday bars use 'datetime' key, not 'date'."""
        from contracts.canonical.ohlcv import CanonicalOHLCVBar

        result = await adapter.fetch_intraday(
            symbol=_SYMBOL,
            interval="5m",
            exchange=_EXCHANGE,
        )
        data = _parse_json(result.raw_data)
        if isinstance(data, list) and len(data) > 0:
            raw_bar = {
                **data[0],
                "symbol": _SYMBOL,
                "exchange": _EXCHANGE,
                "source": "eodhd",
            }
            bar = CanonicalOHLCVBar.from_dict(raw_bar)
            assert bar.symbol == _SYMBOL
            # FIX-O2: Intraday should have no adjusted_close
            assert bar.adjusted_close is None
            assert bar.open > 0


class TestCanonicalQuoteParsing:
    """Verify CanonicalQuote.from_dict works with real EODHD real-time responses."""

    @pytest.mark.asyncio
    async def test_parse_quote_via_remap(self, adapter: EODHDProviderAdapter):
        """Quote parsing uses _remap_quote to normalise EODHD field names."""
        from market_ingestion.application.use_cases.execute_task import _remap_quote

        from contracts.canonical.quotes import CanonicalQuote

        result = await adapter.fetch_quotes(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw_quote = _parse_json(result.raw_data)
        assert isinstance(raw_quote, dict)

        remapped = _remap_quote(raw_quote, _SYMBOL, _EXCHANGE, "eodhd")
        quote = CanonicalQuote.from_dict(remapped)
        assert quote.symbol == _SYMBOL
        assert quote.exchange == _EXCHANGE
        assert quote.last > 0
        assert quote.volume >= 0

    @pytest.mark.asyncio
    async def test_quote_timestamp_is_iso8601(self, adapter: EODHDProviderAdapter):
        """_remap_quote should convert Unix epoch to ISO-8601."""
        from market_ingestion.application.use_cases.execute_task import _remap_quote

        result = await adapter.fetch_quotes(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw_quote = _parse_json(result.raw_data)
        remapped = _remap_quote(raw_quote, _SYMBOL, _EXCHANGE, "eodhd")

        # timestamp should be ISO-8601 string
        ts = remapped["timestamp"]
        assert isinstance(ts, str)
        # Should be parseable
        parsed = datetime.fromisoformat(ts)
        assert parsed.year >= 2020


class TestCanonicalMarketCapParsing:
    """Verify CanonicalMarketCapPoint.from_dict works with real market cap data."""

    @pytest.mark.asyncio
    async def test_parse_market_cap(self, adapter: EODHDProviderAdapter):
        from contracts.canonical.market_cap import CanonicalMarketCapPoint

        result = await adapter.fetch_historical_market_cap(
            ticker=_TICKER,
            from_date="2024-01-01",
            to_date="2024-03-31",
        )
        data = _parse_json(result.raw_data)

        if isinstance(data, list) and len(data) > 0:
            for raw_point in data[:5]:
                point = CanonicalMarketCapPoint.from_dict(
                    {
                        **raw_point,
                        "symbol": _SYMBOL,
                        "exchange": _EXCHANGE,
                        "source": "eodhd",
                    }
                )
                assert point.symbol == _SYMBOL
                if point.value_usd > 0:
                    assert point.value_usd > 1_000_000  # Apple's market cap is always > $1M


# =========================================================================
# Part C — Fundamentals section mapping (_map_fundamentals_sections)
# =========================================================================


class TestFundamentalsSectionMapping:
    """Verify _map_fundamentals_sections correctly maps all 18 sections from real data."""

    @pytest.mark.asyncio
    async def test_maps_all_financial_statement_sections(self, adapter: EODHDProviderAdapter):
        """FIX-F2/F3: Financial statements should be mapped with quarterly/yearly sub-dicts."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # Core financial statement sections
        assert "income_statement" in sections
        assert "balance_sheet" in sections
        assert "cash_flow" in sections

        # Each should have quarterly + yearly sub-dicts
        for key in ("income_statement", "balance_sheet", "cash_flow"):
            section = sections[key]
            assert isinstance(section, dict)
            assert "quarterly" in section
            assert "yearly" in section

    @pytest.mark.asyncio
    async def test_maps_highlights_separately_from_valuation(self, adapter: EODHDProviderAdapter):
        """FIX-F10: Highlights and valuation_ratios should be separate sections."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        assert "highlights" in sections
        assert "valuation_ratios" in sections
        assert sections["highlights"] is not sections["valuation_ratios"]

    @pytest.mark.asyncio
    async def test_maps_company_profile_from_general(self, adapter: EODHDProviderAdapter):
        """FIX-F4: General section → company_profile."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        assert "company_profile" in sections
        profile = sections["company_profile"]
        assert isinstance(profile, dict)
        # AAPL General section should have standard fields
        assert "Name" in profile or "Code" in profile

    @pytest.mark.asyncio
    async def test_maps_holders_sections(self, adapter: EODHDProviderAdapter):
        """FIX-F6: Holders.Institutions → institutional_holders, Holders.Funds → fund_holders."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # AAPL should have holders data
        if raw.get("Holders"):
            if raw["Holders"].get("Institutions"):
                assert "institutional_holders" in sections
            if raw["Holders"].get("Funds"):
                assert "fund_holders" in sections

    @pytest.mark.asyncio
    async def test_maps_insider_transactions_snapshot(self, adapter: EODHDProviderAdapter):
        """FIX-F7: InsiderTransactions → insider_transactions_snapshot."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # InsiderTransactions may or may not be populated
        if raw.get("InsiderTransactions"):
            assert "insider_transactions_snapshot" in sections

    @pytest.mark.asyncio
    async def test_maps_dividend_history_from_number_dividends_by_year(self, adapter: EODHDProviderAdapter):
        """FIX-F5: dividend_history comes from NumberDividendsByYear, not Dividends."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # AAPL pays dividends — NumberDividendsByYear should be present
        splits_divs = raw.get("SplitsDividends") or {}
        if splits_divs.get("NumberDividendsByYear"):
            assert "dividend_history" in sections
            assert isinstance(sections["dividend_history"], dict)

    @pytest.mark.asyncio
    async def test_maps_all_snapshot_sections(self, adapter: EODHDProviderAdapter):
        """Verify technicals_snapshot, share_statistics, splits_dividends, analyst_consensus."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # These should be present for AAPL
        for key in ("technicals_snapshot", "share_statistics", "splits_dividends", "analyst_consensus"):
            assert key in sections, f"Missing section: {key}"

    @pytest.mark.asyncio
    async def test_maps_earnings_subsections(self, adapter: EODHDProviderAdapter):
        """Verify earnings_history, earnings_trend, earnings_annual_trend."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        for key in ("earnings_history", "earnings_trend", "earnings_annual_trend"):
            assert key in sections, f"Missing section: {key}"

    @pytest.mark.asyncio
    async def test_maps_outstanding_shares(self, adapter: EODHDProviderAdapter):
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        if raw.get("outstandingShares"):
            assert "outstanding_shares" in sections

    @pytest.mark.asyncio
    async def test_section_count_is_at_least_13(self, adapter: EODHDProviderAdapter):
        """AAPL should map at least 13 of the 18 possible sections."""
        from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        sections = _map_fundamentals_sections(raw, symbol=_SYMBOL, source="eodhd")

        # Exclude metadata keys
        section_keys = {k for k in sections if k not in ("symbol", "source", "exchange", "period", "report_date")}
        assert (
            len(section_keys) >= 13
        ), f"Expected at least 13 sections for AAPL, got {len(section_keys)}: {section_keys}"


# =========================================================================
# Part D — Consumer-level fundamentals parsing edge cases
# =========================================================================


class TestFundamentalsConsumerEdgeCases:
    """Test edge cases in fundamentals data shapes that the consumer must handle."""

    @pytest.mark.asyncio
    async def test_financial_statement_date_keys_are_iso_dates(self, adapter: EODHDProviderAdapter):
        """Verify that financial statement date keys are parseable as ISO dates."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        income = raw["Financials"]["Income_Statement"]["quarterly"]

        for date_key in list(income.keys())[:5]:
            # The consumer calls datetime.fromisoformat(date_str)
            parsed = datetime.fromisoformat(date_key)
            assert parsed.year >= 2000

    @pytest.mark.asyncio
    async def test_number_dividends_by_year_uses_index_keys(self, adapter: EODHDProviderAdapter):
        """NumberDividendsByYear uses sequential index keys ('0', '1', ...) with Year/Count inside.

        This means the FundamentalsConsumer's date-keyed series handler will try to
        parse '0', '1' as dates, fail, then try int('0') → 0 which also fails
        datetime(0, 12, 31). These entries are silently skipped (continue).

        The consumer should be aware that this section's data shape doesn't match
        the _DATE_KEYED_SERIES_SECTIONS pattern. The entries contain {Year: int, Count: int}.
        """
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        divs = (raw.get("SplitsDividends") or {}).get("NumberDividendsByYear") or {}

        if divs:
            # Keys are sequential indices: "0", "1", "2", ...
            keys = list(divs.keys())[:5]
            for key in keys:
                assert key.isdigit(), f"Expected numeric index key, got {key!r}"
                entry = divs[key]
                assert isinstance(entry, dict)
                assert "Year" in entry
                assert "Count" in entry
                assert isinstance(entry["Year"], int)

    @pytest.mark.asyncio
    async def test_outstanding_shares_has_annual_quarterly_nesting(self, adapter: EODHDProviderAdapter):
        """outstandingShares is {annual: {...}, quarterly: {...}}, NOT flat date-keyed.

        The FundamentalsConsumer treats this as a _DATE_KEYED_SERIES_SECTION, so it
        iterates keys ("annual", "quarterly") — both fail date parsing and get skipped.
        The nested entries inside each have {date: "2024", shares: ..., dateFormatted: ...}.
        """
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        outstanding = raw.get("outstandingShares")

        if outstanding and isinstance(outstanding, dict):
            assert "annual" in outstanding or "quarterly" in outstanding
            # Each sub-dict is index-keyed with date/shares entries
            for period_type in ("annual", "quarterly"):
                sub = outstanding.get(period_type, {})
                if sub:
                    first_entry = next(iter(sub.values()))
                    assert isinstance(first_entry, dict)
                    assert "shares" in first_entry or "sharesMln" in first_entry

    @pytest.mark.asyncio
    async def test_earnings_trend_has_date_field_in_entries(self, adapter: EODHDProviderAdapter):
        """Earnings trend entries should have a 'date' field for period_end parsing."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        trend = (raw.get("Earnings") or {}).get("Trend") or {}

        if trend:
            for period_code, entry in list(trend.items())[:3]:
                assert isinstance(entry, dict), f"Expected dict for {period_code}, got {type(entry)}"
                # Entry should have a "date" field
                assert "date" in entry, f"Missing 'date' in earnings trend entry {period_code}"

    @pytest.mark.asyncio
    async def test_earnings_history_uses_date_keys(self, adapter: EODHDProviderAdapter):
        """Earnings History uses ISO date keys (e.g. '2024-01-25'), matching _DATE_KEYED_SERIES."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        history = (raw.get("Earnings") or {}).get("History") or {}

        if history:
            for date_key in list(history.keys())[:5]:
                parsed = datetime.fromisoformat(date_key)
                assert parsed.year >= 2000
                entry = history[date_key]
                assert isinstance(entry, dict)
                # Should have EPS fields
                assert "epsActual" in entry or "epsEstimate" in entry

    @pytest.mark.asyncio
    async def test_earnings_annual_uses_date_keys(self, adapter: EODHDProviderAdapter):
        """Earnings Annual trend uses date keys for the annual data."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        annual = (raw.get("Earnings") or {}).get("Annual") or {}

        if annual:
            for date_key in list(annual.keys())[:3]:
                parsed = datetime.fromisoformat(date_key)
                assert parsed.year >= 2000

    @pytest.mark.asyncio
    async def test_company_profile_has_metadata_fields(self, adapter: EODHDProviderAdapter):
        """FIX-F4: General section should have ISIN, Name, Sector, etc. for instruments metadata."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        general = raw.get("General") or {}

        # These fields are extracted by FundamentalsConsumer for instruments.update_metadata
        assert "ISIN" in general
        assert "Name" in general
        # Sector, Industry, CountryISO, CurrencyCode should also be present for AAPL
        assert "Sector" in general or "GicSector" in general
        assert "Industry" in general or "GicIndustry" in general
        assert "CountryISO" in general
        assert "CurrencyCode" in general

    @pytest.mark.asyncio
    async def test_snapshot_sections_are_flat_dicts(self, adapter: EODHDProviderAdapter):
        """Snapshot sections (Highlights, Valuation, Technicals) should be flat dicts, not nested."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)

        for key in ("Highlights", "Valuation", "Technicals", "SharesStats"):
            section = raw.get(key)
            if section:
                assert isinstance(section, dict), f"{key} should be a dict, got {type(section)}"
                # Should be flat (values are scalars or None, not nested dicts)
                has_scalar = any(isinstance(v, str | int | float | type(None)) for v in list(section.values())[:5])
                assert has_scalar, f"{key} should contain scalar values"

    @pytest.mark.asyncio
    async def test_analyst_ratings_shape(self, adapter: EODHDProviderAdapter):
        """AnalystRatings should be a flat dict (mapped as analyst_consensus snapshot)."""
        result = await adapter.fetch_fundamentals(symbol=_SYMBOL, exchange=_EXCHANGE)
        raw = _parse_json(result.raw_data)
        ratings = raw.get("AnalystRatings")

        if ratings:
            assert isinstance(ratings, dict)
            # Should have rating/target fields
            assert any(k in ratings for k in ("Rating", "TargetPrice", "StrongBuy", "Buy"))
