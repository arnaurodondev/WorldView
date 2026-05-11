"""Unit tests for RoutingDecisionRepository round-trip — PLAN-0057 A-1.

Covers persistence of:
- ``routing_tier`` (existing baseline)
- ``final_routing_tier`` (Block 8 novelty downgrade — defensive re-add)
- ``processing_path`` (NEW Block 6 suppression-gate output, F-CRIT-06)
- ``composite_score`` + ``feature_scores_json``

PLAN-0084 B-3 switched the repo from ``session.add(model)`` to
``session.execute(pg_insert(model).on_conflict_do_nothing(...))``, so
these tests now capture the values dict from the pg_insert statement via
SQLAlchemy's ``_values`` internal (stable in 2.x) rather than intercepting
``session.add``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from nlp_pipeline.domain.enums import ProcessingPath, RoutingTier
from nlp_pipeline.domain.models import RoutingDecision
from nlp_pipeline.infrastructure.nlp_db.repositories.routing_decision import (
    RoutingDecisionRepository,
)

pytestmark = pytest.mark.unit


def _make_session() -> tuple[MagicMock, list[dict[str, Any]]]:
    """Return (session mock, captured_params_list).

    Each ``repo.add()`` call appends a dict of {column_key: value} to the list,
    extracted from the pg_insert statement passed to ``session.execute``.
    B-3 changed add() to use pg_insert + on_conflict_do_nothing — the session
    no longer receives a ``session.add(model)`` call; values are bound in the
    INSERT statement itself.
    """
    captured: list[dict[str, Any]] = []

    async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        vals: dict[str, Any] = {}
        for col, bindparam in stmt._values.items():
            vals[col.key] = bindparam.value
        captured.append(vals)
        return MagicMock()

    session = MagicMock()
    session.add = MagicMock()
    session.execute = _fake_execute
    return session, captured


@pytest.mark.asyncio
async def test_add_persists_processing_path_full_pipeline() -> None:
    """The new processing_path field round-trips through repo.add()."""
    session, captured = _make_session()
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
    params = captured[0]
    assert params["processing_path"] == "full_pipeline"
    assert params["routing_tier"] == "deep"
    assert params["final_routing_tier"] is None


@pytest.mark.asyncio
async def test_add_handles_novelty_downgrade_full_set_of_fields() -> None:
    """Block 8 novelty path: tier=DEEP, final_tier=LIGHT, path=SECTION_EMBEDDINGS_ONLY."""
    session, captured = _make_session()
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

    params = captured[0]
    assert params["routing_tier"] == "deep"
    assert params["final_routing_tier"] == "light"
    assert params["processing_path"] == "section_embeddings_only"


@pytest.mark.asyncio
async def test_add_legacy_decision_without_processing_path() -> None:
    """Legacy callers that don't set processing_path get None — backward compatible."""
    session, captured = _make_session()
    repo = RoutingDecisionRepository(session)

    decision = RoutingDecision(
        decision_id=UUID("00000000-0000-0000-0000-00000000000c"),
        doc_id=UUID("00000000-0000-0000-0000-00000000000d"),
        routing_tier=RoutingTier.MEDIUM,
        composite_score=0.5,
        feature_scores={},
    )

    await repo.add(decision)

    params = captured[0]
    assert params["processing_path"] is None


@pytest.mark.asyncio
async def test_add_halt_path_for_suppress_tier() -> None:
    """SUPPRESS routing tier yields HALT processing path."""
    session, captured = _make_session()
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

    params = captured[0]
    assert params["routing_tier"] == "suppress"
    assert params["processing_path"] == "halt"


# ── T-W5-4-02: routing-tier write-path audit tests ────────────────────────────
# These tests confirm that final_routing_tier and processing_path are
# ALWAYS non-NULL on rows produced by the post-novelty pipeline path.
# Audit finding (PLAN-0063 W5-4): both fields ARE written by the existing
# repo — no code fix required; tests added as living documentation.


@pytest.mark.asyncio
async def test_routing_decision_writes_final_routing_tier() -> None:
    """add() with a non-None final_routing_tier → value is non-NULL in the INSERT.

    Verifies the PLAN-0057 A-1 Block 8 novelty-downgrade path is persisted.
    """
    session, captured = _make_session()
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

    params = captured[0]
    assert params["final_routing_tier"] is not None, "final_routing_tier must be written for post-novelty rows"
    assert params["final_routing_tier"] == "light"


@pytest.mark.asyncio
async def test_routing_decision_writes_processing_path() -> None:
    """add() with a non-None processing_path → value is non-NULL in the INSERT.

    Verifies the PLAN-0057 A-1 Block 6 suppression-gate output (F-CRIT-06) is persisted.
    """
    session, captured = _make_session()
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

    params = captured[0]
    assert params["processing_path"] is not None, "processing_path must be written for all post-W5-4 rows"
    assert params["processing_path"] == "full_pipeline"
