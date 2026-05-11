"""Unit tests for OutboxDispatcher (T-D-3-08)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(events: list) -> tuple:
    """Return (session_factory, outbox_repo_mock)."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    outbox_repo = AsyncMock()
    outbox_repo.fetch_pending = AsyncMock(return_value=events)
    outbox_repo.mark_dispatched = AsyncMock()
    outbox_repo.mark_failed = AsyncMock()

    return sf, session, outbox_repo


def _make_event(topic: str) -> dict:
    return {
        "event_id": uuid4(),
        "topic": topic,
        "payload_avro": b"\x00" * 8,
        "partition_key": "pk-1",
    }


class TestOutboxDispatcherAllowedTopics:
    def test_allowed_topic_produces_and_marks_dispatched(self) -> None:
        """graph.state.changed.v1 -> producer.produce() called, mark_dispatched called."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("graph.state.changed.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock(return_value=0)

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer, poll_interval_s=0.0)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 1
        producer.produce.assert_called_once()
        outbox_repo.mark_dispatched.assert_awaited_once()
        outbox_repo.mark_failed.assert_not_awaited()

    def test_contradiction_topic_dispatched(self) -> None:
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("intelligence.contradiction.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock(return_value=0)

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 1
        producer.produce.assert_called_once()

    def test_relation_proposed_topic_dispatched(self) -> None:
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("relation.type.proposed.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock(return_value=0)

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 1

    def test_entity_canonical_created_topic_dispatched(self) -> None:
        """entity.canonical.created.v1 is an allowed topic (ProvisionalEnrichmentWorker)."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("entity.canonical.created.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock(return_value=0)

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 1
        producer.produce.assert_called_once()
        outbox_repo.mark_dispatched.assert_awaited_once()
        outbox_repo.mark_failed.assert_not_awaited()


class TestOutboxDispatcherEntityDirtied:
    def test_entity_dirtied_logs_warning_and_marks_dispatched(self) -> None:
        """entity.dirtied.v1 found in outbox -> WARNING logged, mark_dispatched (not produce)."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("entity.dirtied.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        # Not counted as successfully dispatched
        assert dispatched == 0
        # Producer never called
        producer.produce.assert_not_called()
        # Row is removed from queue (mark_dispatched), not left hanging
        outbox_repo.mark_dispatched.assert_awaited_once()
        outbox_repo.mark_failed.assert_not_awaited()


class TestOutboxDispatcherUnknownTopic:
    def test_unknown_topic_marks_failed(self) -> None:
        """Unknown topic -> mark_failed called, producer never called."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("completely.unknown.v9")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock()

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 0
        producer.produce.assert_not_called()
        outbox_repo.mark_failed.assert_awaited_once()

    def test_producer_error_marks_failed(self) -> None:
        """If producer.produce raises -> mark_failed called."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        event = _make_event("graph.state.changed.v1")
        sf, _session, outbox_repo = _make_session_factory([event])

        producer = MagicMock()
        producer.produce = MagicMock(side_effect=RuntimeError("broker down"))

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 0
        outbox_repo.mark_failed.assert_awaited_once()
        outbox_repo.mark_dispatched.assert_not_awaited()

    def test_empty_queue_returns_zero(self) -> None:
        """Empty outbox -> zero dispatched, no produce calls."""
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher import OutboxDispatcher

        sf, _session, outbox_repo = _make_session_factory([])
        producer = MagicMock()

        with patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxRepository",
            return_value=outbox_repo,
        ):
            dispatcher = OutboxDispatcher(sf, producer)
            dispatched = asyncio.run(dispatcher._dispatch_batch())

        assert dispatched == 0
        producer.produce.assert_not_called()
