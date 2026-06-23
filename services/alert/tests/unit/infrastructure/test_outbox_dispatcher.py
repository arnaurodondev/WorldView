"""Unit tests for AlertOutboxDispatcher.

Covers the two CRITICAL outbox bugs from the 2026-06-22 backend-e2e audit:

* BUG-A1 — delivery confirmation: an event is marked ``dispatched`` ONLY after
  the broker confirms delivery (the ``on_delivery`` callback fired with no error
  AND ``flush()`` drained the queue). A NACKed / flush-timed-out event must be
  treated as a failure, not silently lost.
* BUG-A2 — bounded retry + dead-letter: a failed event stays retryable (it is
  re-fetched once its back-off elapses) up to ``dispatcher_max_attempts``, after
  which it is moved to the dead-letter queue — never stranded in ``failed``.

The success-path helpers fire the ``on_delivery`` callback with ``err=None``,
because that is what a real confluent-kafka ``flush()`` does on a confirmed
delivery. The old tests passed ``flush=MagicMock(return_value=0)`` with no
callback, which is precisely the gap BUG-A1 describes.
"""

from __future__ import annotations

from typing import Any
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
        retry_count=int(kwargs.get("retry_count", 0)),  # type: ignore[arg-type]
    )


def _make_settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.kafka_bootstrap_servers = "localhost:9092"
    settings.dispatcher_poll_interval_s = 0.0
    settings.dispatcher_batch_size = 50
    # Concrete values so the dispatcher's arithmetic (retry_count + 1 >= max)
    # works against real ints, not MagicMock proxies.
    settings.dispatcher_max_attempts = 5
    settings.dispatcher_retry_backoff_base_s = 2.0
    settings.dispatcher_retry_backoff_max_s = 60.0
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_dispatcher(
    **settings_overrides: object,
) -> tuple[AlertOutboxDispatcher, MagicMock, MagicMock]:
    settings = _make_settings(**settings_overrides)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value = mock_session

    dispatcher = AlertOutboxDispatcher(settings=settings, session_factory=mock_sf)
    dispatcher._stop_event.set()  # Stop after one iteration in run()

    return dispatcher, mock_session, mock_sf


def _make_acking_producer() -> MagicMock:
    """Producer whose flush() fires the on_delivery callback with err=None.

    This simulates a CONFIRMED broker delivery — the only condition under which
    an event may be marked ``dispatched`` (BUG-A1).
    """
    mock_producer = MagicMock()
    captured: dict[str, Any] = {}

    def _produce(*, on_delivery: Any, **_kwargs: Any) -> None:
        captured["cb"] = on_delivery

    def _flush(timeout: float = 10) -> int:
        cb = captured.get("cb")
        if cb is not None:
            cb(None, MagicMock())  # err=None → delivery confirmed
        return 0  # queue drained

    mock_producer.produce = MagicMock(side_effect=_produce)
    mock_producer.flush = MagicMock(side_effect=_flush)
    return mock_producer


def _make_nacking_producer() -> MagicMock:
    """Producer whose flush() fires on_delivery with a broker error (NACK).

    confluent-kafka does NOT raise on a NACK — it reports the error via the
    delivery callback. flush() still returns 0 (the message left the queue),
    which is exactly why the old ``flush()`` return-only check was unsafe.
    """
    mock_producer = MagicMock()
    captured: dict[str, Any] = {}

    def _produce(*, on_delivery: Any, **_kwargs: Any) -> None:
        captured["cb"] = on_delivery

    def _flush(timeout: float = 10) -> int:
        cb = captured.get("cb")
        if cb is not None:
            cb("NACK: NotEnoughReplicas", MagicMock())  # truthy err → failure
        return 0

    mock_producer.produce = MagicMock(side_effect=_produce)
    mock_producer.flush = MagicMock(side_effect=_flush)
    return mock_producer


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

        mock_producer = _make_acking_producer()

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.mark_dispatched.assert_awaited_once_with(event.event_id)
        MockRepo.return_value.increment_attempts.assert_not_called()
        MockRepo.return_value.move_to_dead_letter.assert_not_called()

    @pytest.mark.unit
    async def test_delivery_nack_is_not_marked_dispatched(self) -> None:
        """BUG-A1: a broker NACK (callback err) must NOT mark the row dispatched.

        flush() returns 0 (message left the queue) but the delivery callback
        reported an error — the previous code marked this ``dispatched`` and the
        event was lost.
        """
        event = _make_outbox_event()
        dispatcher, _, _ = _make_dispatcher()

        mock_producer = _make_nacking_producer()

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.mark_dispatched.assert_not_called()
        MockRepo.return_value.increment_attempts.assert_awaited_once_with(event.event_id)

    @pytest.mark.unit
    async def test_flush_timeout_undelivered_is_not_marked_dispatched(self) -> None:
        """BUG-A1: flush() leaving messages queued (return > 0) is a failure.

        No callback fires and flush() returns a non-zero count → delivery was
        never confirmed, so the row must be retried, not marked dispatched.
        """
        event = _make_outbox_event()
        dispatcher, _, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock()
        mock_producer.flush = MagicMock(return_value=1)  # 1 message still queued
        dispatcher._producer = mock_producer

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.mark_dispatched.assert_not_called()
        MockRepo.return_value.increment_attempts.assert_awaited_once_with(event.event_id)
        # A flush timeout is the wedged-producer signature → producer reset.
        assert dispatcher._producer is None

    @pytest.mark.unit
    async def test_dispatch_failure_increments_attempts(self) -> None:
        """BUG-A2: a non-terminal failure records an attempt and stays retryable."""
        event = _make_outbox_event(retry_count=0)
        dispatcher, _, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock(side_effect=RuntimeError("broker down"))

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.increment_attempts.assert_awaited_once_with(event.event_id)
        MockRepo.return_value.move_to_dead_letter.assert_not_called()
        MockRepo.return_value.mark_dispatched.assert_not_called()

    @pytest.mark.unit
    async def test_exhausted_attempts_dead_letters(self) -> None:
        """BUG-A2: the final attempt (retry_count+1 >= max) dead-letters the row."""
        # max_attempts=5; retry_count already 4 → this attempt is the 5th.
        event = _make_outbox_event(retry_count=4)
        dispatcher, _, _ = _make_dispatcher(dispatcher_max_attempts=5)

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock(side_effect=RuntimeError("broker down"))

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        MockRepo.return_value.move_to_dead_letter.assert_awaited_once()
        # Called with the event + an error_detail string.
        call = MockRepo.return_value.move_to_dead_letter.await_args
        assert call.args[0] is event
        assert "error_detail" in call.kwargs
        MockRepo.return_value.increment_attempts.assert_not_called()
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

        mock_producer = _make_acking_producer()

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()

            await dispatcher._dispatch_batch()

        # produce() is keyword-only now (on_delivery added); assert the routing.
        _args, kwargs = mock_producer.produce.call_args
        assert kwargs["topic"] == "alert.delivered.v1"
        assert kwargs["key"] == partition_key.encode()
        assert kwargs["value"] == b"\x04\x05"
        assert callable(kwargs["on_delivery"])

    @pytest.mark.unit
    async def test_broken_producer_error_resets_producer(self) -> None:
        """GAP-A / BP-711: a delivery TimeoutError discards the wedged producer.

        Without the reset, the cached producer stays wedged forever and every
        subsequent dispatch times out → permanent outbox wedge.
        """
        event = _make_outbox_event()
        dispatcher, _, _ = _make_dispatcher()

        # flush() raises TimeoutError → signature of a wedged producer.
        mock_producer = MagicMock()
        mock_producer.produce = MagicMock()
        mock_producer.flush = MagicMock(side_effect=TimeoutError())
        dispatcher._producer = mock_producer

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        # Producer cache cleared so next dispatch rebuilds + reconnects.
        assert dispatcher._producer is None
        # Stays retryable (not dead-lettered on first failure).
        MockRepo.return_value.increment_attempts.assert_awaited_once_with(event.event_id)

    @pytest.mark.unit
    async def test_non_broken_error_keeps_producer(self) -> None:
        """A non-timeout failure must NOT discard the cached producer."""
        event = _make_outbox_event()
        dispatcher, _, _ = _make_dispatcher()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock(side_effect=RuntimeError("broker down"))
        dispatcher._producer = mock_producer

        with (
            patch("alert.infrastructure.messaging.outbox.dispatcher.OutboxRepository") as MockRepo,
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            MockRepo.return_value.fetch_pending = AsyncMock(return_value=[event])
            MockRepo.return_value.mark_dispatched = AsyncMock()
            MockRepo.return_value.increment_attempts = AsyncMock()
            MockRepo.return_value.move_to_dead_letter = AsyncMock()

            await dispatcher._dispatch_batch()

        assert dispatcher._producer is mock_producer

    @pytest.mark.unit
    def test_stop_sets_stop_event(self) -> None:
        dispatcher, _, _ = _make_dispatcher()
        dispatcher._stop_event.clear()  # reset
        dispatcher.stop()
        assert dispatcher._stop_event.is_set()
