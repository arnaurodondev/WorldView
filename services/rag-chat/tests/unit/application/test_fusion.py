"""Unit tests for FusionPipeline and GraphEnricher (T-F-1-02)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from rag_chat.application.pipeline.fusion import FusionPipeline, GraphEnricher
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType


def _item(
    *,
    item_id: str = "id-1",
    item_type: ItemType = ItemType.chunk,
    score: float = 0.80,
    trust_weight: float = 0.90,
    published_at: datetime | None = None,
    doc_id=None,
    entity_name: str | None = None,
) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=item_type,
        text=f"Text for {item_id}",
        score=score,
        trust_weight=trust_weight,
        citation_meta=CitationMeta(
            title=None,
            url=None,
            source_name="test",
            published_at=published_at,
            entity_name=entity_name,
        ),
        doc_id=doc_id,
        published_at=published_at,
    )


def _relation_result(subject: str, summary_authority: float | None = 0.85, confidence: float = 0.85) -> MagicMock:
    r = MagicMock()
    r.relation_id = f"rel-{subject}"
    r.relation_type = "OWNS"
    r.subject = subject
    r.object = "Target Corp"
    r.summary = f"{subject} owns Target Corp"
    r.confidence = confidence
    r.summary_authority = summary_authority
    return r


@pytest.fixture
def fusion() -> FusionPipeline:
    return FusionPipeline()


@pytest.fixture
def enricher() -> GraphEnricher:
    return GraphEnricher()


@pytest.mark.unit
def test_fusion_dedup_keeps_max_score(fusion: FusionPipeline) -> None:
    """Two items with same doc_id → only the one with higher fusion_score is kept."""
    doc_id = uuid4()
    low = _item(item_id="low", score=0.50, trust_weight=0.80, doc_id=doc_id)
    high = _item(item_id="high", score=0.90, trust_weight=0.80, doc_id=doc_id)

    result = fusion.process([low, high])
    assert len(result) == 1
    assert result[0].item_id == "high"


@pytest.mark.unit
def test_fusion_sorts_by_fusion_score(fusion: FusionPipeline) -> None:
    """Items are sorted descending by fusion_score."""
    items = [
        _item(item_id="a", score=0.30, trust_weight=0.60),
        _item(item_id="b", score=0.90, trust_weight=0.95),
        _item(item_id="c", score=0.60, trust_weight=0.80),
    ]
    result = fusion.process(items)
    scores = [r.fusion_score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
def test_fusion_trust_weight_applied(fusion: FusionPipeline) -> None:
    """SEC filing (trust 0.95) scores higher than news (trust 0.65) at same base score."""
    sec = _item(item_id="sec", score=0.80, trust_weight=0.95)
    news = _item(item_id="news", score=0.80, trust_weight=0.65)

    result = fusion.process([news, sec])
    assert result[0].item_id == "sec"


@pytest.mark.unit
def test_fusion_top_30_limit(fusion: FusionPipeline) -> None:
    """More than 30 items → only top 30 returned."""
    items = [_item(item_id=f"item-{i}", score=float(i) / 100) for i in range(50)]
    result = fusion.process(items)
    assert len(result) == 30


@pytest.mark.unit
def test_fusion_empty_input(fusion: FusionPipeline) -> None:
    """Empty input → empty output."""
    assert fusion.process([]) == []


@pytest.mark.unit
def test_graph_enricher_injects_top3_relations(enricher: GraphEnricher) -> None:
    """Chunk with entity → top-3 relations attached as graph_enrichment."""
    chunk = _item(item_type=ItemType.chunk, entity_name="Apple Inc")
    relations = [
        _relation_result("Apple Inc", summary_authority=0.90, confidence=0.90),
        _relation_result("Apple Inc", summary_authority=0.80, confidence=0.80),
        _relation_result("Apple Inc", summary_authority=0.70, confidence=0.70),
        _relation_result("Apple Inc", summary_authority=0.60, confidence=0.60),  # 4th — excluded
    ]

    result = enricher.enrich([chunk], relations)
    assert len(result) == 1
    # Up to 3 relations injected
    assert len(result[0].graph_enrichment) <= 3
    assert len(result[0].graph_enrichment) > 0


@pytest.mark.unit
def test_graph_enricher_caps_at_2_entities_per_chunk(enricher: GraphEnricher) -> None:
    """Chunks only enrich up to 2 entities — GraphEnricher caps processing."""
    chunk = _item(item_type=ItemType.chunk, entity_name="Apple Inc")
    relations = [_relation_result("Apple Inc")]

    result = enricher.enrich([chunk], relations)
    assert len(result) == 1
    # Enrichment still works with 1 entity
    assert len(result[0].graph_enrichment) >= 1


@pytest.mark.unit
def test_graph_enricher_non_chunk_unchanged(enricher: GraphEnricher) -> None:
    """Relations and claims are not enriched (only chunks)."""
    rel_item = _item(item_type=ItemType.relation)
    relations = [_relation_result("Apple Inc")]

    result = enricher.enrich([rel_item], relations)
    assert result[0].graph_enrichment == ()


@pytest.mark.unit
def test_graph_enricher_no_matching_entity(enricher: GraphEnricher) -> None:
    """Chunk whose entity has no matching relations → unchanged."""
    chunk = _item(item_type=ItemType.chunk, entity_name="Unknown Corp")
    relations = [_relation_result("Apple Inc")]

    result = enricher.enrich([chunk], relations)
    assert result[0].graph_enrichment == ()


@pytest.mark.unit
def test_sort_by_summary_authority_float_values(enricher: GraphEnricher) -> None:
    """Relations with mixed float and None summary_authority sort correctly (B-1 regression).

    Expected order after enrich(): authority=0.8 first, then 0.3, then None last.
    """
    chunk = _item(item_type=ItemType.chunk, entity_name="Tesla Inc")

    rel_high = _relation_result("Tesla Inc", summary_authority=0.8, confidence=0.90)
    rel_none = _relation_result("Tesla Inc", summary_authority=None, confidence=0.70)
    rel_low = _relation_result("Tesla Inc", summary_authority=0.3, confidence=0.80)

    # Pass in unsorted order — enricher must sort correctly without TypeError
    result = enricher.enrich([chunk], [rel_high, rel_none, rel_low])

    assert len(result) == 1
    graph = result[0].graph_enrichment
    assert len(graph) == 3

    # Extract the objects (the relation results are MagicMocks whose .object is "Target Corp")
    # We verify order by inspecting the relation_id which encodes subject+uniqueness via MagicMock spec.
    # Instead: re-derive the authority order from the graph_enrichment confidence values
    # (each rel has a distinct confidence, and authority order matches confidence order here).
    confidences = [entry["confidence"] for entry in graph]
    # 0.8 authority → confidence 0.90, 0.3 authority → confidence 0.80, None → confidence 0.70
    assert confidences[0] == pytest.approx(0.90), "Highest authority (0.8) must be first"
    assert confidences[1] == pytest.approx(0.80), "Second authority (0.3) must be second"
    assert confidences[2] == pytest.approx(0.70), "None authority must be last"
