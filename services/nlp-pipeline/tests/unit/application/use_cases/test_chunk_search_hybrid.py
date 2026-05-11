"""Hybrid-branch unit tests for EnhancedChunkSearchUseCase (PLAN-0063 W5-3 T-02).

Covers the dispatch on `search_type` (ann / lexical / hybrid), the short-query
fallback, RRF dedup, top_k truncation, exception propagation, and the L9
adaptive-boost contract via a spy on `reciprocal_rank_fuse`.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    EnhancedChunkSearchUseCase,
)

pytestmark = pytest.mark.unit

_DUMMY_VEC = [0.1] * 1024


def _raw(chunk_id: uuid.UUID, score: float = 0.8) -> dict:
    """Build a minimal repo row that satisfies _enrich_raw_results."""
    return {
        "chunk_id": chunk_id,
        "doc_id": uuid.uuid4(),
        "section_id": uuid.uuid4(),
        "granularity": "chunk",
        "text": "irrelevant",
        "score": score,
        "section_type": "body",
        "heading_path": "Title",
        "chunk_text_key": None,
    }


def _make_use_case(
    *,
    ann_results: list[dict] | None = None,
    lex_rows: list[dict] | None = None,
    lex_total: int = 7,
    lexical_boost: float = 1.5,
) -> tuple[EnhancedChunkSearchUseCase, AsyncMock]:
    """Build a use case with both ann_search and lexical_search mocked."""
    ann_repo = AsyncMock()
    ann_repo.ann_search = AsyncMock(return_value=(ann_results or [], 11))
    ann_repo.lexical_search = AsyncMock(return_value=(lex_rows or [], lex_total))
    ann_repo.fetch_entity_mentions = AsyncMock(return_value=[])

    source_meta_repo = AsyncMock()
    source_meta_repo.batch_get = AsyncMock(return_value={})

    canon_repo = AsyncMock()
    canon_repo.batch_get = AsyncMock(return_value={})

    valkey = AsyncMock()
    valkey.get = AsyncMock(return_value=None)
    valkey.set = AsyncMock()

    emb_client = MagicMock()
    emb_client.embed = AsyncMock(return_value=_DUMMY_VEC)

    uc = EnhancedChunkSearchUseCase(
        chunk_ann_repo=ann_repo,
        source_metadata_repo=source_meta_repo,
        canonical_entity_repo=canon_repo,
        valkey=valkey,
        embedding_client=emb_client,
        chunk_text_store=None,
        lexical_boost=lexical_boost,
    )
    return uc, ann_repo


@pytest.mark.asyncio
async def test_search_type_ann_skips_lexical_repo_call() -> None:
    """ANN dispatch does not touch the lexical_search repo method."""
    uc, repo = _make_use_case(ann_results=[_raw(uuid.uuid4())])
    await uc.execute(
        query_text=None,
        query_embedding=_DUMMY_VEC,
        search_type="ann",
    )
    repo.ann_search.assert_awaited_once()
    repo.lexical_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_type_lexical_skips_ann_repo_call() -> None:
    """Lexical dispatch does not touch the ann_search repo method."""
    uc, repo = _make_use_case(lex_rows=[_raw(uuid.uuid4())])
    await uc.execute(
        query_text="apple revenue growth Q3",
        query_embedding=None,
        search_type="lexical",
    )
    repo.ann_search.assert_not_awaited()
    repo.lexical_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_type_hybrid_calls_both_repos() -> None:
    """Hybrid dispatch fires ann_search AND lexical_search."""
    uc, repo = _make_use_case(
        ann_results=[_raw(uuid.uuid4())],
        lex_rows=[_raw(uuid.uuid4())],
    )
    await uc.execute(
        query_text="apple revenue growth Q3",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    repo.ann_search.assert_awaited_once()
    repo.lexical_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_hybrid_short_query_falls_back_to_ann_only() -> None:
    """A 1-token query can't drive a useful FTS — fall back to pure ANN."""
    uc, repo = _make_use_case(ann_results=[_raw(uuid.uuid4())])
    await uc.execute(
        query_text="Apple",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    repo.ann_search.assert_awaited_once()
    repo.lexical_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_dedupes_chunk_ids_via_rrf() -> None:
    """An overlapping chunk_id appears exactly once in the fused result."""
    shared_id = uuid.uuid4()
    uc, _repo = _make_use_case(
        ann_results=[_raw(shared_id), _raw(uuid.uuid4())],
        lex_rows=[_raw(shared_id), _raw(uuid.uuid4())],
    )
    results, _total, _model = await uc.execute(
        query_text="apple revenue growth Q3",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    chunk_ids = [r.chunk_id for r in results]
    assert chunk_ids.count(shared_id) == 1


@pytest.mark.asyncio
async def test_hybrid_respects_top_k() -> None:
    """top_k caps the fused list even when both legs return that many results."""
    ann_rows = [_raw(uuid.uuid4()) for _ in range(20)]
    lex_rows = [_raw(uuid.uuid4()) for _ in range(20)]
    uc, _repo = _make_use_case(ann_results=ann_rows, lex_rows=lex_rows)
    results, _total, _model = await uc.execute(
        query_text="apple revenue growth Q3",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
        top_k=10,
    )
    assert len(results) <= 10


@pytest.mark.asyncio
async def test_hybrid_propagates_repo_exception() -> None:
    """If either leg raises, the orchestrator must see the exception."""
    uc, repo = _make_use_case(ann_results=[_raw(uuid.uuid4())])
    repo.lexical_search.side_effect = RuntimeError("FTS exploded")
    with pytest.raises(RuntimeError):
        await uc.execute(
            query_text="apple revenue growth Q3",
            query_embedding=_DUMMY_VEC,
            search_type="hybrid",
        )


@pytest.mark.asyncio
async def test_hybrid_applies_lexical_boost_for_rare_token_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """A query with rare tokens (PRD-0034) → RRF called with weighted lex leg."""
    captured: dict = {}

    real_module = "nlp_pipeline.application.use_cases.enhanced_chunk_search"

    def _spy_rrf(rankings, *, k, key, weights=None):  # type: ignore[no-untyped-def]
        captured["weights"] = weights
        # Return a deterministic order — first list first, then second.
        flat = []
        seen = set()
        for ranking in rankings:
            for item in ranking:
                ident = key(item)
                if ident in seen:
                    continue
                seen.add(ident)
                flat.append((item, 1.0))
        return flat

    monkeypatch.setattr(f"{real_module}.reciprocal_rank_fuse", _spy_rrf)

    uc, _repo = _make_use_case(
        ann_results=[_raw(uuid.uuid4())],
        lex_rows=[_raw(uuid.uuid4())],
        lexical_boost=1.5,
    )
    await uc.execute(
        query_text="What does PRD-0034 say about retrieval?",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    assert captured["weights"] == (1.0, 1.5)


@pytest.mark.asyncio
async def test_hybrid_no_boost_for_non_rare_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain English query → uniform weights (1.0, 1.0)."""
    captured: dict = {}

    real_module = "nlp_pipeline.application.use_cases.enhanced_chunk_search"

    def _spy_rrf(rankings, *, k, key, weights=None):  # type: ignore[no-untyped-def]
        captured["weights"] = weights
        return [(rankings[0][0], 1.0)] if rankings and rankings[0] else []

    monkeypatch.setattr(f"{real_module}.reciprocal_rank_fuse", _spy_rrf)

    uc, _repo = _make_use_case(
        ann_results=[_raw(uuid.uuid4())],
        lex_rows=[_raw(uuid.uuid4())],
    )
    await uc.execute(
        query_text="What is the gross margin number?",
        query_embedding=_DUMMY_VEC,
        search_type="hybrid",
    )
    assert captured["weights"] == (1.0, 1.0)


@pytest.mark.asyncio
async def test_unknown_search_type_raises_value_error() -> None:
    """Defensive: unknown literal raises before any repo call."""
    uc, _repo = _make_use_case()
    with pytest.raises(ValueError):
        await uc.execute(
            query_text="x",
            query_embedding=None,
            search_type="bogus",
        )
