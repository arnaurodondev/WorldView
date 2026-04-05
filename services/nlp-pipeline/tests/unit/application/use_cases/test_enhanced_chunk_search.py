"""Unit tests for EnhancedChunkSearchUseCase (PLAN-0015-B T-B-3-01)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    EnhancedChunkSearchUseCase,
    _embed_cache_key,
)

_CHUNK_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")
_DOC_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000011")
_SECTION_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000012")
_ENTITY_ID = uuid.UUID("018f1e2a-0000-7000-8000-000000000013")

_DUMMY_VEC = [0.1] * 1024


def _make_raw_result(
    chunk_id: uuid.UUID = _CHUNK_ID,
    doc_id: uuid.UUID = _DOC_ID,
    section_id: uuid.UUID = _SECTION_ID,
    score: float = 0.87,
    heading_path: str | None = "Item 2 > Revenue",
    section_type: str | None = "financial",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "section_id": section_id,
        "granularity": "chunk",
        "text": heading_path or "",
        "score": score,
        "section_type": section_type,
        "heading_path": heading_path,
    }


def _make_use_case(
    *,
    ann_results: list | None = None,
    total_searched: int = 1000,
    entity_mentions: list | None = None,
    canon_map: dict | None = None,
    meta_map: dict | None = None,
    valkey_cached_vec: str | None = None,
    embed_result: list[float] | None = None,
) -> EnhancedChunkSearchUseCase:
    ann_repo = AsyncMock()
    ann_repo.ann_search = AsyncMock(
        return_value=([_make_raw_result()] if ann_results is None else ann_results, total_searched)
    )
    ann_repo.fetch_entity_mentions = AsyncMock(return_value=entity_mentions or [])

    source_meta_repo = AsyncMock()
    source_meta_repo.batch_get = AsyncMock(return_value=meta_map or {})

    canon_repo = AsyncMock()
    canon_repo.batch_get = AsyncMock(return_value=canon_map or {})

    valkey = AsyncMock()
    valkey.get = AsyncMock(return_value=valkey_cached_vec)
    valkey.set = AsyncMock()

    emb_client = MagicMock()
    emb_client.embed = AsyncMock(return_value=embed_result or _DUMMY_VEC)

    return EnhancedChunkSearchUseCase(
        chunk_ann_repo=ann_repo,
        source_metadata_repo=source_meta_repo,
        canonical_entity_repo=canon_repo,
        valkey=valkey,
        embedding_client=emb_client,
    )


@pytest.mark.unit
class TestEnhancedChunkSearchUseCase:
    @pytest.mark.asyncio
    async def test_chunk_search_returns_enriched_results(self) -> None:
        """Vector search returns entities + source_metadata correctly assembled."""
        from nlp_pipeline.domain.models import DocumentSourceMetadata

        doc_meta = DocumentSourceMetadata(
            doc_id=_DOC_ID,
            title="Apple Q3 2024 10-Q",
            url="https://example.com/10q",
            published_at=None,
            source_name="SEC EDGAR",
            source_type="sec_10q",
            word_count=5000,
            created_at=__import__("datetime").datetime(2024, 8, 1, tzinfo=__import__("datetime").timezone.utc),
        )
        entity_mention = {
            "chunk_id": _CHUNK_ID,
            "resolved_entity_id": _ENTITY_ID,
            "resolution_confidence": 0.96,
        }
        canon_data = {
            _ENTITY_ID: {"canonical_name": "Apple Inc.", "entity_type": "organization"},
        }

        uc = _make_use_case(
            entity_mentions=[entity_mention],
            canon_map=canon_data,
            meta_map={_DOC_ID: doc_meta},
        )
        results, total, model = await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
            include_entities=True,
        )

        assert len(results) == 1
        r = results[0]
        assert r.chunk_id == _CHUNK_ID
        assert r.doc_id == _DOC_ID
        assert r.score == pytest.approx(0.87)
        assert r.source_metadata.title == "Apple Q3 2024 10-Q"
        assert r.source_metadata.source_type == "sec_10q"
        assert len(r.entities) == 1
        e = r.entities[0]
        assert e.entity_id == _ENTITY_ID
        assert e.canonical_name == "Apple Inc."
        assert e.entity_type == "organization"
        assert e.confidence == pytest.approx(0.96)
        assert total == 1000
        assert model == "nomic-embed-text"

    @pytest.mark.asyncio
    async def test_chunk_search_date_filter_passed_to_repo(self) -> None:
        """date_from and date_to are forwarded to the ANN repository."""
        from datetime import date

        uc = _make_use_case()
        date_from = date(2024, 1, 1)
        date_to = date(2024, 12, 31)

        await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
            date_from=date_from,
            date_to=date_to,
        )

        uc._ann.ann_search.assert_called_once()  # type: ignore[attr-defined]
        call_kwargs = uc._ann.ann_search.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["date_from"] == date_from
        assert call_kwargs["date_to"] == date_to

    @pytest.mark.asyncio
    async def test_chunk_search_pre_embedded_query_skips_embed(self) -> None:
        """When query_embedding is provided, embedding client and cache are NOT called."""
        uc = _make_use_case()

        await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
        )

        uc._emb.embed.assert_not_called()  # type: ignore[attr-defined]
        uc._valkey.get.assert_not_called()  # type: ignore[attr-defined]
        uc._valkey.set.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_chunk_search_embedding_cached(self) -> None:
        """Second call with same query_text returns from Valkey — embed NOT called."""
        cached_vec = json.dumps(_DUMMY_VEC)
        uc = _make_use_case(valkey_cached_vec=cached_vec)

        await uc.execute(
            query_text="apple q3 revenue",
            query_embedding=None,
        )

        uc._emb.embed.assert_not_called()  # type: ignore[attr-defined]
        uc._valkey.get.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_chunk_search_embed_called_on_cache_miss(self) -> None:
        """On cache miss, embedding client is called and result is cached."""
        uc = _make_use_case(valkey_cached_vec=None)

        await uc.execute(
            query_text="apple q3 revenue",
            query_embedding=None,
        )

        uc._emb.embed.assert_called_once_with("apple q3 revenue")  # type: ignore[attr-defined]
        uc._valkey.set.assert_called_once()  # type: ignore[attr-defined]
        set_args = uc._valkey.set.call_args  # type: ignore[attr-defined]
        assert set_args.kwargs.get("ex") == 3600 or set_args.args[2] == 3600

    @pytest.mark.asyncio
    async def test_chunk_search_empty_results(self) -> None:
        """No ANN hits → empty result list returned without entity/meta lookups."""
        uc = _make_use_case(ann_results=[], total_searched=500)

        results, total, _ = await uc.execute(
            query_text=None,
            query_embedding=_DUMMY_VEC,
        )

        assert results == []
        assert total == 500
        uc._meta.batch_get.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.unit
class TestEmbedCacheKey:
    def test_cache_key_format(self) -> None:
        key = _embed_cache_key("hello world")
        assert key.startswith("s6:v1:emb:")
        assert len(key) == len("s6:v1:emb:") + 16

    def test_same_text_same_key(self) -> None:
        assert _embed_cache_key("apple") == _embed_cache_key("apple")

    def test_different_text_different_key(self) -> None:
        assert _embed_cache_key("apple") != _embed_cache_key("google")
