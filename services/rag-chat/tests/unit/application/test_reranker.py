"""Unit tests for BGEReranker and CohereReranker (T-F-2-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.application.pipeline.reranker import BGEReranker, CohereReranker
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


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


# ── CohereReranker tests ───────────────────────────────────────────────────────


def _make_cohere_reranker(http_client: MagicMock | None = None) -> CohereReranker:
    return CohereReranker(api_key="test-cohere-key", http_client=http_client)


@pytest.mark.unit
async def test_cohere_reranker_returns_top_k() -> None:
    """Cohere returns ranked results → items reordered correctly."""
    items = [_item(f"item-{i}") for i in range(5)]

    # Cohere returns items in reverse order (item-4 is best)
    results = [{"index": 4 - i, "relevance_score": (i + 1) * 0.2} for i in range(5)]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": results}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = _make_cohere_reranker(mock_client)
    result = await reranker.rerank("Apple revenue?", items)

    # Top item should be item-4 (highest relevance_score 1.0 in mock)
    assert result[0].item_id == "item-0"  # index=4 mapped to item at sorted position
    mock_client.post.assert_awaited_once()


@pytest.mark.unit
async def test_cohere_reranker_posts_to_cohere_url() -> None:
    """Verify request is sent to Cohere v2 endpoint with auth header."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"index": 0, "relevance_score": 0.9}]}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = CohereReranker(api_key="test-key-123", http_client=mock_client)
    await reranker.rerank("What is NVDA?", [_item("x")])

    call_kwargs = mock_client.post.call_args.kwargs
    assert "cohere.com" in mock_client.post.call_args[0][0]
    assert "Bearer test-key-123" in call_kwargs["headers"]["Authorization"]


@pytest.mark.unit
async def test_cohere_reranker_falls_back_on_error() -> None:
    """Cohere API error → top-12 by fusion_score returned."""
    items = [_item(f"item-{i}", score=float(i) / 10) for i in range(20)]

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("connection refused")

    reranker = _make_cohere_reranker(mock_client)
    result = await reranker.rerank("query", items)

    assert len(result) == 12
    scores = [r.fusion_score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
async def test_cohere_reranker_empty_input() -> None:
    """0 items → empty list without calling the API."""
    mock_client = AsyncMock()
    reranker = _make_cohere_reranker(mock_client)
    result = await reranker.rerank("query", [])
    assert result == []
    mock_client.post.assert_not_awaited()


# ── DeepInfraReranker tests ───────────────────────────────────────────────────


def _make_deepinfra_reranker(http_client: MagicMock | None = None) -> DeepInfraReranker:
    from rag_chat.application.pipeline.reranker import DeepInfraReranker

    return DeepInfraReranker(api_key="test-deepinfra-key", http_client=http_client)


@pytest.mark.unit
async def test_deepinfra_reranker_happy_path_returns_top_k() -> None:
    """Successful DeepInfra response → items reordered by cross-encoder score, max _TOP_K returned.

    The adapter pre-sorts items by fusion_score DESC before sending to the API, then
    applies the returned scores to that pre-sorted head. Items created with score=i/10
    (item-0 lowest, item-4 highest) are pre-sorted as [item-4, item-3, item-2, item-1, item-0].
    Scores [0.1, 0.2, 0.3, 0.4, 0.9] map to: item-4→0.1, item-3→0.2, ..., item-0→0.9.
    So the reranked order is: item-0 (0.9) > item-1 (0.4) > item-2 (0.3) > item-3 (0.2) > item-4 (0.1).
    """
    from rag_chat.application.pipeline.reranker import DeepInfraReranker

    items = [_item(f"item-{i}", score=float(i) / 10) for i in range(5)]
    # Scores applied to the fusion_score-sorted head [item-4, item-3, item-2, item-1, item-0]
    # item-0 ends up first because it gets score=0.9 (the last element of scores)
    scores = [0.1, 0.2, 0.3, 0.4, 0.9]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"scores": scores}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = DeepInfraReranker(api_key="test-key", http_client=mock_client)
    result = await reranker.rerank("What is Apple's revenue?", items)

    # Should return at most _TOP_K=12 items
    assert len(result) <= 12
    assert len(result) == 5  # fewer than TOP_K so all returned
    # item-0 gets score=0.9 (highest) because it lands last in the pre-sorted head
    assert result[0].item_id == "item-0"
    mock_client.post.assert_awaited_once()


@pytest.mark.unit
async def test_deepinfra_reranker_posts_to_correct_url() -> None:
    """Request is POSTed to the DeepInfra inference endpoint with Bearer auth."""
    from rag_chat.application.pipeline.reranker import (
        _DEEPINFRA_DEFAULT_MODEL,
        _DEEPINFRA_RERANK_BASE,
        DeepInfraReranker,
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"scores": [0.9]}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = DeepInfraReranker(api_key="my-secret-key", http_client=mock_client)
    await reranker.rerank("query", [_item("x")])

    call_args = mock_client.post.call_args
    url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert _DEEPINFRA_RERANK_BASE in url
    assert _DEEPINFRA_DEFAULT_MODEL in url
    headers = call_args.kwargs["headers"]
    assert "Bearer my-secret-key" in headers["Authorization"]


@pytest.mark.unit
async def test_deepinfra_reranker_falls_back_on_api_error() -> None:
    """DeepInfra API raises an exception → fallback to top-12 by fusion_score."""
    items = [_item(f"item-{i}", score=float(i) / 10) for i in range(20)]

    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("connection refused")

    reranker = _make_deepinfra_reranker(mock_client)
    result = await reranker.rerank("query", items)

    assert len(result) == 12
    scores = [r.fusion_score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
async def test_deepinfra_reranker_falls_back_on_5xx() -> None:
    """DeepInfra 5xx response → raise_for_status fires → fallback to fusion_score sort."""
    import httpx

    items = [_item(f"item-{i}", score=float(i) / 10) for i in range(15)]

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="503 Service Unavailable",
        request=MagicMock(),
        response=MagicMock(status_code=503),
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = _make_deepinfra_reranker(mock_client)
    result = await reranker.rerank("query", items)

    # Graceful fallback: sorted by fusion_score, at most 12
    assert len(result) == 12
    scores = [r.fusion_score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
async def test_deepinfra_reranker_empty_input() -> None:
    """0 items → empty list without calling the API."""
    mock_client = AsyncMock()
    reranker = _make_deepinfra_reranker(mock_client)
    result = await reranker.rerank("query", [])
    assert result == []
    mock_client.post.assert_not_awaited()


@pytest.mark.unit
async def test_deepinfra_reranker_score_length_mismatch_falls_back() -> None:
    """API returns wrong number of scores → ValueError → fallback to fusion_score sort."""
    items = [_item(f"item-{i}") for i in range(5)]
    # Return only 3 scores for 5 documents — a server-side bug
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"scores": [0.9, 0.8, 0.7]}  # missing 2 scores
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    reranker = _make_deepinfra_reranker(mock_client)
    result = await reranker.rerank("query", items)

    # Score mismatch triggers ValueError → caught → fallback to fusion_score
    assert len(result) <= 12
    assert len(result) > 0  # should still return something via fallback


@pytest.mark.unit
async def test_deepinfra_reranker_max_docs_cap_limits_payload() -> None:
    """Input exceeds max_docs → only top-N by fusion_score are sent to the API."""
    from rag_chat.application.pipeline.reranker import DeepInfraReranker

    # Create 30 items but set max_docs=5 — only 5 should be sent to the API
    items = [_item(f"item-{i}", score=float(i) / 30) for i in range(30)]
    captured_payloads: list[dict] = []

    async def _capture_post(url: str, **kwargs: object) -> MagicMock:
        captured_payloads.append(kwargs.get("json", {}))  # type: ignore[arg-type]
        mock_resp = MagicMock()
        # Return 5 scores (matching the 5-doc cap)
        mock_resp.json.return_value = {"scores": [0.5, 0.6, 0.7, 0.8, 0.9]}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    mock_client = AsyncMock()
    mock_client.post = _capture_post

    reranker = DeepInfraReranker(api_key="key", http_client=mock_client, max_docs=5)
    await reranker.rerank("query", items)

    assert len(captured_payloads) == 1
    assert len(captured_payloads[0]["documents"]) == 5
