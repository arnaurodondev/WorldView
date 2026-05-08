"""Unit tests for AlertOutboxDispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from alert.domain.entities import OutboxEvent
from alert.domain.enums import OutboxStatus
from alert.infrastructure.messaging.outbox.dispatcher import AlertOutboxDispatcher

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _make_outbox_event(**kwargs: object) -> OutboxEvent:
    return OutboxEvent(
        event_id=kwargs.get("event_id", uuid4()),  # type: ignore[arg-type]
        topic=str(kwargs.get("topic", "alert.delivered.v1")),
        partition_key=str(kwargs.get("partition_key", str(uuid4()))),
        payload_avro=bytes(kwargs.get("payload_avro", b"\x01\x02")),  # type: ignore[arg-type]
        status=OutboxStatus.PENDING,
        created_at=utc_now(),
    )


def _make_settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.kafka_bootstrap_servers = "localhost:9092"
    settings.dispatcher_poll_interval_s = 0.0
    settings.dispatcher_batch_size = 50
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_dispatcher(
    pending_events: list[OutboxEvent] | None = None,
) -> tuple[AlertOutboxDispatcher, MagicMock, AsyncMock]:
    settings = _make_settings()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value = mock_session

    dispatcher = AlertOutboxDispatcher(settings=settings, session_factory=mock_sf)
    dispatcher._stop_event.set()  # Stop after one iteration in run()

    return dispatcher, mock_session, mock_sf


class TestAlertOutboxDispatcher:
    @pytest.mark.unit
    async def test_empty_batch_does_not_produce(self) -> None:
        dispatcher, _mock_session, _ = _make_dispatcher()

        with patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo:
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[])

            await dispatcher._dispatch_batch()

        # No produce calls when batch is empty
        assert dispatcher._producer is None

    @pytest.mark.unit
    async def test_dispatch_success_marks_dispatched(self) -> None:
        event = _make_outbox_event()
        dispatcher, _mock_session, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock()
        mock_producer.flush = MagicMock(return_value=0)

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.mark_failed = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.mark_dispatched.assert_awaited_once_with(event.event_id)
        MockRepo.return_value.mark_failed.assert_not_called()

    @pytest.mark.unit
    async def test_dispatch_failure_marks_failed(self) -> None:
        event = _make_outbox_event()
        dispatcher, _mock_session, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock(side_effect=RuntimeError("broker down"))

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.mark_failed = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.mark_failed.assert_awaited_once_with(event.event_id)
        MockRepo.return_value.mark_dispatched.assert_not_called()

    @pytest.mark.unit
    async def test_produces_correct_topic_and_key(self) -> None:
        partition_key = str(uuid4())
        event = _make_outbox_event(
            topic="alert.delivered.v1",
            partition_key=partition_key,
            payload_avro=b"\x04\x05",
        )
        dispatcher, _, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock()
        mock_producer.flush = MagicMock(return_value=0)

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()

            await dispatcher._dispatch_batch()

        mock_producer.produce.assert_called_once_with(
            topic="alert.delivered.v1",
            key=partition_key.encode(),
            value=b"\x04\x05",
        )

    @pytest.mark.unit
    def test_stop_sets_stop_event(self) -> None:
        dispatcher, _, _ = _make_dispatcher()
        dispatcher._stop_event.clear()  # reset
        dispatcher.stop()
        assert dispatcher._stop_event.is_set()
