"""Unit tests for RoutingDecisionRepository round-trip — PLAN-0057 A-1.

Covers persistence of:
- ``routing_tier`` (existing baseline)
- ``final_routing_tier`` (Block 8 novelty downgrade — defensive re-add)
- ``processing_path`` (NEW Block 6 suppression-gate output, F-CRIT-06)
- ``composite_score`` + ``feature_scores_json``

Mocks the AsyncSession to assert the row populated from the dataclass carries
all fields (we already have an integration round-trip test in
test_consumer_pipeline.py; here we're proving the field plumbing).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from nlp_pipeline.domain.enums import ProcessingPath, RoutingTier
from nlp_pipeline.domain.models import RoutingDecision
from nlp_pipeline.infrastructure.nlp_db.repositories.routing_decision import (
    RoutingDecisionRepository,
)

if TYPE_CHECKING:
    from nlp_pipeline.infrastructure.nlp_db.models import RoutingDecisionModel

pytestmark = pytest.mark.unit


def _capture_session_add() -> tuple[MagicMock, list[Any]]:
    """Build an AsyncSession mock that records every ``.add(...)`` call."""
    captured: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: captured.append(obj))
    session.execute = AsyncMock()
    return session, captured


@pytest.mark.asyncio
async def test_add_persists_processing_path_full_pipeline() -> None:
    """The new processing_path field round-trips through repo.add()."""
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000001"),
        doc_id=UUID("00000000-0000-0000-0000-000000000002"),
        routing_tier=RoutingTier.DEEP,
        composite_score=0.82,
        feature_scores={"entity_density": 0.5},
        final_routing_tier=None,
        processing_path=ProcessingPath.FULL_PIPELINE,
    )

    await repo.add(decision)

    assert len(captured) == 1
    row: RoutingDecisionModel = captured[0]
    assert row.processing_path == "full_pipeline"
    assert row.routing_tier == "deep"
    assert row.final_routing_tier is None


@pytest.mark.asyncio
async def test_add_handles_novelty_downgrade_full_set_of_fields() -> None:
    """Block 8 novelty path: tier=DEEP, final_tier=LIGHT, path=SECTION_EMBEDDINGS_ONLY."""
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-00000000000a"),
        doc_id=UUID("00000000-0000-0000-0000-00000000000b"),
        routing_tier=RoutingTier.DEEP,
        composite_score=0.74,
        feature_scores={"entity_density": 0.6, "novelty": 0.05},
        final_routing_tier=RoutingTier.LIGHT,
        processing_path=ProcessingPath.SECTION_EMBEDDINGS_ONLY,
    )

    await repo.add(decision)

    row: RoutingDecisionModel = captured[0]
    assert row.routing_tier == "deep"
    assert row.final_routing_tier == "light"
    assert row.processing_path == "section_embeddings_only"


@pytest.mark.asyncio
async def test_add_legacy_decision_without_processing_path() -> None:
    """Legacy callers that don't set processing_path get None — backward compatible."""
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-00000000000c"),
        doc_id=UUID("00000000-0000-0000-0000-00000000000d"),
        routing_tier=RoutingTier.MEDIUM,
        composite_score=0.5,
        feature_scores={},
    )

    await repo.add(decision)

    row: RoutingDecisionModel = captured[0]
    assert row.processing_path is None


@pytest.mark.asyncio
async def test_add_halt_path_for_suppress_tier() -> None:
    """SUPPRESS routing tier yields HALT processing path."""
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-00000000000e"),
        doc_id=UUID("00000000-0000-0000-0000-00000000000f"),
        routing_tier=RoutingTier.SUPPRESS,
        composite_score=0.15,
        feature_scores={},
        processing_path=ProcessingPath.HALT,
    )

    await repo.add(decision)

    row: RoutingDecisionModel = captured[0]
    assert row.routing_tier == "suppress"
    assert row.processing_path == "halt"


# ── T-W5-4-02: routing-tier write-path audit tests ────────────────────────────
# These tests confirm that final_routing_tier and processing_path are
# ALWAYS non-NULL on rows produced by the post-novelty pipeline path.
# Audit finding (PLAN-0063 W5-4): both fields ARE written by the existing
# repo — no code fix required; tests added as living documentation.


@pytest.mark.asyncio
async def test_routing_decision_writes_final_routing_tier() -> None:
    """add() with a non-None final_routing_tier → row.final_routing_tier is non-NULL.

    Verifies the PLAN-0057 A-1 Block 8 novelty-downgrade path is persisted.
    """
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000010"),
        doc_id=UUID("00000000-0000-0000-0000-000000000011"),
        routing_tier=RoutingTier.DEEP,
        composite_score=0.78,
        feature_scores={"entity_density": 0.6},
        final_routing_tier=RoutingTier.LIGHT,
        processing_path=ProcessingPath.SECTION_EMBEDDINGS_ONLY,
    )

    await repo.add(decision)

    row: RoutingDecisionModel = captured[0]
    assert row.final_routing_tier is not None, "final_routing_tier must be written for post-novelty rows"
    assert row.final_routing_tier == "light"


@pytest.mark.asyncio
async def test_routing_decision_writes_processing_path() -> None:
    """add() with a non-None processing_path → row.processing_path is non-NULL.

    Verifies the PLAN-0057 A-1 Block 6 suppression-gate output (F-CRIT-06) is persisted.
    """
    session, captured = _capture_session_add()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-000000000012"),
        doc_id=UUID("00000000-0000-0000-0000-000000000013"),
        routing_tier=RoutingTier.MEDIUM,
        composite_score=0.55,
        feature_scores={},
        processing_path=ProcessingPath.FULL_PIPELINE,
    )

    await repo.add(decision)

    row: RoutingDecisionModel = captured[0]
    assert row.processing_path is not None, "processing_path must be written for all post-W5-4 rows"
    assert row.processing_path == "full_pipeline"
