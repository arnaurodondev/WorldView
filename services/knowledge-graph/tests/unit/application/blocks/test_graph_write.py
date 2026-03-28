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


class _MockProducer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None:
        self.calls.append({"topic": topic, "key": key, "value": value})


def _raw_relation(
    *,
    raw_type: str = "employs",
    entity_provisional: bool = False,
) -> object:
    from knowledge_graph.application.blocks.graph_write import RawRelation

    return RawRelation(
        subject_entity_id=uuid4(),
        object_entity_id=uuid4(),
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

        summary = asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        assert summary.relations_upserted == 0
        assert summary.evidence_rows_inserted == 0

    def test_relation_with_canonical_type_calls_upsert(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        relation_repo.upsert.assert_called_once()

    def test_relation_with_none_canonical_type_skips_upsert(self) -> None:
        """Unknown relation types (proposed) must NOT upsert to relations table."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        relation_repo.upsert.assert_not_called()

    def test_evidence_always_inserted_even_for_proposed_type(self) -> None:
        """Evidence staging happens regardless of canonicalization outcome."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        evidence_repo = _make_evidence_repo()
        rel = _raw_relation()
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
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
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        # Verify insert_raw was called with no partition_key kwarg
        kwargs = evidence_repo.insert_raw.call_args.kwargs
        assert "partition_key" not in kwargs


# ---------------------------------------------------------------------------
# entity.dirtied.v1 direct produce
# ---------------------------------------------------------------------------


class TestEntityDirtiedDirectProduce:
    def test_entity_dirtied_produced_not_via_outbox(self) -> None:
        """entity.dirtied.v1 must use direct_producer, NOT outbox.append."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        producer = _MockProducer()
        outbox = _make_outbox_repo()
        rel = _raw_relation()
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=outbox,
                direct_producer=producer,
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        # Direct producer was called
        assert len(producer.calls) >= 1
        topics = {c["topic"] for c in producer.calls}
        assert "entity.dirtied.v1" in topics
        # Outbox was NOT called with entity.dirtied topic
        outbox_topics = {
            call.kwargs.get("topic") or call.args[0] if call.args else "" for call in outbox.append.call_args_list
        }
        assert "entity.dirtied.v1" not in outbox_topics

    def test_entity_dirtied_key_is_entity_id(self) -> None:
        """entity.dirtied.v1 Kafka key must be the entity_id bytes."""
        from knowledge_graph.application.blocks.graph_write import RawRelation, materialize_graph

        producer = _MockProducer()
        subject_id = uuid4()
        rel = RawRelation(
            subject_entity_id=subject_id,
            object_entity_id=uuid4(),
            raw_type="employs",
            extraction_confidence=0.8,
            evidence_date=_NOW,
        )
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],
                canonical_types=["employs"],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=producer,
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        dirty_calls = [c for c in producer.calls if c["topic"] == "entity.dirtied.v1"]
        assert len(dirty_calls) >= 1
        # Key must decode to a valid UUID matching one of the entities
        keys = {c["key"].decode() for c in dirty_calls}
        assert str(subject_id) in keys

    def test_graph_state_changed_emitted_via_outbox(self) -> None:
        """graph.state.changed.v1 must use outbox.append."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        outbox = _make_outbox_repo()
        rel = _raw_relation()
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=outbox,
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
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
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                events=[event],
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
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
        asyncio.get_event_loop().run_until_complete(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                events=[],
                claims=[claim],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                direct_producer=_MockProducer(),
                entity_dirtied_topic="entity.dirtied.v1",
            )
        )
        # session.execute should have been called for INSERT claims
        assert session.execute.call_count >= 1
        sqls = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("claims" in s.lower() for s in sqls)
