"""Unit tests for PredictionMarketConsumer (PRD-0019 Wave B-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot
from market_data.infrastructure.messaging.consumers.prediction_market_consumer import (
    PredictionMarketConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
_ISO = _NOW.isoformat()

_VALID_EVENT: dict = {
    "event_id": "01900000-0000-7000-8000-000000000001",
    "event_type": "market.prediction.snapshot",
    "schema_version": 1,
    "occurred_at": _ISO,
    "market_id": "0xabc123",
    "source": "polymarket",
    "question": "Will BTC reach 100k by end of 2026?",
    "description": "Bitcoin price target market",
    "outcomes": [
        {"name": "Yes", "token_id": "tok_yes", "price": 0.72},
        {"name": "No", "token_id": "tok_no", "price": 0.28},
    ],
    "volume_24h": 1500.5,
    "liquidity": 3000.0,
    "close_time": None,
    "resolution_status": "open",
    "resolved_answer": None,
    "minio_bronze_key": None,
    "market_slug": None,
    "correlation_id": None,
}


def _make_uow() -> MagicMock:
    """Return a fully-mocked UnitOfWork with async repo methods."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.ingestion_events = MagicMock()
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.prediction_markets = MagicMock()
    uow.prediction_markets.upsert = AsyncMock(return_value=PredictionMarket(market_id="0xabc123"))
    uow.prediction_market_snapshots = MagicMock()
    uow.prediction_market_snapshots.insert_if_not_exists = AsyncMock(return_value=True)
    uow.commit = AsyncMock()
    uow.failed_tasks = MagicMock()
    uow.failed_tasks.create = AsyncMock()
    # Batched-path bulk methods (2026-07-15 throughput fix).
    uow.ingestion_events.create_many_if_not_exists = AsyncMock(
        side_effect=lambda events: {eid for eid, _t, _s in events}
    )
    uow.prediction_markets.bulk_upsert = AsyncMock()
    uow.prediction_market_snapshots.bulk_insert_if_not_exists = AsyncMock(return_value=0)
    return uow


def _make_consumer(uow: MagicMock) -> PredictionMarketConsumer:
    consumer = PredictionMarketConsumer(
        uow_factory=lambda: uow,
        config=ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            topics=["market.prediction.v1"],
        ),
    )
    consumer._current_uow = uow
    return consumer


class TestProcessMessageUpsertMarket:
    """T-B-1-07: valid event → prediction_markets upserted."""

    @pytest.mark.asyncio
    async def test_upserts_market_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_markets.upsert.assert_called_once()
        call_args = uow.prediction_markets.upsert.call_args[0][0]
        assert isinstance(call_args, PredictionMarket)
        assert call_args.market_id == "0xabc123"
        assert call_args.question == "Will BTC reach 100k by end of 2026?"
        assert call_args.resolution_status == "open"

    @pytest.mark.asyncio
    async def test_market_outcomes_strip_prices(self) -> None:
        """Market entity outcomes should only have name/token_id, not price."""
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        call_args = uow.prediction_markets.upsert.call_args[0][0]
        for outcome in call_args.outcomes:
            assert "price" not in outcome
            assert "name" in outcome
            assert "token_id" in outcome


class TestProcessMessageInsertSnapshot:
    """T-B-1-07: valid event → snapshot inserted."""

    @pytest.mark.asyncio
    async def test_inserts_snapshot_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_snapshots.insert_if_not_exists.assert_called_once()
        snap: PredictionMarketSnapshot = uow.prediction_market_snapshots.insert_if_not_exists.call_args[0][0]
        assert isinstance(snap, PredictionMarketSnapshot)
        assert snap.market_id == "0xabc123"
        assert snap.outcomes_prices == {"Yes": 0.72, "No": 0.28}
        assert snap.volume_24h == Decimal("1500.5")
        assert snap.liquidity == Decimal("3000.0")
        assert snap.source_event_id == _VALID_EVENT["event_id"]

    @pytest.mark.asyncio
    async def test_commit_not_called_in_process_message(self) -> None:
        """M-04: process_message must NOT call commit — the base class owns the commit.

        Calling uow.commit() inside process_message causes a double-commit per
        message because BaseKafkaConsumer also commits after process_message returns.
        """
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.commit.assert_not_called()


class TestProcessMessageIdempotent:
    """T-B-1-07: same event_id twice → skips second write."""

    @pytest.mark.asyncio
    async def test_idempotent_second_delivery_skipped(self) -> None:
        uow = _make_uow()
        # First call: new event; second call: duplicate.
        uow.ingestion_events.create_if_not_exists = AsyncMock(side_effect=[True, False])
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})
        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        # Writes should happen exactly once; commit is owned by base class
        assert uow.prediction_markets.upsert.call_count == 1
        assert uow.prediction_market_snapshots.insert_if_not_exists.call_count == 1
        # M-04: commit is not called inside process_message — base class commits
        assert uow.commit.call_count == 0


class TestProcessMessageDuplicateEventSkipped:
    """T-B-1-07: create_if_not_exists returns False → no writes."""

    @pytest.mark.asyncio
    async def test_duplicate_event_skips_all_writes(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_markets.upsert.assert_not_called()
        uow.prediction_market_snapshots.insert_if_not_exists.assert_not_called()
        uow.commit.assert_not_called()


class TestProcessMessageMalformedData:
    """T-B-1-07: missing market_id → MalformedDataError."""

    @pytest.mark.asyncio
    async def test_missing_event_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        bad_event = {**_VALID_EVENT, "event_id": None}

        with pytest.raises(MalformedDataError, match="event_id"):
            await consumer.process_message(key=None, value=bad_event, headers={})

    @pytest.mark.asyncio
    async def test_missing_market_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        bad_event = {**_VALID_EVENT, "market_id": None}

        with pytest.raises(MalformedDataError, match="market_id"):
            await consumer.process_message(key=None, value=bad_event, headers={})

    @pytest.mark.asyncio
    async def test_missing_occurred_at_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        bad_event = {**_VALID_EVENT, "occurred_at": "not-a-date"}

        with pytest.raises(MalformedDataError, match="occurred_at"):
            await consumer.process_message(key=None, value=bad_event, headers={})


class TestProcessBatch:
    """2026-07-15 throughput fix: batched consume path writes correctly + is idempotent."""

    @pytest.mark.asyncio
    async def test_batch_bulk_upserts_new_events(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        e2 = {**_VALID_EVENT, "event_id": "01900000-0000-7000-8000-000000000002", "market_id": "0xdef456"}
        items = [(None, _VALID_EVENT, {}), (None, e2, {})]

        await consumer.process_batch(items)

        # One bulk dedup, one bulk upsert, one bulk snapshot insert — no per-row calls.
        uow.ingestion_events.create_many_if_not_exists.assert_called_once()
        uow.prediction_markets.bulk_upsert.assert_called_once()
        uow.prediction_market_snapshots.bulk_insert_if_not_exists.assert_called_once()
        uow.prediction_markets.upsert.assert_not_called()
        # Both markets forwarded to the bulk upsert.
        markets = uow.prediction_markets.bulk_upsert.call_args[0][0]
        assert {m.market_id for m in markets} == {"0xabc123", "0xdef456"}
        # M-04: process_batch must NOT commit — the base owns the single commit.
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_idempotent_all_duplicates_skipped(self) -> None:
        uow = _make_uow()
        # Dedup returns NO new ids → whole batch already materialised.
        uow.ingestion_events.create_many_if_not_exists = AsyncMock(return_value=set())
        consumer = _make_consumer(uow)

        await consumer.process_batch([(None, _VALID_EVENT, {})])

        uow.prediction_markets.bulk_upsert.assert_not_called()
        uow.prediction_market_snapshots.bulk_insert_if_not_exists.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_only_new_events_written(self) -> None:
        uow = _make_uow()
        e2 = {**_VALID_EVENT, "event_id": "01900000-0000-7000-8000-000000000002", "market_id": "0xdef456"}
        # Only the second event is new.
        uow.ingestion_events.create_many_if_not_exists = AsyncMock(return_value={e2["event_id"]})
        consumer = _make_consumer(uow)

        await consumer.process_batch([(None, _VALID_EVENT, {}), (None, e2, {})])

        markets = uow.prediction_markets.bulk_upsert.call_args[0][0]
        assert [m.market_id for m in markets] == ["0xdef456"]

    @pytest.mark.asyncio
    async def test_batch_malformed_record_skipped_not_fatal(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        bad = {**_VALID_EVENT, "event_id": "01900000-0000-7000-8000-000000000003", "market_id": None}
        # One good, one malformed → good one still written, no raise.
        await consumer.process_batch([(None, _VALID_EVENT, {}), (None, bad, {})])

        markets = uow.prediction_markets.bulk_upsert.call_args[0][0]
        assert [m.market_id for m in markets] == ["0xabc123"]
