"""Integration tests for relation upsert idempotency (Block 12a).

Verifies:
- Upsert creates a new relation on first insert.
- Repeated upsert on the same (subject, type, object) triple increments
  evidence_count and marks confidence_stale = true, but does NOT create
  a duplicate row.
- partition_key is STORED and cannot be set in INSERT (validated by schema).
"""

from __future__ import annotations

import uuid

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
    RelationRepository,
)
from sqlalchemy import text


def _make_entity_id() -> uuid.UUID:
    return uuid.uuid4()


async def _create_entity(session, name: str, entity_type: str = "organization") -> uuid.UUID:
    repo = CanonicalEntityRepository(session)
    return await repo.create(canonical_name=name, entity_type=entity_type)


@pytest.mark.integration
async def test_relation_upsert_creates_new_row(session_factory) -> None:
    """First upsert creates exactly one row."""
    async with session_factory() as session:
        sub = await _create_entity(session, "Apple Inc.")
        obj = await _create_entity(session, "NASDAQ")
        await session.commit()

    async with session_factory() as session:
        repo = RelationRepository(session)
        rel_id = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        await session.commit()

    assert rel_id is not None

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM relations WHERE relation_id = :rid"),
            {"rid": str(rel_id)},
        )
        assert result.scalar() == 1


@pytest.mark.integration
async def test_relation_upsert_idempotent(session_factory) -> None:
    """Repeated upsert on same triple does NOT create duplicates; increments evidence_count."""
    async with session_factory() as session:
        sub = await _create_entity(session, "Tesla Inc.")
        obj = await _create_entity(session, "NYSE")
        await session.commit()

    # First upsert
    async with session_factory() as session:
        repo = RelationRepository(session)
        rid1 = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        await session.commit()

    # Second upsert (same triple)
    async with session_factory() as session:
        repo = RelationRepository(session)
        rid2 = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        await session.commit()

    assert rid1 == rid2, "Second upsert must return the same relation_id"

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT evidence_count, confidence_stale FROM relations WHERE relation_id = :rid"),
            {"rid": str(rid1)},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] >= 2, f"evidence_count should be ≥ 2, got {row[0]}"
    assert row[1] is True, "confidence_stale should be True after upsert"


@pytest.mark.integration
async def test_different_triples_create_separate_rows(session_factory) -> None:
    """Different (subject, type, object) triples create separate relation rows."""
    async with session_factory() as session:
        sub = await _create_entity(session, "Microsoft Corp.")
        obj1 = await _create_entity(session, "NASDAQ")
        obj2 = await _create_entity(session, "NYSE")
        await session.commit()

    async with session_factory() as session:
        repo = RelationRepository(session)
        rid1 = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj1,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        rid2 = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj2,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        await session.commit()

    assert rid1 != rid2
