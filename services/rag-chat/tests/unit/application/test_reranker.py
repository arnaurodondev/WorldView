"""Unit tests for BGEReranker (T-F-2-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.application.pipeline.reranker import BGEReranker
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType


def _item(item_id: str, score: float = 0.70, trust: float = 0.80) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=ItemType.chunk,
        text=f"Text for {item_id}",
        score=score,
        trust_weight=trust,
        citation_meta=CitationMeta(title=None, url=None, source_name=None, published_at=None, entity_name=None),
    )


def _make_reranker(http_client: MagicMock | None = None) -> BGEReranker:
    return BGEReranker(
        ollama_base_url="http://localhost:11434",
        http_client=http_client,
    )


@pytest.mark.unit
async def test_reranker_returns_top_12() -> None:
    """30 items in -> max 12 out."""
    items = [_item(f"item-{i}") for i in range(30)]

    # Mock Ollama response: all 30 items with descending scores
    results = [{"index": i, "relevance_score": 1.0 - i * 0.03} for i in range(30)]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": results}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = _make_reranker(mock_client)
    result = await reranker.rerank("What is Apple's revenue?", items)
    assert len(result) == 12


@pytest.mark.unit
async def test_reranker_falls_back_on_timeout() -> None:
    """Ollama timeout -> top 12 by fusion_score returned."""
    items = [_item(f"item-{i}", score=float(i) / 30) for i in range(20)]

    mock_client = AsyncMock()
    mock_client.post.side_effect = TimeoutError("connection timeout")

    reranker = _make_reranker(mock_client)
    result = await reranker.rerank("query", items)

    assert len(result) == 12
    # Should be sorted by fusion_score desc
    scores = [r.fusion_score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
async def test_reranker_empty_input() -> None:
    """0 items -> empty list."""
    reranker = _make_reranker(AsyncMock())
    result = await reranker.rerank("query", [])
    assert result == []
