"""Integration tests for contradiction detection round-trip (Block 12b / Worker 13B).

Verifies:
- Two opposing, non-neutral claims on the same (subject, type) create a link.
- The link is returned by fetch_active_for_subject.
- Neutral polarity claims do NOT form contradictions (find_opposing_claims returns []).
"""

from __future__ import annotations

import uuid

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
    ContradictionRepository,
)
from sqlalchemy import text


async def _insert_claim(session, subject_id: uuid.UUID, claim_type: str, polarity: str) -> uuid.UUID:
    """Insert a minimal claim row; returns claim_id."""
    from common.time import utc_now  # type: ignore[import-untyped]

    result = await session.execute(
        text("""
INSERT INTO claims (
    subject_entity_id, claim_type, polarity,
    claim_text, extraction_confidence, created_at
) VALUES (
    :subject_id, :claim_type, :polarity,
    :claim_text, 0.85, :created_at
)
RETURNING claim_id
"""),
        {
            "subject_id": str(subject_id),
            "claim_type": claim_type,
            "polarity": polarity,
            "claim_text": f"Test claim {claim_type} {polarity}",
            "created_at": utc_now(),
        },
    )
    row = result.fetchone()
    return uuid.UUID(str(row[0]))  # type: ignore[index]


@pytest.mark.integration
async def test_opposing_claims_form_contradiction_link(session_factory) -> None:
    """Two opposing non-neutral claims on the same subject/type yield a contradiction link."""
    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("Contra Corp", "organization")
        await session.commit()

    # Insert positive then negative claim
    async with session_factory() as session:
        pos_claim_id = await _insert_claim(session, subject_id, "analyst_rating", "positive")
        await _insert_claim(session, subject_id, "analyst_rating", "negative")
        await session.commit()

    # Insert a mock evidence row for the negative claim to reference
    async with session_factory() as session:
        rel_ev_result = await session.execute(
            text("""
INSERT INTO relation_evidence_raw (
    subject_entity_id, canonical_type, object_entity_id,
    doc_id, source_type, extraction_confidence, source_weight,
    evidence_date, semantic_mode
) VALUES (
    :sub, 'analyst_rating', :obj,
    gen_random_uuid(), 'eodhd_news', 0.85, 0.60,
    now(), 'TEMPORAL_CLAIM'
)
RETURNING raw_id
"""),
            {"sub": str(subject_id), "obj": str(uuid.uuid4())},
        )
        raw_id = uuid.UUID(str(rel_ev_result.fetchone()[0]))  # type: ignore[index]
        await session.commit()

    from common.time import utc_now  # type: ignore[import-untyped]

    async with session_factory() as session:
        repo = ContradictionRepository(session)

        # Confirm find_opposing_claims finds the positive claim as opposite to negative
        opposites = await repo.find_opposing_claims(
            subject_entity_id=subject_id,
            claim_type="analyst_rating",
            polarity="negative",
        )
        assert len(opposites) >= 1, "Should find at least one opposing (positive) claim"

        # Insert contradiction link
        link_id = await repo.insert_link(
            relation_evidence_id=raw_id,
            claim_id=pos_claim_id,
            contradiction_type="polarity_flip",
            strength=0.75,
            detected_at=utc_now(),  # type: ignore[no-any-return]
        )
        await session.commit()

    assert link_id is not None

    async with session_factory() as session:
        repo = ContradictionRepository(session)
        active = await repo.fetch_active_for_subject(subject_id)

    assert len(active) >= 1, "Contradiction link should be active after insertion"


@pytest.mark.integration
async def test_neutral_polarity_does_not_contradict(session_factory) -> None:
    """find_opposing_claims returns empty list for neutral polarity."""
    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("Neutral Corp", "organization")
        await session.commit()

    async with session_factory() as session:
        await _insert_claim(session, subject_id, "analyst_rating", "positive")
        await session.commit()

    async with session_factory() as session:
        repo = ContradictionRepository(session)
        opposites = await repo.find_opposing_claims(
            subject_entity_id=subject_id,
            claim_type="analyst_rating",
            polarity="neutral",  # neutral cannot form contradictions
        )

    assert opposites == [], "Neutral polarity should never return opposing claims"


@pytest.mark.integration
async def test_contradiction_link_idempotent(session_factory) -> None:
    """insert_link with ON CONFLICT DO NOTHING returns same link_id on repeat."""
    from common.time import utc_now  # type: ignore[import-untyped]

    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("Idem Corp", "organization")
        await session.commit()

    async with session_factory() as session:
        claim_id = await _insert_claim(session, subject_id, "price_target", "negative")
        ev_result = await session.execute(
            text("""
INSERT INTO relation_evidence_raw (
    subject_entity_id, canonical_type, object_entity_id,
    doc_id, source_type, extraction_confidence, source_weight,
    evidence_date, semantic_mode
) VALUES (
    :sub, 'price_target', :obj, gen_random_uuid(),
    'eodhd_news', 0.80, 0.60, now(), 'TEMPORAL_CLAIM'
)
RETURNING raw_id
"""),
            {"sub": str(subject_id), "obj": str(uuid.uuid4())},
        )
        raw_id = uuid.UUID(str(ev_result.fetchone()[0]))  # type: ignore[index]
        await session.commit()

    async with session_factory() as session:
        repo = ContradictionRepository(session)
        t = utc_now()  # type: ignore[no-any-return]
        lid1 = await repo.insert_link(raw_id, claim_id, "polarity_flip", 0.6, t)
        lid2 = await repo.insert_link(raw_id, claim_id, "polarity_flip", 0.6, t)
        await session.commit()

    assert lid1 == lid2, "Duplicate insert_link must return same link_id"
