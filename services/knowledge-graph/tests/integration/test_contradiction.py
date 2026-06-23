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
    doc_id, subject_entity_id, claim_type, polarity,
    claim_text, extraction_confidence, created_at
) VALUES (
    :doc_id, :subject_id, :claim_type, :polarity,
    :claim_text, 0.85, :created_at
)
RETURNING claim_id
"""),
        {
            "doc_id": str(uuid.uuid4()),
            "subject_id": str(subject_id),
            "claim_type": claim_type,
            "polarity": polarity,
            "claim_text": f"Test claim {claim_type} {polarity}",
            "created_at": utc_now(),
        },
    )
    row = result.fetchone()
    return uuid.UUID(str(row[0]))  # type: ignore[index]


@pytest.mark.integration()
async def test_opposing_claims_form_contradiction_link(session_factory) -> None:
    """Two opposing non-neutral claims on the same subject/type yield a contradiction link."""
    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("Contra Corp", "organization")
        await session.commit()

    # Insert positive then negative claim
    async with session_factory() as session:
        pos_claim_id = await _insert_claim(session, subject_id, "analyst_rating", "positive")
        neg_claim_id = await _insert_claim(session, subject_id, "analyst_rating", "negative")
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

        # Insert contradiction link. COLUMN-NAMING TRAP (BP-706): despite its
        # name, ``relation_evidence_id`` holds the SUBJECT claim's
        # ``claims.claim_id`` (no FK) — this is what the worker writes and what
        # every read path (``fetch_active_for_subject``) joins on. Passing a
        # ``relation_evidence_raw.raw_id`` here (as this test used to) silently
        # matches no claim, so ``fetch_active_for_subject`` returned 0.
        link_id = await repo.insert_link(
            relation_evidence_id=neg_claim_id,
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


@pytest.mark.integration()
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


@pytest.mark.integration()
async def test_aggregate_contra_stats_maps_links_to_relations(session_factory) -> None:
    """Regression for BP-706 / BUG-2 (2026-06-22 backend-e2e-coverage-gaps).

    The write-path aggregation ``aggregate_contra_stats_for_active_links`` feeds
    ``relations.update_contra_columns``. It MUST resolve a contradiction link to
    the relation(s) it scores via ``claims.claim_id`` (the value actually stored
    in ``relation_contradiction_links.relation_evidence_id``), NOT via
    ``relation_evidence_raw.raw_id``.

    THE TRAP THIS PINS: ``relation_evidence_id`` is named like a
    ``relation_evidence_raw.raw_id`` FK but holds a ``claims.claim_id`` (no FK
    constraint → a misjoin is silently accepted yet matches 0 rows). The third,
    missed read path joined ``rer.raw_id = rcl.relation_evidence_id`` and so
    returned 0 rows on every run, leaving every relation with the default
    ``strongest_contra_score = 0.0`` despite thousands of links existing.

    This test mirrors the real WRITE path (worker stores the *subject claim's*
    claim_id as ``relation_evidence_id``) and asserts the aggregation maps the
    link to a relation on the same subject (>0). The earlier tests in this file
    pass a real ``raw_id`` — exactly the structurally-invisible mismatch that let
    the bug ship — so this case deliberately uses the claim_id.
    """
    from common.time import utc_now  # type: ignore[import-untyped]

    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        subject_id = await entity_repo.create("Aggregate Corp", "organization")
        object_id = await entity_repo.create("Aggregate Object Corp", "organization")
        await session.commit()

    # Two opposing, entity-level financial claims on the subject — the kind that
    # actually carry contradictions (OTHER/REVENUE_GROWTH/…), which have NO
    # relation_evidence_raw rows and whose claim_type is NOT a canonical_type.
    async with session_factory() as session:
        subject_claim_id = await _insert_claim(session, subject_id, "REVENUE_GROWTH", "positive")
        opp_claim_id = await _insert_claim(session, subject_id, "REVENUE_GROWTH", "negative")
        await session.commit()

    # A relation where this entity is the SUBJECT — the contradiction must
    # propagate to it (subject-keyed, like the corrected read paths).
    async with session_factory() as session:
        rel_result = await session.execute(
            text("""
INSERT INTO relations (
    subject_entity_id, canonical_type, object_entity_id,
    semantic_mode, decay_class, decay_alpha, base_confidence,
    confidence, confidence_stale, summary_stale,
    first_evidence_at, latest_evidence_at, evidence_count
) VALUES (
    :sub, 'partner_of', :obj,
    'RELATION_STATE', 'DURABLE', 0.01, 0.5,
    0.5, true, true,
    now(), now(), 1
)
RETURNING relation_id
"""),
            {"sub": str(subject_id), "obj": str(object_id)},
        )
        relation_id = uuid.UUID(str(rel_result.fetchone()[0]))  # type: ignore[index]
        await session.commit()

    # Insert the contradiction link mirroring the WORKER write path:
    # relation_evidence_id = the SUBJECT claim's claim_id (NOT a raw_id).
    async with session_factory() as session:
        repo = ContradictionRepository(session)
        await repo.insert_link(
            relation_evidence_id=subject_claim_id,
            claim_id=opp_claim_id,
            contradiction_type="polarity_conflict",
            strength=0.77,
            detected_at=utc_now(),  # type: ignore[no-any-return]
        )
        await session.commit()

    # The aggregation must now resolve the link to the relation (>0 rows).
    async with session_factory() as session:
        repo = ContradictionRepository(session)
        stats = await repo.aggregate_contra_stats_for_active_links()

    mapped = [s for s in stats if s["relation_id"] == relation_id]
    assert mapped, (
        "aggregate_contra_stats_for_active_links must map the contradiction link "
        "to the subject's relation via claims.claim_id (got 0 rows for it — the "
        "misjoin on relation_evidence_raw.raw_id has silently regressed)"
    )
    stat = mapped[0]
    assert stat["strongest_contra_score"] == pytest.approx(0.77)
    assert stat["contra_count_by_type"] == {"polarity_conflict": 1}
    assert stat["latest_contra_at"] is not None
    assert stat["current_confidence"] == pytest.approx(0.5)


@pytest.mark.integration()
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
    source_document_id, extraction_confidence, source_trust_weight,
    evidence_date
) VALUES (
    :sub, 'price_target', :obj, gen_random_uuid(),
    0.80, 0.60, now()
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
