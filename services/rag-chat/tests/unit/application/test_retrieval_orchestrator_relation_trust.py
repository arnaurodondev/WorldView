"""Regression tests: relation/graph legs must not double-count source trust.

Bug (high): a relation's `confidence` is the PLAN-0109 Beta posterior P(true), which
ALREADY folds in graded source_trust_weights, corroboration (syndication dedup) and
extraction_confidence. The relation/graph legs of ParallelRetrievalOrchestrator used to
pass it through TrustScorer.score(source_type="relation"), which RE-APPLIES source
authority + a default corroboration(0.5) + extraction(0.5) on top — counting source
trust twice.

These tests pin the fix:
  - _fetch_relations and _fetch_graph set trust_weight = 1.0 (no second trust multiplier);
  - fusion_score for a relation == confidence * recency * 1.0 (trust enters exactly once,
    inside the confidence posterior);
  - ranking is sane: a higher-confidence relation outranks a lower-confidence one when
    recency is equal (the old double-count could only ever shrink relation scores, but the
    invariant we lock here is the trust_weight, which is the conflation point).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from rag_chat.application.pipeline.retrieval_orchestrator import (
    _RELATION_TRUST_WEIGHT,
    ParallelRetrievalOrchestrator,
)
from rag_chat.application.pipeline.trust_scorer import TrustScorer
from rag_chat.application.ports.upstream_clients import EgocentricGraph, RelationResult
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_orchestrator(s7: AsyncMock) -> ParallelRetrievalOrchestrator:
    """Build the orchestrator with a given S7 mock and no-op other clients."""
    s6 = AsyncMock()
    s3 = AsyncMock()
    s1 = AsyncMock()
    return ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        timeout=5.0,
    )


def _make_relation(relation_id: str, confidence: float) -> RelationResult:
    return RelationResult(
        relation_id=relation_id,
        subject="Apple Inc.",
        relation_type="SUPPLIER_OF",
        object="TSMC",
        summary="Apple sources chips from TSMC.",
        confidence=confidence,
        # latest_evidence_at left None → recency_score is deterministic for both items,
        # so any score delta is attributable to confidence/trust, not recency.
    )


# ── relation leg: trust_weight is 1.0 (no double-count) ───────────────────────


class TestRelationLegTrustNotDoubleCounted:
    @pytest.mark.asyncio
    async def test_fetch_relations_uses_unit_trust_weight(self) -> None:
        """_fetch_relations must hold trust_weight at 1.0, not TrustScorer("relation")."""
        s7 = AsyncMock()
        s7.search_relations = AsyncMock(return_value=[_make_relation("rel-1", confidence=0.9)])
        orchestrator = _make_orchestrator(s7)

        items = await orchestrator._fetch_relations(embedding=[0.1] * 1024, entity_ids=[uuid4()])

        assert len(items) == 1
        item = items[0]
        assert item.item_type is ItemType.relation
        # The conflation point: trust must NOT be re-applied on top of the posterior.
        assert item.trust_weight == _RELATION_TRUST_WEIGHT == 1.0

    @pytest.mark.asyncio
    async def test_fetch_relations_trust_weight_differs_from_scorer(self) -> None:
        """Document the regression: TrustScorer('relation') would re-apply authority.

        If the leg ever reverts to trust_weight=TrustScorer.score('relation'), this guard
        fails — the scorer yields ~0.42 (0.4*0.80 + 0.1*0.5 + 0.1*0.5), proving a second
        trust multiplier was applied to an already-trust-folded confidence.
        """
        s7 = AsyncMock()
        s7.search_relations = AsyncMock(return_value=[_make_relation("rel-1", confidence=0.9)])
        orchestrator = _make_orchestrator(s7)

        items = await orchestrator._fetch_relations(embedding=[0.1] * 1024, entity_ids=[uuid4()])

        scorer_weight = TrustScorer().score(source_type="relation")
        assert scorer_weight < 1.0  # sanity: the old path shrank relation scores
        assert items[0].trust_weight != scorer_weight

    @pytest.mark.asyncio
    async def test_fetch_relations_fusion_score_is_confidence_times_recency(self) -> None:
        """fusion_score = score * recency * trust_weight, with trust_weight == 1.0.

        So a relation's fusion_score reduces to confidence * recency — trust enters
        exactly once (inside the confidence posterior), never twice.
        """
        s7 = AsyncMock()
        s7.search_relations = AsyncMock(return_value=[_make_relation("rel-1", confidence=0.9)])
        orchestrator = _make_orchestrator(s7)

        item = (await orchestrator._fetch_relations(embedding=[0.1] * 1024, entity_ids=[uuid4()]))[0]

        assert item.fusion_score == pytest.approx(item.score * item.recency_score)

    @pytest.mark.asyncio
    async def test_higher_confidence_relation_outranks_lower(self) -> None:
        """With equal recency, a higher-confidence relation must outrank a lower one."""
        s7 = AsyncMock()
        s7.search_relations = AsyncMock(
            return_value=[
                _make_relation("rel-low", confidence=0.40),
                _make_relation("rel-high", confidence=0.95),
            ]
        )
        orchestrator = _make_orchestrator(s7)

        items = await orchestrator._fetch_relations(embedding=[0.1] * 1024, entity_ids=[uuid4()])
        ranked = sorted(items, key=lambda i: i.fusion_score, reverse=True)

        assert ranked[0].item_id == "rel-high"
        assert ranked[1].item_id == "rel-low"


# ── graph-edge leg: same invariant ────────────────────────────────────────────


class TestGraphEdgeLegTrustNotDoubleCounted:
    @pytest.mark.asyncio
    async def test_fetch_graph_uses_unit_trust_weight(self) -> None:
        """_fetch_graph edges must also hold trust_weight at 1.0 (same Beta posterior)."""
        s7 = AsyncMock()
        s7.get_egocentric_graph = AsyncMock(
            return_value=EgocentricGraph(
                entity_id="e1",
                nodes=[],
                edges=[
                    {
                        "relation_id": "edge-1",
                        "subject": "Apple Inc.",
                        "relation_type": "SUPPLIER_OF",
                        "object": "TSMC",
                        "summary": "Apple sources chips from TSMC.",
                        "confidence": 0.88,
                    }
                ],
            )
        )
        orchestrator = _make_orchestrator(s7)

        items = await orchestrator._fetch_graph(entity_id=uuid4())

        assert len(items) == 1
        assert items[0].trust_weight == _RELATION_TRUST_WEIGHT == 1.0
        assert items[0].fusion_score == pytest.approx(items[0].score * items[0].recency_score)
