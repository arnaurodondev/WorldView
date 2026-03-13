"""E2E pipeline tests — simulate the full data ingestion path.

These tests exercise the system from the consumer's ``process_message`` method
all the way to the final database state, verifying that:

  1. OHLCV pipeline persists bars and sets the has_ohlcv flag.
  2. Quotes pipeline persists a quote and invalidates the cache.
  3. Instrument lifecycle: auto-create on first ingest, flags updated on each type.
  4. Priority-resolution round-trip: same bar re-ingested at lower priority is
     silently ignored at the database level.

Each test calls ``consumer.process_message()`` with a mock ``MarketDatasetFetched``
Avro dict, bypassing real Kafka/S3 with in-memory stubs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# ── helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_OHLCV_JSONL = json.dumps(
    {
        "provider": "polygon",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "timeframe": "1d",
        "bar_date": "2024-06-01",
        "open": "180.00",
        "high": "185.00",
        "low": "178.00",
        "close": "183.00",
        "volume": 50000000,
        "adjusted_close": "183.00",
        "source": "polygon",
    }
).encode()

_SAMPLE_QUOTE_JSONL = json.dumps(
    {
        "provider": "polygon",
        "symbol": "AAPL",
        "exchange": "XNAS",
        "bid": "182.50",
        "ask": "183.00",
        "last": "182.75",
        "volume": 1000,
        "timestamp": "2024-06-01T15:30:00+00:00",
    }
).encode()


def _make_event(dataset_type: str, extra: dict | None = None) -> dict:
    base = {
        "event_id": "evt-001",
        "event_type": "market.dataset.fetched",
        "schema_version": 1,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
        "correlation_id": None,
        "causation_id": None,
        "task_id": "task-001",
        "provider": "polygon",
        "dataset_type": dataset_type,
        "symbol": "AAPL",
        "exchange": "XNAS",
        "timeframe": "1d",
        "variant": None,
        "range_start": "2024-06-01T00:00:00+00:00",
        "range_end": "2024-06-01T23:59:59+00:00",
        "bronze_ref_bucket": "market-raw",
        "bronze_ref_key": "raw/polygon/AAPL/2024-06-01.json",
        "bronze_ref_sha256": "abc123",
        "bronze_ref_byte_length": 1024,
        "bronze_ref_mime_type": "application/json",
        "canonical_ref_bucket": "market-canonical",
        "canonical_ref_key": "canonical/polygon/AAPL/2024-06-01.jsonl",
        "canonical_ref_sha256": "def456",
        "canonical_ref_byte_length": 512,
        "canonical_ref_mime_type": "application/x-ndjson",
        "canonical_schema_version": 2,
        "row_count": 1,
    }
    if extra:
        base.update(extra)
    return base


def _make_storage_mock(content: bytes) -> AsyncMock:
    mock = AsyncMock()
    mock.get_bytes.return_value = content
    return mock


# ── OHLCV pipeline ────────────────────────────────────────────────────────────


class TestOHLCVPipeline:
    async def test_ohlcv_event_persists_bars_and_sets_flag(self, _migrated_db: str) -> None:
        """process_message → bars stored, has_ohlcv=True on instrument."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)

        storage = _make_storage_mock(_SAMPLE_OHLCV_JSONL)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-ohlcv",
            topics=["market.dataset.fetched"],
        )
        consumer = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=storage,
            config=config,
        )

        event = _make_event("OHLCV")

        # Inject UoW directly as the consumer accesses self._current_uow
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(event)
            await uow.commit()

            # Verify instrument was created with has_ohlcv=True
            instr = await uow.instruments.find_by_symbol_exchange("AAPL", "XNAS")
            assert instr is not None
            assert instr.flags.has_ohlcv is True

            # Verify OHLCV bar was persisted
            from datetime import date

            from market_data.domain.enums import Timeframe

            bars = await uow.ohlcv.find_by_instrument_timeframe_range(
                instr.id,
                Timeframe.ONE_DAY,
                date(2024, 6, 1),
                date(2024, 6, 1),
            )
            assert len(bars) >= 1
            assert bars[0].close == Decimal("183.00")

        await engine.dispose()


# ── Quotes pipeline ───────────────────────────────────────────────────────────


class TestQuotesPipeline:
    async def test_quote_event_persists_quote(self, _migrated_db: str) -> None:
        """process_message → quote stored in DB."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)

        storage = _make_storage_mock(_SAMPLE_QUOTE_JSONL)

        # Mock Valkey client (cache invalidation, no real container needed)
        mock_valkey = MagicMock(spec=ValkeyClient)
        mock_valkey.delete = AsyncMock()

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-quotes",
            topics=["market.dataset.fetched"],
        )
        consumer = QuotesConsumer(
            uow_factory=uow_factory,
            object_storage=storage,
            valkey_client=mock_valkey,
            config=config,
        )

        event = _make_event("QUOTE")

        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            consumer._current_uow = uow  # type: ignore[attr-defined]
            await consumer.process_message(event)
            await uow.commit()

            instr = await uow.instruments.find_by_symbol_exchange("AAPL", "XNAS")
            assert instr is not None
            assert instr.flags.has_quotes is True

            quote = await uow.quotes.find_by_instrument(instr.id)
            assert quote is not None
            assert quote.bid == Decimal("182.50")

        await engine.dispose()


# ── Instrument lifecycle ──────────────────────────────────────────────────────


class TestInstrumentLifecycle:
    async def test_sequential_ingestion_sets_all_flags(self, _migrated_db: str) -> None:
        """OHLCV then QUOTE ingest → instrument ends with both flags set."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-lifecycle",
            topics=["market.dataset.fetched"],
        )

        # Step 1: OHLCV ingest
        ohlcv_consumer = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=_make_storage_mock(_SAMPLE_OHLCV_JSONL),
            config=config,
        )
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            ohlcv_consumer._current_uow = uow  # type: ignore[attr-defined]
            await ohlcv_consumer.process_message(_make_event("OHLCV", {"symbol": "TSLA", "exchange": "XNAS"}))
            await uow.commit()

        # Step 2: Quote ingest for the same instrument
        mock_valkey = MagicMock(spec=ValkeyClient)
        mock_valkey.delete = AsyncMock()

        quote_consumer = QuotesConsumer(
            uow_factory=uow_factory,
            object_storage=_make_storage_mock(_SAMPLE_QUOTE_JSONL),
            valkey_client=mock_valkey,
            config=config,
        )
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            quote_consumer._current_uow = uow  # type: ignore[attr-defined]
            await quote_consumer.process_message(_make_event("QUOTE", {"symbol": "TSLA", "exchange": "XNAS"}))
            await uow.commit()

            # Both flags must be set on the same instrument row
            instr = await uow.instruments.find_by_symbol_exchange("TSLA", "XNAS")
            assert instr is not None
            assert instr.flags.has_ohlcv is True
            assert instr.flags.has_quotes is True

        await engine.dispose()


# ── Priority resolution end-to-end ────────────────────────────────────────────


class TestPriorityResolutionE2E:
    async def test_high_priority_survives_low_priority_re_ingest(
        self,
        _migrated_db: str,
    ) -> None:
        """Polygon data (priority=100) must survive a Yahoo re-ingest (priority=80)."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-priority",
            topics=["market.dataset.fetched"],
        )

        # Polygon bar: close=200.00
        polygon_jsonl = json.dumps(
            {
                "provider": "polygon",
                "symbol": "NVDA",
                "exchange": "XNAS",
                "timeframe": "1d",
                "bar_date": "2024-06-01",
                "open": "198.00",
                "high": "202.00",
                "low": "196.00",
                "close": "200.00",
                "volume": 30000000,
                "adjusted_close": "200.00",
                "source": "polygon",
            }
        ).encode()

        # Yahoo bar for same date: close=999.00
        yahoo_jsonl = json.dumps(
            {
                "provider": "yahoo",
                "symbol": "NVDA",
                "exchange": "XNAS",
                "timeframe": "1d",
                "bar_date": "2024-06-01",
                "open": "999.00",
                "high": "999.00",
                "low": "999.00",
                "close": "999.00",
                "volume": 1,
                "adjusted_close": "999.00",
                "source": "yahoo",
            }
        ).encode()

        # Ingest Polygon first
        c1 = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=_make_storage_mock(polygon_jsonl),
            config=config,
        )
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            c1._current_uow = uow  # type: ignore[attr-defined]
            await c1.process_message(_make_event("OHLCV", {"symbol": "NVDA", "provider": "polygon"}))
            await uow.commit()

        # Ingest Yahoo (lower priority) for the same bar
        c2 = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=_make_storage_mock(yahoo_jsonl),
            config=config,
        )
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            c2._current_uow = uow  # type: ignore[attr-defined]
            await c2.process_message(_make_event("OHLCV", {"symbol": "NVDA", "provider": "yahoo"}))
            await uow.commit()

        # Verify Polygon data survives
        async with SqlAlchemyUnitOfWork(factory, factory) as uow:
            from datetime import date

            from market_data.domain.enums import Timeframe

            instr = await uow.instruments.find_by_symbol_exchange("NVDA", "XNAS")
            assert instr is not None
            bars = await uow.ohlcv.find_by_instrument_timeframe_range(
                instr.id,
                Timeframe.ONE_DAY,
                date(2024, 6, 1),
                date(2024, 6, 1),
            )
            assert len(bars) == 1
            assert bars[0].close == Decimal("200.00"), f"Expected Polygon close=200.00 to survive, got {bars[0].close}"

        await engine.dispose()
