"""Unit tests for NLPPipelineOutboxDispatcher.

Critical invariants tested:
  - Empty batch → no Kafka produce call, return 0.
  - Successful dispatch → mark_dispatched called, return 1.
  - Failed delivery → mark_failed called (not mark_dispatched).
  - DLQ threshold: after MAX_DISPATCH_ATTEMPTS failures, move_to_dlq called.
  - stop() signals the run loop to exit.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.outbox.dispatcher import (
    _MAX_DISPATCH_ATTEMPTS,
    NLPPipelineOutboxDispatcher,
)

pytestmark = pytest.mark.unit


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.kafka_bootstrap_servers = "localhost:9092"
    s.dispatcher_batch_size = 10
    s.dispatcher_poll_interval_secs = 0.01
    return s


def _make_record(
    event_id: uuid.UUID | None = None,
    topic: str = "nlp.article.enriched.v1",
    retry_count: int = 0,
) -> MagicMock:
    r = MagicMock()
    r.event_id = event_id or uuid.uuid4()
    r.topic = topic
    r.partition_key = str(uuid.uuid4())
    r.payload_avro = b'{"doc_id": "abc"}'
    r.retry_count = retry_count
    return r


def _make_dispatcher() -> tuple[NLPPipelineOutboxDispatcher, MagicMock, MagicMock]:
    """Returns (dispatcher, outbox_repo_mock, dlq_repo_mock)."""
    settings = _make_settings()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    session_factory = MagicMock(return_value=mock_session)

    outbox_repo = AsyncMock()
    dlq_repo = AsyncMock()

    dispatcher = NLPPipelineOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
    )
    return dispatcher, outbox_repo, dlq_repo


@pytest.mark.unit
class TestDispatcherEmptyBatch:
    @pytest.mark.asyncio
    async def test_empty_batch_returns_zero(self) -> None:
        """No records in DB → dispatch returns 0 without calling produce."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        outbox_repo.claim_batch = AsyncMock(return_value=[])

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
        ):
            count = await dispatcher._dispatch_batch()

        assert count == 0
        outbox_repo.mark_dispatched.assert_not_called()
        outbox_repo.mark_failed.assert_not_called()


@pytest.mark.unit
class TestDispatcherSuccessfulDelivery:
    @pytest.mark.asyncio
    async def test_successful_delivery_marks_dispatched(self) -> None:
        """When Kafka delivery succeeds, mark_dispatched is called and count=1."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        record = _make_record()
        outbox_repo.claim_batch = AsyncMock(return_value=[record])
        outbox_repo.mark_dispatched = AsyncMock()
        outbox_repo.mark_failed = AsyncMock(return_value=1)

        # Simulate a successful produce: on_delivery callback called with err=None
        def fake_produce(topic: str, key: Any, value: Any, on_delivery: Any) -> None:
            on_delivery(None, MagicMock())

        mock_producer = MagicMock()
        mock_producer.produce.side_effect = fake_produce
        mock_producer.flush = MagicMock(return_value=0)

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            # run_in_executor calls blocking functions — patch the loop to call them directly
            loop = asyncio.get_event_loop()
            original_run_in_executor = loop.run_in_executor

            async def immediate_executor(executor: Any, fn: Any, *args: Any) -> Any:
                return fn()

            loop.run_in_executor = immediate_executor  # type: ignore[method-assign]
            try:
                count = await dispatcher._dispatch_batch()
            finally:
                loop.run_in_executor = original_run_in_executor  # type: ignore[method-assign]

        assert count == 1
        outbox_repo.mark_dispatched.assert_called_once_with(record.event_id)
        outbox_repo.mark_failed.assert_not_called()
        dlq_repo.move_to_dlq.assert_not_called()


@pytest.mark.unit
class TestDispatcherFailedDelivery:
    @pytest.mark.asyncio
    async def test_failed_delivery_marks_failed(self) -> None:
        """When Kafka delivery fails (below threshold), mark_failed called, no DLQ."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        record = _make_record(retry_count=0)
        outbox_repo.claim_batch = AsyncMock(return_value=[record])
        outbox_repo.mark_dispatched = AsyncMock()
        outbox_repo.mark_failed = AsyncMock(return_value=1)
        dlq_repo.move_to_dlq = AsyncMock()

        # Simulate a failed produce: on_delivery callback called with err != None
        def fake_produce(topic: str, key: Any, value: Any, on_delivery: Any) -> None:
            on_delivery(MagicMock(), None)  # err is truthy

        mock_producer = MagicMock()
        mock_producer.produce.side_effect = fake_produce
        mock_producer.flush = MagicMock(return_value=0)

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            loop = asyncio.get_event_loop()
            original = loop.run_in_executor

            async def immediate_executor(executor: Any, fn: Any, *args: Any) -> Any:
                return fn()

            loop.run_in_executor = immediate_executor  # type: ignore[method-assign]
            try:
                count = await dispatcher._dispatch_batch()
            finally:
                loop.run_in_executor = original  # type: ignore[method-assign]

        assert count == 0
        outbox_repo.mark_failed.assert_called_once_with(record.event_id)
        outbox_repo.mark_dispatched.assert_not_called()
        # retry_count=0, threshold=5 → should NOT dead-letter
        dlq_repo.move_to_dlq.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_attempts_triggers_dlq(self) -> None:
        """When retry_count+1 >= MAX_DISPATCH_ATTEMPTS, move_to_dlq is called."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        # retry_count = MAX - 1 so next failure hits the threshold
        record = _make_record(retry_count=_MAX_DISPATCH_ATTEMPTS - 1)
        outbox_repo.claim_batch = AsyncMock(return_value=[record])
        outbox_repo.mark_dispatched = AsyncMock()
        # BUG-3: the DLQ decision now uses mark_failed's authoritative return; at the
        # cap it returns MAX_DISPATCH_ATTEMPTS → triggers move_to_dlq.
        outbox_repo.mark_failed = AsyncMock(return_value=_MAX_DISPATCH_ATTEMPTS)
        dlq_repo.move_to_dlq = AsyncMock()

        def fake_produce(topic: str, key: Any, value: Any, on_delivery: Any) -> None:
            on_delivery(MagicMock(), None)  # failure

        mock_producer = MagicMock()
        mock_producer.produce.side_effect = fake_produce
        mock_producer.flush = MagicMock(return_value=0)

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            loop = asyncio.get_event_loop()
            original = loop.run_in_executor

            async def immediate_executor(executor: Any, fn: Any, *args: Any) -> Any:
                return fn()

            loop.run_in_executor = immediate_executor  # type: ignore[method-assign]
            try:
                await dispatcher._dispatch_batch()
            finally:
                loop.run_in_executor = original  # type: ignore[method-assign]

        dlq_repo.move_to_dlq.assert_called_once()
        call_kwargs = dlq_repo.move_to_dlq.call_args.kwargs
        assert call_kwargs["original_event_id"] == record.event_id
        assert call_kwargs["topic"] == record.topic


@pytest.mark.unit
class TestDispatcherBrokenProducerRecovery:
    """GAP-A: a wedged producer (produce/flush TimeoutError) must be discarded."""

    @pytest.mark.asyncio
    async def test_timeout_error_resets_producer(self) -> None:
        """A flush TimeoutError clears the cached producer so the next dispatch rebuilds."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        record = _make_record(retry_count=0)
        outbox_repo.claim_batch = AsyncMock(return_value=[record])
        outbox_repo.mark_dispatched = AsyncMock()
        outbox_repo.mark_failed = AsyncMock(return_value=1)
        dlq_repo.move_to_dlq = AsyncMock()

        # produce succeeds but flush() raises TimeoutError → wedged producer.
        mock_producer = MagicMock()
        mock_producer.produce = MagicMock()
        mock_producer.flush = MagicMock(side_effect=TimeoutError())
        dispatcher._producer = mock_producer

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            loop = asyncio.get_event_loop()
            original = loop.run_in_executor

            async def immediate_executor(executor: Any, fn: Any, *args: Any) -> Any:
                return fn()

            loop.run_in_executor = immediate_executor  # type: ignore[method-assign]
            try:
                count = await dispatcher._dispatch_batch()
            finally:
                loop.run_in_executor = original  # type: ignore[method-assign]

        assert count == 0
        # Wedged producer discarded; ``_get_producer`` will lazily rebuild next cycle.
        assert dispatcher._producer is None
        outbox_repo.mark_failed.assert_called_once_with(record.event_id)

    @pytest.mark.asyncio
    async def test_non_timeout_error_keeps_producer(self) -> None:
        """A non-timeout produce exception must NOT discard the cached producer."""
        dispatcher, outbox_repo, dlq_repo = _make_dispatcher()
        record = _make_record(retry_count=0)
        outbox_repo.claim_batch = AsyncMock(return_value=[record])
        outbox_repo.mark_failed = AsyncMock(return_value=1)
        dlq_repo.move_to_dlq = AsyncMock()

        mock_producer = MagicMock()
        mock_producer.produce = MagicMock(side_effect=ValueError("bad payload"))
        mock_producer.flush = MagicMock(return_value=0)
        dispatcher._producer = mock_producer

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
                return_value=outbox_repo,
            ),
            patch(
                "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.DLQRepository",
                return_value=dlq_repo,
            ),
            patch.object(dispatcher, "_get_producer", return_value=mock_producer),
        ):
            loop = asyncio.get_event_loop()
            original = loop.run_in_executor

            async def immediate_executor(executor: Any, fn: Any, *args: Any) -> Any:
                return fn()

            loop.run_in_executor = immediate_executor  # type: ignore[method-assign]
            try:
                await dispatcher._dispatch_batch()
            finally:
                loop.run_in_executor = original  # type: ignore[method-assign]

        assert dispatcher._producer is mock_producer


@pytest.mark.unit
class TestDispatcherLifecycle:
    def test_stop_sets_event(self) -> None:
        """stop() must signal the run loop to exit."""
        dispatcher = NLPPipelineOutboxDispatcher(
            settings=_make_settings(),
            session_factory=MagicMock(),
        )
        assert not dispatcher._stop_event.is_set()
        dispatcher.stop()
        assert dispatcher._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_run_exits_after_stop(self) -> None:
        """run() exits promptly once stop() has been called."""
        dispatcher = NLPPipelineOutboxDispatcher(
            settings=_make_settings(),
            session_factory=MagicMock(),
        )

        async def empty_batch() -> int:
            return 0

        with patch.object(dispatcher, "_dispatch_batch", side_effect=empty_batch):
            dispatcher.stop()  # pre-set the stop flag
            await asyncio.wait_for(dispatcher.run(), timeout=1.0)
        # If we get here without TimeoutError, the loop exited correctly
