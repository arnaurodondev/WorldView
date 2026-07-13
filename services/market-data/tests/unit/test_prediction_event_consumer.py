"""Unit tests for PredictionEventConsumer (PLAN-0056 Wave A3, T-A-3-02)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionEvent
from market_data.infrastructure.messaging.consumers.prediction_event_consumer import (
    PredictionEventConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_START = datetime(2028, 1, 1, 0, 0, 0, tzinfo=UTC)
_END = datetime(2028, 11, 7, 0, 0, 0, tzinfo=UTC)

_VALID_EVENT: dict = {
    "event_id": "01900000-0000-7000-8000-0000000000b2",
    "event_type": "market.prediction.event",
    "schema_version": 1,
    "occurred_at": _START.isoformat(),
    "group_id": "grp_12345",
    "name": "2028 US Presidential Election",
    "category": "politics",
    "start_date": _START.isoformat(),
    "end_date": _END.isoformat(),
    "market_count": 7,
    "correlation_id": None,
}


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.ingestion_events = MagicMock()
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.prediction_events = MagicMock()
    uow.prediction_events.upsert = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.failed_tasks = MagicMock()
    uow.failed_tasks.create = AsyncMock()
    return uow


def _make_consumer(uow: MagicMock) -> PredictionEventConsumer:
    consumer = PredictionEventConsumer(
        uow_factory=lambda: uow,
        config=ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            topics=["market.prediction.event.v1"],
        ),
    )
    consumer._current_uow = uow
    return consumer


class TestProcessMessageUpsertEvent:
    @pytest.mark.asyncio
    async def test_upserts_event_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_events.upsert.assert_called_once()
        event: PredictionEvent = uow.prediction_events.upsert.call_args[0][0]
        assert isinstance(event, PredictionEvent)
        # group_id maps to the event_id business key.
        assert event.event_id == "grp_12345"
        assert event.name == "2028 US Presidential Election"
        assert event.category == "politics"
        assert event.start_date == _START
        assert event.end_date == _END
        assert event.market_count == 7

    @pytest.mark.asyncio
    async def test_null_dates_map_to_none(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        event_payload = {**_VALID_EVENT, "start_date": None, "end_date": None, "category": None}

        await consumer.process_message(key=None, value=event_payload, headers={})

        event: PredictionEvent = uow.prediction_events.upsert.call_args[0][0]
        assert event.start_date is None
        assert event.end_date is None
        assert event.category is None

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

        assert uow.prediction_events.upsert.call_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_event_skips_all_writes(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_events.upsert.assert_not_called()


class TestProcessMessageMalformed:
    @pytest.mark.asyncio
    async def test_missing_event_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="event_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "event_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_missing_group_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="group_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "group_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_invalid_start_date_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="start_date"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "start_date": "not-a-date"}, headers={})
