"""Unit tests for RetrievalPlanBuilder (PLAN-0063 W5-3 / T-E-2-02).

Verifies every intent's flag matrix and the FINANCIAL_DATA/RELATIONSHIP
use_chunks=True fix (commit 9414a8b8). The cypher_enabled feature flag was
removed in 2026-05 — ``use_cypher`` is now driven purely by the per-intent
matrix; the tool-use loop is the runtime gate for the cypher traversal tool.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000001")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _builder() -> RetrievalPlanBuilder:
    return RetrievalPlanBuilder()


# ── use_chunks=True coverage (regression for FINANCIAL_DATA / RELATIONSHIP) ───


@pytest.mark.parametrize(
    "intent",
    [
        QueryIntent.FACTUAL_LOOKUP,
        QueryIntent.RELATIONSHIP,
        QueryIntent.SIGNAL_INTEL,
        QueryIntent.FINANCIAL_DATA,
        QueryIntent.COMPARISON,
        QueryIntent.REASONING,
        QueryIntent.PORTFOLIO,
        QueryIntent.GENERAL,
    ],
)
def test_all_intents_use_chunks(intent: QueryIntent) -> None:
    """Every intent must include chunk retrieval (no zero-candidate classes)."""
    plan = _builder().build(intent)
    assert plan.use_chunks is True, f"{intent} must have use_chunks=True"


# ── FINANCIAL_DATA matrix ─────────────────────────────────────────────────────


def test_financial_data_flags() -> None:
    plan = _builder().build(QueryIntent.FINANCIAL_DATA)
    assert plan.use_chunks is True
    assert plan.use_claims is True
    assert plan.use_events is True
    assert plan.use_financial is True
    assert plan.use_relations is False
    assert plan.use_graph is False
    assert plan.use_contradictions is False
    assert plan.use_portfolio is False
    assert plan.use_cypher is False  # intent matrix base False


# ── RELATIONSHIP matrix ───────────────────────────────────────────────────────


def test_relationship_flags() -> None:
    plan = _builder().build(QueryIntent.RELATIONSHIP)
    assert plan.use_chunks is True
    assert plan.use_relations is True
    assert plan.use_graph is True
    assert plan.use_claims is False
    assert plan.use_events is False
    assert plan.use_contradictions is False
    assert plan.use_financial is False
    assert plan.use_portfolio is False


def test_relationship_uses_cypher() -> None:
    """RELATIONSHIP intent → use_cypher=True (per intent matrix)."""
    assert _builder().build(QueryIntent.RELATIONSHIP).use_cypher is True


# ── REASONING matrix ──────────────────────────────────────────────────────────


def test_reasoning_uses_cypher() -> None:
    """REASONING intent → use_cypher=True (per intent matrix)."""
    assert _builder().build(QueryIntent.REASONING).use_cypher is True


# ── GENERAL minimal matrix ────────────────────────────────────────────────────


def test_general_minimal_flags() -> None:
    plan = _builder().build(QueryIntent.GENERAL)
    assert plan.use_chunks is True
    assert plan.use_relations is False
    assert plan.use_graph is False
    assert plan.use_claims is False
    assert plan.use_events is False
    assert plan.use_financial is False
    assert plan.use_portfolio is False
    assert plan.use_cypher is False


# ── Entity and date context passthrough ───────────────────────────────────────


def test_entity_ids_passed_through() -> None:
    plan = _builder().build(QueryIntent.FACTUAL_LOOKUP, entity_ids=(_ENTITY_ID,))
    assert plan.entity_ids == (_ENTITY_ID,)


def test_empty_entity_ids_by_default() -> None:
    plan = _builder().build(QueryIntent.FACTUAL_LOOKUP)
    assert plan.entity_ids == ()


def test_date_filter_none_by_default() -> None:
    plan = _builder().build(QueryIntent.FACTUAL_LOOKUP)
    assert plan.date_filter is None


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────


def test_portfolio_uses_portfolio_flag() -> None:
    plan = _builder().build(QueryIntent.PORTFOLIO)
    assert plan.use_portfolio is True
    assert plan.use_financial is True
