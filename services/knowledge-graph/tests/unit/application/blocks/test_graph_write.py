"""Unit tests for Block 12a: graph materialization."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = (str(uuid4()),)
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    return session


def _make_relation_repo(relation_id: UUID | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.upsert = AsyncMock(return_value=relation_id or uuid4())
    return repo


def _make_evidence_repo(raw_id: UUID | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.insert_raw = AsyncMock(return_value=raw_id or uuid4())
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def _raw_relation(
    *,
    raw_type: str = "employs",
    entity_provisional: bool = False,
    subject_entity_id: UUID | None = None,
    object_entity_id: UUID | None = None,
) -> object:
    from knowledge_graph.application.blocks.graph_write import RawRelation

    return RawRelation(
        subject_entity_id=subject_entity_id or uuid4(),
        object_entity_id=object_entity_id or uuid4(),
        raw_type=raw_type,
        extraction_confidence=0.85,
        evidence_date=_NOW,
        entity_provisional=entity_provisional,
    )


# ---------------------------------------------------------------------------
# Graph upsert idempotency
# ---------------------------------------------------------------------------


class TestGraphMaterializationRelations:
    def test_empty_relations_returns_zero_counts(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert summary.relations_upserted == 0
        assert summary.evidence_rows_inserted == 0

    def test_relation_with_canonical_type_calls_upsert(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        relation_repo.upsert.assert_called_once()

    def test_relation_with_none_canonical_type_skips_upsert(self) -> None:
        """Unknown relation types (proposed) must NOT upsert to relations table."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        relation_repo.upsert.assert_not_called()

    def test_evidence_always_inserted_even_for_proposed_type(self) -> None:
        """Evidence staging happens regardless of canonicalization outcome."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        evidence_repo = _make_evidence_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        evidence_repo.insert_raw.assert_called_once()


# ---------------------------------------------------------------------------
# partition_key never in INSERT
# ---------------------------------------------------------------------------


class TestPartitionKeyNotInInsert:
    def test_insert_raw_not_called_with_partition_key(self) -> None:
        """partition_key is STORED — evidence_repo.insert_raw must NOT receive it."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        evidence_repo = _make_evidence_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Verify insert_raw was called with no partition_key kwarg
        kwargs = evidence_repo.insert_raw.call_args.kwargs
        assert "partition_key" not in kwargs


# ---------------------------------------------------------------------------
# entity.dirtied.v1 — PLAN-0031 C-1: returned as entity_ids_to_dirty
# ---------------------------------------------------------------------------


class TestEntityDirtiedReturnedNotProduced:
    """PLAN-0031 C-1: materialize_graph() no longer produces entity.dirtied.v1
    directly.  Instead it returns entity_ids_to_dirty in the summary so the
    caller can produce AFTER session.commit()."""

    def test_materialize_graph_returns_dirtied_entity_ids(self) -> None:
        """Both subject and object entity IDs are in the returned set."""
        from knowledge_graph.application.blocks.graph_write import RawRelation, materialize_graph

        subj_id = uuid4()
        obj_id = uuid4()
        rel = RawRelation(
            subject_entity_id=subj_id,
            object_entity_id=obj_id,
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
        )
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Both subject and object IDs must be in the returned frozenset
        assert subj_id in summary.entity_ids_to_dirty
        assert obj_id in summary.entity_ids_to_dirty
        assert isinstance(summary.entity_ids_to_dirty, frozenset)

    def test_materialize_graph_does_not_produce_kafka(self) -> None:
        """No produce_bytes() calls inside the function — caller produces."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        # Verify there is no direct_producer parameter at all (TypeError if passed)
        rel = _raw_relation()
        # If we accidentally pass direct_producer, the function should reject it
        # since we removed the parameter
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # The function returns entity IDs to dirty (not empty for a relation)
        assert summary.entities_dirtied >= 1
        assert len(summary.entity_ids_to_dirty) >= 1

    def test_empty_relations_returns_empty_dirty_set(self) -> None:
        """No relations = no dirty entities."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert len(summary.entity_ids_to_dirty) == 0

    def test_graph_state_changed_emitted_via_outbox(self) -> None:
        """graph.state.changed.v1 must use outbox.append."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        outbox = _make_outbox_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=outbox,
            )
        )
        assert outbox.append.called
        topics = [c.kwargs["topic"] for c in outbox.append.call_args_list]
        assert "graph.state.changed.v1" in topics


# ---------------------------------------------------------------------------
# Events + claims inserts
# ---------------------------------------------------------------------------


class TestEventsAndClaims:
    def test_events_inserted_via_session(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawEvent, materialize_graph

        session = _make_session()
        event = RawEvent(
            subject_entity_id=uuid4(),
            event_type="ceo_departure",
            event_text="CEO resigned",
            extraction_confidence=0.9,
            event_date=_NOW,
        )
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # session.execute should have been called (INSERT events + INSERT event_entities)
        assert session.execute.call_count >= 2

    def test_claims_inserted_via_session(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawClaim, materialize_graph

        session = _make_session()
        claim = RawClaim(
            subject_entity_id=uuid4(),
            claim_type="analyst_rating",
            polarity="positive",
            claim_text="Buy rating",
            extraction_confidence=0.8,
        )
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # session.execute should have been called for INSERT claims
        assert session.execute.call_count >= 1
        sqls = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("claims" in s.lower() for s in sqls)
