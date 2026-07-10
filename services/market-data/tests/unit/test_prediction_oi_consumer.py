"""Unit tests for PredictionOIConsumer (PLAN-0056 Wave A3, T-A-3-04)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionMarketOI
from market_data.infrastructure.messaging.consumers.prediction_oi_consumer import (
    PredictionOIConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_VALID_EVENT: dict = {
    "event_id": "01900000-0000-7000-8000-0000000000d4",
    "event_type": "market.prediction.oi",
    "schema_version": 1,
    "occurred_at": "2026-04-09T12:00:00+00:00",
    "market_id": "0xabc123",
    "snapshot_date": "2026-04-09",
    "total_oi_usd": 125000.5,
    "total_volume_24h_usd": 50000.25,
    "correlation_id": None,
}


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.ingestion_events = MagicMock()
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.prediction_market_oi = MagicMock()
    uow.prediction_market_oi.upsert = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.failed_tasks = MagicMock()
    uow.failed_tasks.create = AsyncMock()
    return uow


def _make_consumer(uow: MagicMock) -> PredictionOIConsumer:
    consumer = PredictionOIConsumer(
        uow_factory=lambda: uow,
        config=ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            topics=["market.prediction.oi.v1"],
        ),
    )
    consumer._current_uow = uow
    return consumer


class TestProcessMessageUpsertOI:
    @pytest.mark.asyncio
    async def test_upserts_oi_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_oi.upsert.assert_called_once()
        oi: PredictionMarketOI = uow.prediction_market_oi.upsert.call_args[0][0]
        assert isinstance(oi, PredictionMarketOI)
        assert oi.market_id == "0xabc123"
        assert oi.snapshot_date == date(2026, 4, 9)
        assert oi.total_oi_usd == Decimal("125000.5")
        assert oi.total_volume_24h_usd == Decimal("50000.25")

    @pytest.mark.asyncio
    async def test_null_money_fields_map_to_none(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        payload = {**_VALID_EVENT, "total_oi_usd": None, "total_volume_24h_usd": None}

        await consumer.process_message(key=None, value=payload, headers={})

        oi: PredictionMarketOI = uow.prediction_market_oi.upsert.call_args[0][0]
        assert oi.total_oi_usd is None
        assert oi.total_volume_24h_usd is None

    @pytest.mark.asyncio
    async def test_datetime_snapshot_date_tolerated(self) -> None:
        """A producer sending a full ISO datetime still yields the calendar day."""
        uow = _make_uow()
        consumer = _make_consumer(uow)
        payload = {**_VALID_EVENT, "snapshot_date": "2026-04-09T00:00:00+00:00"}

        await consumer.process_message(key=None, value=payload, headers={})

        oi: PredictionMarketOI = uow.prediction_market_oi.upsert.call_args[0][0]
        assert oi.snapshot_date == date(2026, 4, 9)

    @pytest.mark.asyncio
    async def test_commit_not_called_in_process_message(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.commit.assert_not_called()


class TestProcessMessageIdempotent:
    @pytest.mark.asyncio
    async def test_replay_duplicate_skipped(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(side_effect=[True, False])
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})
        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        assert uow.prediction_market_oi.upsert.call_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_event_skips_all_writes(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_oi.upsert.assert_not_called()


class TestProcessMessageMalformed:
    @pytest.mark.asyncio
    async def test_missing_market_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="market_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "market_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_invalid_snapshot_date_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="snapshot_date"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "snapshot_date": "not-a-date"}, headers={})
