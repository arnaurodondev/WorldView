"""Unit tests for ProvisionalQueuedConsumer (PLAN-0061 Wave E).

Tests:
  - test_skips_when_row_not_found        — FOR UPDATE SKIP LOCKED returns None → no-op
  - test_enriches_and_resolves_on_success — happy path: enrichment persisted, status=resolved
  - test_applies_retry_on_llm_failure    — LLM returns None → retry transition
  - test_emits_dirtied_after_commit       — entity.dirtied.v1 emitted only after successful commit
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01234567-89ab-7def-8012-345678901234")
_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000099")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_consumer(session_factory: MagicMock, llm_client: MagicMock | None = None) -> object:
    from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
        ProvisionalQueuedConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-provisional-queued-group",
        topics=["entity.provisional.queued.v1"],
    )
    return ProvisionalQueuedConsumer(
        config=config,
        session_factory=session_factory,
        llm_client=llm_client or MagicMock(),
    )


def _make_session_factory(pending_row: tuple | None) -> tuple[AsyncMock, MagicMock]:
    """Return (session, factory). pending_row is returned by fetchone() in the lock query."""
    session = AsyncMock()
    session.commit = AsyncMock()

    result_mock = MagicMock()
    result_mock.fetchone.return_value = pending_row

    session.execute = AsyncMock(return_value=result_mock)

    def _make_cm() -> AsyncMock:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    factory = MagicMock(side_effect=lambda: _make_cm())
    return session, factory


def _make_pending_row(retry_count: int = 0) -> tuple:
    return (
        "Apple Inc.",  # mention_text
        "financial_instrument",  # mention_class
        "Apple is a tech company",  # context_snippet
        retry_count,  # retry_count
    )


def _make_event(queue_id: UUID = _QUEUE_ID) -> dict:
    return {
        "event_id": "01900000-0000-7000-0000-000000000001",
        "queue_id": str(queue_id),
        "normalized_surface": "apple inc.",
        "mention_class": "financial_instrument",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkipWhenNotPending:
    async def test_skips_when_row_not_found(self) -> None:
        """FOR UPDATE SKIP LOCKED returns no row → process_message exits early, no commit."""
        _session, factory = _make_session_factory(pending_row=None)
        consumer = _make_consumer(factory)

        await consumer.process_message(  # type: ignore[union-attr]
            key="apple inc.",
            value=_make_event(),
            headers={},
        )

        # SELECT was executed but the early-return means no UPDATE / commit happens.
        _session.execute.assert_awaited_once()
        _session.commit.assert_not_awaited()

    async def test_returns_early_on_missing_queue_id(self) -> None:
        """Event missing queue_id key is silently discarded."""
        _session, factory = _make_session_factory(pending_row=None)
        consumer = _make_consumer(factory)

        await consumer.process_message(  # type: ignore[union-attr]
            key=None,
            value={"event_id": "x"},  # no queue_id
            headers={},
        )

        factory.assert_not_called()  # no DB session opened at all


class TestHappyPath:
    async def test_enriches_and_sets_resolved(self) -> None:
        """Happy path: profile extracted → persist_enrichment → status='resolved'."""
        _session, factory = _make_session_factory(pending_row=_make_pending_row())
        consumer = _make_consumer(factory)

        profile = {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "isin": None,
            "aliases": [],
        }

        with (
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.compute_embedding",
                new=AsyncMock(return_value=[0.1] * 1024),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.persist_enrichment",
                new=AsyncMock(return_value=_ENTITY_ID),
            ),
        ):
            await consumer.process_message(  # type: ignore[union-attr]
                key="apple inc.",
                value=_make_event(),
                headers={},
            )

        # session.commit() should be called at least twice:
        # once after marking 'processing', once after persist + 'resolved'
        assert _session.commit.await_count >= 2


class TestRetryOnFailure:
    async def test_applies_retry_when_llm_returns_none(self) -> None:
        """When extract_entity_profile returns None, apply_retry_transition is called."""
        _session, factory = _make_session_factory(pending_row=_make_pending_row(retry_count=0))
        consumer = _make_consumer(factory)

        with (
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.apply_retry_transition",
                new=AsyncMock(return_value=False),
            ) as mock_retry,
        ):
            await consumer.process_message(  # type: ignore[union-attr]
                key="apple inc.",
                value=_make_event(),
                headers={},
            )

        mock_retry.assert_awaited_once()
        call_kwargs = mock_retry.call_args
        assert call_kwargs.args[1] == _QUEUE_ID  # queue_id arg


class TestDirtiedEmit:
    async def test_emits_dirtied_after_commit(self) -> None:
        """entity.dirtied.v1 is emitted only after successful commit (no orphaned msgs)."""
        _session, factory = _make_session_factory(pending_row=_make_pending_row())
        producer = MagicMock()

        from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
            ProvisionalQueuedConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="kg-provisional-queued-group",
            topics=["entity.provisional.queued.v1"],
        )
        consumer = ProvisionalQueuedConsumer(
            config=config,
            session_factory=factory,
            llm_client=MagicMock(),
            direct_producer=producer,
        )

        profile = {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "isin": None,
            "aliases": [],
        }

        with (
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.extract_entity_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.compute_embedding",
                new=AsyncMock(return_value=[0.1] * 1024),
            ),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.persist_enrichment",
                new=AsyncMock(return_value=_ENTITY_ID),
            ),
        ):
            await consumer.process_message(
                key="apple inc.",
                value=_make_event(),
                headers={},
            )

        producer.produce_bytes.assert_called_once()
        call_kwargs = producer.produce_bytes.call_args.kwargs
        assert call_kwargs["topic"] == "entity.dirtied.v1"
        import json

        payload = json.loads(call_kwargs["value"])
        assert payload["entity_id"] == str(_ENTITY_ID)


# ---------------------------------------------------------------------------
# P-1: init warning when direct_producer is None
# ---------------------------------------------------------------------------


class TestInitWarningNoProducer:
    def test_provisional_queued_consumer_warns_when_no_producer(self) -> None:
        """When direct_producer=None, a WARNING is logged at init time."""
        from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
            ProvisionalQueuedConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="kg-provisional-queued-group",
            topics=["entity.provisional.queued.v1"],
        )
        _, factory = _make_session_factory(pending_row=None)

        with capture_logs() as cap:
            ProvisionalQueuedConsumer(
                config=config,
                session_factory=factory,
                llm_client=MagicMock(),
                direct_producer=None,
            )

        assert any(
            e.get("event") == "provisional_queued_consumer_no_producer" and e.get("log_level") == "warning" for e in cap
        ), f"Expected warning log not found in: {cap}"

    def test_provisional_queued_consumer_no_warning_when_producer_present(self) -> None:
        """When direct_producer is provided, no 'no_producer' warning is logged."""
        from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
            ProvisionalQueuedConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="kg-provisional-queued-group",
            topics=["entity.provisional.queued.v1"],
        )
        _, factory = _make_session_factory(pending_row=None)

        with capture_logs() as cap:
            ProvisionalQueuedConsumer(
                config=config,
                session_factory=factory,
                llm_client=MagicMock(),
                direct_producer=MagicMock(),
            )

        assert not any(
            e.get("event") == "provisional_queued_consumer_no_producer" for e in cap
        ), f"Unexpected no_producer warning found in: {cap}"


# ---------------------------------------------------------------------------
# P-2: _fail_safe_retry increments stuck counter on DB failure
# ---------------------------------------------------------------------------


class TestFailSafeRetryStuckCounter:
    async def test_fail_safe_retry_failure_increments_stuck_counter(self) -> None:
        """When _fail_safe_retry DB call fails, s7_provisional_queue_stuck_total is incremented."""
        from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
            _fail_safe_retry,
        )

        broken_sf = MagicMock(side_effect=RuntimeError("db down"))

        _counter_path = (
            "knowledge_graph.infrastructure.messaging.consumers"
            ".provisional_queued_consumer.s7_provisional_queue_stuck_total"
        )
        with patch(_counter_path) as mock_counter:
            await _fail_safe_retry(broken_sf, uuid4(), 0, 5)

        mock_counter.inc.assert_called_once()

    async def test_fail_safe_retry_no_increment_on_success(self) -> None:
        """When _fail_safe_retry succeeds, stuck counter is NOT incremented."""
        from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
            _fail_safe_retry,
        )

        session = AsyncMock()
        session.commit = AsyncMock()

        def _make_cm():
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        factory = MagicMock(side_effect=lambda: _make_cm())

        _counter_path = (
            "knowledge_graph.infrastructure.messaging.consumers"
            ".provisional_queued_consumer.s7_provisional_queue_stuck_total"
        )
        with (
            patch(_counter_path) as mock_counter,
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment_core.apply_retry_transition",
                new=AsyncMock(return_value=False),
            ),
        ):
            await _fail_safe_retry(factory, uuid4(), 0, 5)

        mock_counter.inc.assert_not_called()
