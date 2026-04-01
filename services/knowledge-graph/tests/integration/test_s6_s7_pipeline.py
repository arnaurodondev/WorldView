"""S6→S7 pipeline continuity test.

Verifies that the graph materialization block (Block 12a) correctly:
  - Writes a relation row to intelligence_db.
  - Appends a graph.state.changed.v1 outbox entry.
  - Calls direct_producer.produce_bytes for entity.dirtied.v1.

The test does NOT require a live Kafka broker; it uses mock producers and
a real intelligence_db.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from knowledge_graph.application.blocks.graph_write import (
    RawRelation,
    materialize_graph,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import OutboxRepository
from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
    RelationEvidenceRepository,
)
from sqlalchemy import text


@pytest.mark.integration
async def test_s6_s7_pipeline_relation_written(session_factory) -> None:
    """materialize_graph writes a relation row and a graph.state.changed.v1 outbox entry."""

    # Setup: create canonical entities
    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("PipelineCorp", "organization")
        obj_id = await entity_repo.create("PipelineExchange", "exchange")
        await session.commit()

    doc_id = uuid.uuid4()
    evidence_date = datetime.now(tz=UTC)

    raw_relation = RawRelation(
        subject_entity_id=subject_id,
        object_entity_id=obj_id,
        raw_type="listed_on",
        polarity="positive",
        extraction_confidence=0.87,
        source_trust_weight=0.60,
        evidence_date=evidence_date,
        is_backfill=False,
    )

    # Mock direct producer (entity.dirtied.v1 — direct Kafka produce)
    mock_producer = MagicMock()
    mock_producer.produce_bytes = MagicMock()

    async with session_factory() as session:
        relation_repo = RelationRepository(session)
        evidence_repo = RelationEvidenceRepository(session)
        outbox_repo = OutboxRepository(session)

        summary = await materialize_graph(
            doc_id=doc_id,
            source_type="eodhd_news",
            is_backfill=False,
            relations=[raw_relation],
            canonical_types=["listed_on"],
            events=[],
            claims=[],
            session=session,
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            outbox_repo=outbox_repo,
            direct_producer=mock_producer,  # type: ignore[arg-type]
            entity_dirtied_topic="entity.dirtied.v1",
        )
        await session.commit()

    # Verify relation was written
    async with session_factory() as session:
        result = await session.execute(
            text("""
SELECT COUNT(*) FROM relations
WHERE subject_entity_id = :sub AND object_entity_id = :obj
  AND canonical_type = 'listed_on'
"""),
            {"sub": str(subject_id), "obj": str(obj_id)},
        )
        count = result.scalar()

    assert count >= 1, f"Expected relation in DB after pipeline, got {count}"
    assert summary.relations_upserted >= 1
    assert summary.evidence_rows_inserted >= 1

    # Verify entity.dirtied.v1 was produced directly
    mock_producer.produce_bytes.assert_called()

    # Verify outbox entry for graph.state.changed.v1
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM outbox_events WHERE topic = 'graph.state.changed.v1'")
        )
        outbox_count = result.scalar()

    assert outbox_count >= 1, "Expected graph.state.changed.v1 outbox entry"


@pytest.mark.integration
async def test_s6_s7_pipeline_unknown_type_stages_evidence(session_factory) -> None:
    """Relations with canonical_type=None still stage evidence_raw row (for later resolution)."""

    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("UnknownCorp", "organization")
        obj_id = await entity_repo.create("UnknownTarget", "organization")
        await session.commit()

    raw_relation = RawRelation(
        subject_entity_id=subject_id,
        object_entity_id=obj_id,
        raw_type="unknown_type_xyz",
        extraction_confidence=0.50,
        source_trust_weight=0.55,
        evidence_date=datetime.now(tz=UTC),
    )

    mock_producer = MagicMock()
    mock_producer.produce_bytes = MagicMock()

    async with session_factory() as session:
        relation_repo = RelationRepository(session)
        evidence_repo = RelationEvidenceRepository(session)
        outbox_repo = OutboxRepository(session)

        summary = await materialize_graph(
            doc_id=uuid.uuid4(),
            source_type="eodhd_news",
            is_backfill=False,
            relations=[raw_relation],
            canonical_types=[None],  # unknown type → no upsert, but evidence staged
            events=[],
            claims=[],
            session=session,
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            outbox_repo=outbox_repo,
            direct_producer=mock_producer,  # type: ignore[arg-type]
            entity_dirtied_topic="entity.dirtied.v1",
        )
        await session.commit()

    assert summary.relations_upserted == 0, "canonical_type=None should not create relation row"
    assert summary.evidence_rows_inserted == 1, "Evidence row should still be staged"
