"""Live AAPL pipeline tests — real EODHD API calls, real TimescaleDB container.

Tests the full consumer pipeline end-to-end for AAPL.US:
  - Fetches real data from EODHD (demo API key, free tier)
  - Canonicalises it using the contracts models
  - Runs each consumer's process_message() against a testcontainers TimescaleDB
  - Asserts that every market-data table contains the correct data

Skip conditions:
  - Network unreachable → skip all (not failed)
  - testcontainers / Docker not available → skip

Run:
    cd services/market-data
    .venv/bin/pytest tests/live/ -v
"""

from __future__ import annotations

import json
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Network guard
# ---------------------------------------------------------------------------


def _is_network_available() -> bool:
    try:
        socket.create_connection(("eodhd.com", 443), timeout=5)
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(not _is_network_available(), reason="No network to eodhd.com"),
]

# EODHD demo key gives free access to AAPL.US
_API_KEY = "demo"
_SYMBOL = "AAPL"
_EXCHANGE = "US"
_BASE_URL = "https://eodhd.com/api"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eodhd_get(path: str, params: dict) -> dict | list:
    """Synchronous EODHD request (used in fixtures, not async tests)."""
    import httpx

    params.setdefault("fmt", "json")
    params["api_token"] = _API_KEY
    resp = httpx.get(f"{_BASE_URL}/{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _build_fundamentals_canonical(eodhd_raw: dict) -> bytes:
    """Map a raw EODHD fundamentals response to canonical JSONL bytes.

    Replicates the key mapping logic from market-ingestion's
    ``_map_fundamentals_sections`` so market-data consumers can process it.
    """
    from contracts.canonical.fundamentals import CanonicalFundamentals  # type: ignore[import-untyped]

    financials = eodhd_raw.get("Financials") or {}
    earnings = eodhd_raw.get("Earnings") or {}
    splits_divs = eodhd_raw.get("SplitsDividends") or {}

    sections: dict[str, Any] = {
        "symbol": _SYMBOL,
        "source": "eodhd",
        "exchange": _EXCHANGE,
        # Financial sections
        "income_statement": financials.get("Income_Statement"),
        "balance_sheet": financials.get("Balance_Sheet"),
        "cash_flow": financials.get("Cash_Flow"),
        # Snapshot sections
        "highlights": eodhd_raw.get("Highlights"),
        "valuation_ratios": eodhd_raw.get("Valuation"),
        "technicals_snapshot": eodhd_raw.get("Technicals"),
        "share_statistics": eodhd_raw.get("SharesStats"),
        "splits_dividends": eodhd_raw.get("SplitsDividends"),
        "analyst_consensus": eodhd_raw.get("AnalystRatings"),
        # Earnings
        "earnings_history": earnings.get("History"),
        "earnings_trend": earnings.get("Trend"),
        "earnings_annual_trend": earnings.get("Annual"),
        # Company
        "company_profile": eodhd_raw.get("General"),
        "institutional_holders": (eodhd_raw.get("Holders") or {}).get("Institutions"),
        "fund_holders": (eodhd_raw.get("Holders") or {}).get("Funds"),
        "insider_transactions_snapshot": eodhd_raw.get("InsiderTransactions"),
        "dividend_history": splits_divs.get("NumberDividendsByYear"),
        "outstanding_shares": eodhd_raw.get("outstandingShares"),
    }
    # Remove None sections so they're skipped cleanly
    sections = {k: v for k, v in sections.items() if v is not None}

    fund = CanonicalFundamentals.from_dict(sections)
    return (json.dumps(fund.to_dict()) + "\n").encode("utf-8")


def _build_ohlcv_canonical(bars: list[dict]) -> bytes:
    """Convert raw EODHD OHLCV bar list to canonical JSONL bytes."""
    from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]

    lines = []
    for b in bars:
        row = {
            "symbol": _SYMBOL,
            "exchange": _EXCHANGE,
            "source": "eodhd",
            "date": b.get("date", ""),
            "open": b.get("open", 0),
            "high": b.get("high", 0),
            "low": b.get("low", 0),
            "close": b.get("close", 0),
            "volume": b.get("volume", 0),
            "adjusted_close": b.get("adjusted_close"),
        }
        bar = CanonicalOHLCVBar.from_dict(row)
        lines.append(json.dumps(bar.to_dict()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_quote_canonical(raw_quote: dict) -> bytes:
    """Convert raw EODHD real-time quote to canonical JSON bytes."""
    from contracts.canonical.quotes import CanonicalQuote  # type: ignore[import-untyped]

    last = raw_quote.get("close") or raw_quote.get("last", 0.0)
    ts_raw = raw_quote.get("timestamp")
    if isinstance(ts_raw, int | float):
        timestamp = datetime.fromtimestamp(ts_raw, tz=UTC).isoformat()
    else:
        timestamp = datetime.now(tz=UTC).isoformat()

    row = {
        "symbol": _SYMBOL,
        "exchange": _EXCHANGE,
        "source": "eodhd",
        "bid": raw_quote.get("bid") or last,
        "ask": raw_quote.get("ask") or last,
        "last": last,
        "volume": raw_quote.get("volume", 0),
        "timestamp": timestamp,
    }
    quote = CanonicalQuote.from_dict(row)
    return (json.dumps(quote.to_dict()) + "\n").encode("utf-8")


def _make_event(dataset_type: str, sha256: str = "live-test-sha256") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "market.dataset.fetched",
        "schema_version": 1,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "correlation_id": None,
        "causation_id": None,
        "task_id": str(uuid.uuid4()),
        "provider": "eodhd",
        "dataset_type": dataset_type,
        "symbol": _SYMBOL,
        "exchange": _EXCHANGE,
        "timeframe": "1d",
        "variant": "annual",
        "range_start": "2024-01-01T00:00:00+00:00",
        "range_end": "2024-12-31T23:59:59+00:00",
        "bronze_ref_bucket": "market-bronze",
        "bronze_ref_key": f"test/{dataset_type}/AAPL.json",
        "bronze_ref_sha256": sha256,
        "bronze_ref_byte_length": 1024,
        "bronze_ref_mime_type": "application/json",
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": f"test/{dataset_type}/AAPL.jsonl",
        "canonical_ref_sha256": sha256,
        "canonical_ref_byte_length": 512,
        "canonical_ref_mime_type": "application/x-ndjson",
        "canonical_schema_version": 1,
        "row_count": 1,
    }


# ---------------------------------------------------------------------------
# Session-scoped DB fixture (testcontainers, migrated once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _live_db_url():
    """Start a TimescaleDB testcontainer, run Alembic, return the asyncpg URL."""
    import os

    from alembic import command
    from alembic.config import Config
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        dbname="market_data_db",
        username="postgres",
        password="postgres",
    ) as container:
        raw_url = container.get_connection_url()
        asyncpg_url = raw_url.replace("postgresql://", "postgresql+asyncpg://").replace("psycopg2", "asyncpg")
        # Set ALEMBIC_URL so alembic/env.py picks up the testcontainer URL instead
        # of overriding it with _Settings().database_url (defaults to localhost:5432).
        os.environ["ALEMBIC_URL"] = asyncpg_url
        try:
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")
        finally:
            os.environ.pop("ALEMBIC_URL", None)
        yield asyncpg_url


@pytest.fixture
async def _live_uow_factory(_live_db_url: str):
    """Return a UoW factory and engine backed by the live test container."""
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_live_db_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def make_uow() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory, factory)

    yield make_uow, engine

    # Truncate after each test so they're isolated
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                "income_statements, balance_sheets, cash_flow_statements, "
                "valuation_ratios, technicals_snapshots, share_statistics, "
                "splits_dividends, analyst_consensus, earnings_history, "
                "earnings_trends, earnings_annual_trends, dividend_history, "
                "outstanding_shares, "
                "highlights, company_profiles, institutional_holders, "
                "fund_holders, insider_transactions_snapshot, "
                "ohlcv_bars, quotes, "
                "ingestion_events, failed_tasks, outbox_events, "
                "instruments, securities "
                "CASCADE"
            )
        )
        await conn.commit()
    await engine.dispose()


# ---------------------------------------------------------------------------
# ── OHLCV consumer — AAPL daily bars ─────────────────────────────────────────
# ---------------------------------------------------------------------------


class TestAAPLOHLCV:
    """Verify OHLCV pipeline populates ohlcv_bars and instrument flags correctly."""

    async def test_ohlcv_bars_materialized(self, _live_uow_factory) -> None:
        """EODHD AAPL daily bars → ohlcv_bars rows present, instrument has_ohlcv=True."""
        from datetime import date

        from market_data.domain.enums import Timeframe
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        # Fetch from EODHD
        raw_bars: list[dict] = _eodhd_get(  # type: ignore[assignment]
            f"eod/{_SYMBOL}.{_EXCHANGE}",
            {"from": "2024-01-02", "to": "2024-01-31"},
        )
        assert isinstance(raw_bars, list) and len(raw_bars) > 0, "EODHD returned no OHLCV bars"

        canonical_bytes = _build_ohlcv_canonical(raw_bars)

        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-ohlcv",
            topics=["market.dataset.fetched"],
        )
        consumer = OHLCVConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("ohlcv", sha256="aapl-ohlcv-jan-2024")
        async with (
            SqlAlchemyUnitOfWork(
                engine.sync_engine.__class__,  # unused — use direct uow below
            )
            if False
            else uow_factory() as uow
        ):
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        # Query results in a fresh UoW
        async with uow_factory() as uow:
            instr = await uow.instruments.find_by_symbol_exchange(_SYMBOL, _EXCHANGE)
            assert instr is not None, "Instrument was not created"
            assert instr.symbol == _SYMBOL
            assert instr.exchange == _EXCHANGE
            assert instr.flags.has_ohlcv is True, "has_ohlcv should be True after OHLCV ingest"

            bars = await uow.ohlcv.find_by_instrument_timeframe_range(
                instr.id,
                Timeframe.ONE_DAY,
                date(2024, 1, 2),
                date(2024, 1, 31),
            )
            assert len(bars) >= 10, f"Expected ≥10 trading days, got {len(bars)}"
            # Spot-check numerical fields
            for bar in bars:
                assert bar.open > 0, "open should be positive"
                assert bar.high >= bar.low, "high should be >= low"
                assert bar.close > 0, "close should be positive"
                assert bar.volume >= 0, "volume should be non-negative"

    async def test_weekly_ohlcv_bars(self, _live_uow_factory) -> None:
        """Weekly bars are persisted with timeframe=1w."""
        from datetime import date

        from market_data.domain.enums import Timeframe
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, _ = _live_uow_factory

        raw_bars: list[dict] = _eodhd_get(  # type: ignore[assignment]
            f"eod/{_SYMBOL}.{_EXCHANGE}",
            {"from": "2024-01-01", "to": "2024-03-31", "period": "w"},
        )
        assert isinstance(raw_bars, list) and len(raw_bars) > 0

        canonical_bytes = _build_ohlcv_canonical(raw_bars)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-ohlcv-w",
            topics=["market.dataset.fetched"],
        )
        consumer = OHLCVConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("ohlcv", sha256="aapl-ohlcv-weekly-q1-2024")
        event["timeframe"] = "1w"

        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with uow_factory() as uow:
            instr = await uow.instruments.find_by_symbol_exchange(_SYMBOL, _EXCHANGE)
            assert instr is not None
            bars = await uow.ohlcv.find_by_instrument_timeframe_range(
                instr.id,
                Timeframe.ONE_WEEK,
                date(2024, 1, 1),
                date(2024, 3, 31),
            )
            assert len(bars) >= 1, "Expected at least 1 weekly bar"


# ---------------------------------------------------------------------------
# ── Quotes consumer ───────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


class TestAAPLQuotes:
    """Verify quotes pipeline populates the quotes table correctly."""

    async def test_quote_materialized(self, _live_uow_factory) -> None:
        """EODHD AAPL real-time quote → quotes row present, bid/ask/last > 0."""
        from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, _ = _live_uow_factory

        raw_quote = _eodhd_get(f"real-time/{_SYMBOL}.{_EXCHANGE}", {})
        assert isinstance(raw_quote, dict), "Expected a dict from real-time endpoint"

        canonical_bytes = _build_quote_canonical(raw_quote)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-quotes",
            topics=["market.dataset.fetched"],
        )
        consumer = QuotesConsumer(
            uow_factory=uow_factory,
            object_storage=storage,
            valkey_client=None,
            config=config,
        )

        event = _make_event("quotes", sha256="aapl-quote-live")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with uow_factory() as uow:
            instr = await uow.instruments.find_by_symbol_exchange(_SYMBOL, _EXCHANGE)
            assert instr is not None
            assert instr.flags.has_quotes is True, "has_quotes should be True after quote ingest"

            quote = await uow.quotes.find_by_instrument(instr.id)
            assert quote is not None, "Quote row should exist"
            assert float(quote.last) > 0, f"last price should be positive, got {quote.last}"
            assert float(quote.bid) >= 0, "bid should be non-negative"
            assert float(quote.ask) >= 0, "ask should be non-negative"
            assert quote.timestamp is not None, "timestamp should be set"


# ---------------------------------------------------------------------------
# ── Fundamentals consumer ─────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


class TestAAPLFundamentals:
    """Verify fundamentals pipeline populates all section tables and enriches the
    instruments/securities rows with company metadata."""

    @pytest.fixture(scope="class")
    def aapl_fundamentals_raw(self) -> dict:
        """Fetch AAPL.US full fundamentals once per class (expensive call)."""
        data = _eodhd_get(f"fundamentals/{_SYMBOL}.{_EXCHANGE}", {})
        assert isinstance(data, dict), "Expected a dict from fundamentals endpoint"
        assert "General" in data, "Expected 'General' section in fundamentals"
        return data  # type: ignore[return-value]

    async def test_instrument_metadata_populated(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """After fundamentals ingest, instruments.name/isin/sector/industry/country/currency
        are all populated from the EODHD General section."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, _ = _live_uow_factory
        general = aapl_fundamentals_raw["General"]

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-fundamentals",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-live")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with uow_factory() as uow:
            instr = await uow.instruments.find_by_symbol_exchange(_SYMBOL, _EXCHANGE)
            assert instr is not None, "Instrument should have been created"
            assert instr.flags.has_fundamentals is True

            # Instrument metadata — populated from General section
            expected_name = general.get("Name")
            expected_isin = general.get("ISIN")
            expected_sector = general.get("Sector")
            expected_country = general.get("CountryISO")
            expected_currency = general.get("CurrencyCode")

            if expected_name:
                assert instr.name == expected_name, f"Instrument name mismatch: {instr.name!r} != {expected_name!r}"
            if expected_isin:
                assert instr.isin == expected_isin, f"ISIN mismatch: {instr.isin!r} != {expected_isin!r}"
            if expected_sector:
                assert instr.sector == expected_sector, f"Sector mismatch: {instr.sector!r} != {expected_sector!r}"
            if expected_country:
                assert instr.country == expected_country, f"Country mismatch: {instr.country!r} != {expected_country!r}"
            if expected_currency:
                assert (
                    instr.currency_code == expected_currency
                ), f"Currency mismatch: {instr.currency_code!r} != {expected_currency!r}"

    async def test_security_metadata_populated(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """After fundamentals ingest, securities.name and isin are enriched from General."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, _engine = _live_uow_factory
        general = aapl_fundamentals_raw["General"]

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-fundaments-sec",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-sec-live")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with uow_factory() as uow:
            instr = await uow.instruments.find_by_symbol_exchange(_SYMBOL, _EXCHANGE)
            assert instr is not None

            sec = await uow.securities.find_by_id(instr.security_id)
            assert sec is not None, "Parent Security should exist"

            company_name = general.get("Name")
            if company_name:
                assert sec.name == company_name, f"Security name should be '{company_name}', got '{sec.name}'"

    async def test_income_statements_present(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """After fundamentals ingest, income_statements table has rows for AAPL."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-income",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-income")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM income_statements i "
                    "JOIN instruments ins ON i.instrument_id = ins.id "
                    "WHERE ins.symbol = :sym AND ins.exchange = :exch"
                ),
                {"sym": _SYMBOL, "exch": _EXCHANGE},
            )
            count = row.scalar_one()
        assert count > 0, f"Expected income_statement rows for {_SYMBOL}, got 0"

    async def test_balance_sheets_present(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """balance_sheets table has rows after fundamentals ingest."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-bs",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-bs")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM balance_sheets i "
                    "JOIN instruments ins ON i.instrument_id = ins.id "
                    "WHERE ins.symbol = :sym"
                ),
                {"sym": _SYMBOL},
            )
            count = row.scalar_one()
        assert count > 0, f"Expected balance_sheet rows for {_SYMBOL}, got 0"

    async def test_company_profile_present(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """company_profiles table has exactly one row for AAPL after ingest."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-prof",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-prof")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM company_profiles cp "
                    "JOIN instruments ins ON cp.instrument_id = ins.id "
                    "WHERE ins.symbol = :sym"
                ),
                {"sym": _SYMBOL},
            )
            count = row.scalar_one()
        assert count == 1, f"Expected exactly 1 company_profile row for {_SYMBOL}, got {count}"

    async def test_highlights_present(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """highlights table has a row after fundamentals ingest."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-highlights",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-hl")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM highlights h "
                    "JOIN instruments ins ON h.instrument_id = ins.id "
                    "WHERE ins.symbol = :sym"
                ),
                {"sym": _SYMBOL},
            )
            count = row.scalar_one()
        assert count > 0, f"Expected highlights rows for {_SYMBOL}, got 0"

    async def test_earnings_history_present(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """earnings_history table has rows after fundamentals ingest."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-earnings",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-earn")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        async with engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM earnings_history eh "
                    "JOIN instruments ins ON eh.instrument_id = ins.id "
                    "WHERE ins.symbol = :sym"
                ),
                {"sym": _SYMBOL},
            )
            count = row.scalar_one()
        assert count > 0, f"Expected earnings_history rows for {_SYMBOL}, got 0"

    async def test_all_sections_non_empty(self, _live_uow_factory, aapl_fundamentals_raw: dict) -> None:
        """Aggregate check: all major section tables have ≥1 row for AAPL after a single
        fundamentals ingest. This catches any silent data-loss regressions."""
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
            FundamentalsConsumer,
        )
        from sqlalchemy import text

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        uow_factory, engine = _live_uow_factory

        canonical_bytes = _build_fundamentals_canonical(aapl_fundamentals_raw)
        storage = AsyncMock()
        storage.get_bytes.return_value = canonical_bytes

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="live-test-all",
            topics=["market.dataset.fetched"],
        )
        consumer = FundamentalsConsumer(uow_factory=uow_factory, object_storage=storage, config=config)

        event = _make_event("fundamentals", sha256="aapl-fundamentals-all")
        async with uow_factory() as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(None, event, {})
            await uow.commit()

        # Tables expected to have ≥ 1 row after a complete fundamentals ingest
        expected_tables = [
            "income_statements",
            "balance_sheets",
            "cash_flow_statements",
            "valuation_ratios",
            "technicals_snapshots",
            "share_statistics",
            "splits_dividends",
            "analyst_consensus",
            "earnings_history",
            "highlights",
            "company_profiles",
        ]

        empty_required: list[str] = []
        async with engine.connect() as conn:
            for table in expected_tables:
                row = await conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table} t "  # noqa: S608
                        "JOIN instruments ins ON t.instrument_id = ins.id "
                        "WHERE ins.symbol = :sym"
                    ),
                    {"sym": _SYMBOL},
                )
                count = row.scalar_one()
                if count == 0:
                    empty_required.append(table)

        assert not empty_required, f"Expected data in all required tables but these were empty: {empty_required}"
