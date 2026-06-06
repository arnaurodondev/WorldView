"""Integration tests for confidence formula bounds (PRD §10.1).

Verifies:
- final confidence is bounded in [0, 1].
- corroboration gain is capped at 0.20.
- ConfidenceComponents.validate() raises on violation.
"""

from __future__ import annotations

import pytest
from knowledge_graph.domain.errors import ConfidenceBoundsViolation
from knowledge_graph.domain.models import ConfidenceComponents


@pytest.mark.integration()
def test_confidence_final_bounded_lower() -> None:
    """confidence clamped to 0 when formula would yield negative."""
    cc = ConfidenceComponents(
        support=0.1,
        corroboration=0.0,
        contradiction=0.6,  # cap is exactly 0.60
        final=0.0,
    )
    cc.validate()  # should not raise


@pytest.mark.integration()
def test_confidence_final_bounded_upper() -> None:
    cc = ConfidenceComponents(
        support=0.95,
        corroboration=0.20,  # at cap
        contradiction=0.0,
        final=1.0,
    )
    cc.validate()


@pytest.mark.integration()
def test_confidence_corroboration_cap_violation() -> None:
    """corroboration > 0.20 must raise ConfidenceBoundsViolation."""
    cc = ConfidenceComponents(
        support=0.70,
        corroboration=0.21,  # exceeds cap
        contradiction=0.0,
        final=0.70,
    )
    with pytest.raises(ConfidenceBoundsViolation, match="corroboration"):
        cc.validate()


@pytest.mark.integration()
def test_confidence_contradiction_cap_violation() -> None:
    """contradiction > 0.60 must raise ConfidenceBoundsViolation."""
    cc = ConfidenceComponents(
        support=0.70,
        corroboration=0.0,
        contradiction=0.61,  # exceeds cap
        final=0.70,
    )
    with pytest.raises(ConfidenceBoundsViolation, match="contradiction"):
        cc.validate()


@pytest.mark.integration()
def test_confidence_final_out_of_range_raises() -> None:
    """final outside [0, 1] must raise."""
    cc = ConfidenceComponents(
        support=0.5,
        corroboration=0.0,
        contradiction=0.0,
        final=1.01,
    )
    with pytest.raises(ConfidenceBoundsViolation, match="final"):
        cc.validate()


@pytest.mark.integration()
async def test_confidence_mark_updated_persists(session_factory) -> None:
    """mark_confidence_updated persists the new confidence value to intelligence_db."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
        RelationRepository,
    )

    from common.time import utc_now  # type: ignore[import-untyped]

    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        sub = await entity_repo.create("Conf Corp", "organization")
        obj = await entity_repo.create("Exchange", "exchange")
        await session.commit()

    async with session_factory() as session:
        repo = RelationRepository(session)
        rid = await repo.upsert(
            subject_entity_id=sub,
            object_entity_id=obj,
            canonical_type="listed_on",
            semantic_mode="RELATION_STATE",
            decay_class="DURABLE",
            decay_alpha=0.000950,
            base_confidence=0.80,
        )
        await session.commit()

    target_confidence = 0.723
    async with session_factory() as session:
        repo = RelationRepository(session)
        await repo.mark_confidence_updated(rid, target_confidence, utc_now())  # type: ignore[no-any-return]
        await session.commit()

    async with session_factory() as session:
        from sqlalchemy import text

        result = await session.execute(
            text("SELECT confidence, confidence_stale FROM relations WHERE relation_id = :rid"),
            {"rid": str(rid)},
        )
        row = result.fetchone()

    assert row is not None
    assert abs(float(row[0]) - target_confidence) < 1e-6
    assert row[1] is False, "confidence_stale should be False after mark_confidence_updated"
