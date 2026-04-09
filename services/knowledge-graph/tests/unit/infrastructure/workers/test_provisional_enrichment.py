"""Unit tests for ProvisionalEnrichmentWorker (Worker 13E).

Key invariant under test: entity.dirtied.v1 is produced AFTER session.commit(),
not before — so no orphaned Kafka messages if the transaction rolls back.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01234567-89ab-7def-8012-345678901234")
_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_with_rows(rows: list) -> tuple[AsyncMock, MagicMock]:
    """Return (session, session_factory) with pre-loaded pending-queue rows."""
    session = AsyncMock()
    session.commit = AsyncMock()

    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows

    session.execute = AsyncMock(return_value=result_mock)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session_cm

    return session, factory


def _make_producer() -> MagicMock:
    producer = MagicMock()
    producer.produce_bytes = MagicMock()
    return producer


def _make_pending_row() -> tuple:
    """Return a fake DB row matching the SELECT column order."""
    return (
        str(_QUEUE_ID),  # queue_id
        "Apple Inc.",  # mention_text
        "apple inc.",  # normalized_surface
        "financial_instrument",  # mention_class
        "Apple is a tech company",  # context_snippet
        None,  # source_doc_id
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisionalEnrichmentWorkerNoPendingRows:
    async def test_no_pending_rows_no_produce(self) -> None:
        """When no pending rows, producer.produce_bytes is never called."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)
        await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_no_pending_rows_still_commits(self) -> None:
        """run() always commits the session, even with no rows to process."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)
        await worker.run()

        session.commit.assert_called_once()


class TestProvisionalEnrichmentWorkerPostCommitOrdering:
    async def test_dirtied_produced_after_commit(self) -> None:
        """entity.dirtied.v1 is produced AFTER session.commit(), never before."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        commit_called_at: list[int] = []
        produce_called_at: list[int] = []
        call_counter: list[int] = [0]

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        original_commit = session.commit

        async def _tracked_commit():
            call_counter[0] += 1
            commit_called_at.append(call_counter[0])
            await original_commit()

        session.commit = _tracked_commit

        def _tracked_produce(**kwargs: object) -> None:
            call_counter[0] += 1
            produce_called_at.append(call_counter[0])

        producer.produce_bytes = _tracked_produce

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        # Patch _enrich_entity to return a UUID (success) without touching DB internals
        with patch.object(worker, "_enrich_entity", return_value=_ENTITY_ID):
            await worker.run()

        assert len(commit_called_at) == 1
        assert len(produce_called_at) == 1
        # Commit must have happened before produce
        assert commit_called_at[0] < produce_called_at[0], "entity.dirtied.v1 must be produced AFTER commit, not before"

    async def test_commit_failure_suppresses_produce(self) -> None:
        """When commit raises, producer.produce_bytes is never called."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()
        session.commit = AsyncMock(side_effect=RuntimeError("DB write failed"))

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with patch.object(worker, "_enrich_entity", return_value=_ENTITY_ID):
            with pytest.raises(RuntimeError, match="DB write failed"):
                await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_dirty_payload_contains_entity_id(self) -> None:
        """Produced entity.dirtied.v1 payload includes the entity_id."""
        import json

        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(
            factory, AsyncMock(), direct_producer=producer, entity_dirtied_topic="entity.dirtied.v1"
        )

        with patch.object(worker, "_enrich_entity", return_value=_ENTITY_ID):
            await worker.run()

        producer.produce_bytes.assert_called_once()
        kwargs = producer.produce_bytes.call_args.kwargs
        assert kwargs["topic"] == "entity.dirtied.v1"
        assert kwargs["key"] == str(_ENTITY_ID).encode()
        payload = json.loads(kwargs["value"])
        assert payload["entity_id"] == str(_ENTITY_ID)

    async def test_multiple_entities_all_produced_after_commit(self) -> None:
        """All dirty IDs accumulated before commit — then produced in batch after."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        entity_id_1 = UUID("01234567-89ab-7def-8012-aaaaaaaaaaaa")
        entity_id_2 = UUID("01234567-89ab-7def-8012-bbbbbbbbbbbb")
        rows = [_make_pending_row(), _make_pending_row()]

        session, factory = _make_session_with_rows(rows)
        producer = _make_producer()

        call_order: list[str] = []
        original_commit = session.commit

        async def _track_commit():
            call_order.append("commit")
            await original_commit()

        session.commit = _track_commit

        def _track_produce(**kwargs: object) -> None:
            call_order.append("produce")

        producer.produce_bytes = _track_produce

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        # Return different entity IDs for the two rows
        side_effects = [entity_id_1, entity_id_2]
        with patch.object(worker, "_enrich_entity", side_effect=side_effects):
            await worker.run()

        # commit appears before both produces
        commit_idx = call_order.index("commit")
        produce_indices = [i for i, v in enumerate(call_order) if v == "produce"]
        assert len(produce_indices) == 2
        assert all(commit_idx < idx for idx in produce_indices)


class TestProvisionalEnrichmentWorkerFailedEnrichment:
    async def test_llm_failure_skips_dirty_produce(self) -> None:
        """When _enrich_entity returns None (LLM failed), no dirty event is produced."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with patch.object(worker, "_enrich_entity", return_value=None):
            await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_enrichment_exception_skips_dirty_produce(self) -> None:
        """When _enrich_entity raises, the row is logged as failed, not dirtied."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with patch.object(worker, "_enrich_entity", side_effect=RuntimeError("LLM timeout")):
            # run() should NOT re-raise — it logs and continues
            await worker.run()

        producer.produce_bytes.assert_not_called()


class TestProvisionalEnrichmentWorkerNoProducer:
    async def test_none_producer_completes_without_error(self) -> None:
        """When direct_producer=None, run() completes without AttributeError."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=None)

        with patch.object(worker, "_enrich_entity", return_value=_ENTITY_ID):
            # Should not raise even though producer is None
            await worker.run()
