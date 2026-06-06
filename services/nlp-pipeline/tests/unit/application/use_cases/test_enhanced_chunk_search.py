"""Unit tests for EnhancedChunkSearchUseCase (PLAN-0015-B T-B-3-01)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    EnhancedChunkSearchUseCase,
    _chunk_text_cache_key,
    _embed_cache_key,
)

pytestmark = pytest.mark.unit

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
    chunk_text_key: str | None = None,
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
        "chunk_text_key": chunk_text_key,
    }


def _make_chunk_text_store(
    texts: dict[uuid.UUID, str] | None = None,
    fail: bool = False,
) -> ChunkTextStorePort:
    store = MagicMock(spec=ChunkTextStorePort)
    if fail:
        store.get_batch = AsyncMock(side_effect=Exception("MinIO down"))
    else:

        async def _get_batch(key_map: dict) -> dict:
            return {cid: (texts or {}).get(cid, "") for cid in key_map}

        store.get_batch = AsyncMock(side_effect=_get_batch)
    return store


def _make_use_case(
    *,
    ann_results: list | None = None,
    total_searched: int = 1000,
    entity_mentions: list | None = None,
    canon_map: dict | None = None,
    meta_map: dict | None = None,
    valkey_cached_vec: str | None = None,
    embed_result: list[float] | None = None,
    chunk_text_store: ChunkTextStorePort | None = None,
    valkey_cached_text: bytes | None = None,
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

    # Return embed cache miss by default; allow text cache to be set separately
    def _valkey_get(key: str) -> object:
        return valkey_cached_vec if key.startswith("s6:v1:emb:") else valkey_cached_text

    valkey.get = AsyncMock(side_effect=_valkey_get)
    valkey.set = AsyncMock()

    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

    _embed_output = [
        EmbeddingOutput(embedding=embed_result or _DUMMY_VEC, model_id="BAAI/bge-large-en-v1.5", dimension=1024)
    ]
    emb_client = MagicMock()
    emb_client.embed = AsyncMock(return_value=_embed_output)

    return EnhancedChunkSearchUseCase(
        chunk_ann_repo=ann_repo,
        source_metadata_repo=source_meta_repo,
        canonical_entity_repo=canon_repo,
        valkey=valkey,
        embedding_client=emb_client,
        chunk_text_store=chunk_text_store,
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

        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

        uc._emb.embed.assert_called_once_with(  # type: ignore[attr-defined]
            [EmbeddingInput(text="apple q3 revenue", model_id="BAAI/bge-large-en-v1.5")]
        )
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


@pytest.mark.unit
class TestChunkTextCacheKey:
    def test_key_format(self) -> None:
        cid = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")
        key = _chunk_text_cache_key(cid)
        assert key == f"nlp:v1:chunk_text:{cid}"


@pytest.mark.unit
class TestEnhancedChunkSearchTextFetch:
    """Tests for the MinIO chunk text fetch path."""

    @pytest.mark.asyncio
    async def test_text_populated_from_minio_when_key_present(self) -> None:
        """When chunk_text_key is in the result, text comes from the store."""
        text_key = f"nlp-pipeline/chunk-text/{_DOC_ID}/{_CHUNK_ID}/body/v1.txt"
        raw = [_make_raw_result(chunk_text_key=text_key)]

        store = _make_chunk_text_store(texts={_CHUNK_ID: "Apple reported strong Q3 earnings."})
        uc = _make_use_case(ann_results=raw, chunk_text_store=store)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert len(results) == 1
        assert results[0].text == "Apple reported strong Q3 earnings."

    @pytest.mark.asyncio
    async def test_text_falls_back_to_heading_path_when_no_key(self) -> None:
        """When chunk_text_key is None, text falls back to heading_path."""
        raw = [_make_raw_result(chunk_text_key=None, heading_path="Item 1A > Risk Factors")]

        store = _make_chunk_text_store()
        uc = _make_use_case(ann_results=raw, chunk_text_store=store)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert results[0].text == "Item 1A > Risk Factors"
        # key_map is empty (no chunk_text_key) → early return, get_batch never called
        store.get_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_text_served_from_valkey_cache(self) -> None:
        """Cached chunk text is returned without calling get_batch."""
        text_key = f"nlp-pipeline/chunk-text/{_DOC_ID}/{_CHUNK_ID}/body/v1.txt"
        raw = [_make_raw_result(chunk_text_key=text_key)]

        store = MagicMock(spec=ChunkTextStorePort)
        store.get_batch = AsyncMock(return_value={})

        cached_text = b"Cached: Apple Q3 beat expectations."
        uc = _make_use_case(ann_results=raw, chunk_text_store=store, valkey_cached_text=cached_text)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert results[0].text == "Cached: Apple Q3 beat expectations."
        # all chunks resolved from Valkey → uncached is empty → get_batch never called
        store.get_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_failure_falls_back_gracefully(self) -> None:
        """get_batch failure must not raise; text falls back to heading_path."""
        text_key = f"nlp-pipeline/chunk-text/{_DOC_ID}/{_CHUNK_ID}/body/v1.txt"
        raw = [_make_raw_result(chunk_text_key=text_key, heading_path="Fallback heading")]

        store = _make_chunk_text_store(fail=True)
        uc = _make_use_case(ann_results=raw, chunk_text_store=store)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert results[0].text == "Fallback heading"  # graceful fallback

    @pytest.mark.asyncio
    async def test_no_store_leaves_text_as_heading_path(self) -> None:
        """When chunk_text_store is None, text is heading_path (original behaviour)."""
        raw = [_make_raw_result(chunk_text_key="some/key", heading_path="My Heading")]
        uc = _make_use_case(ann_results=raw, chunk_text_store=None)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert results[0].text == "My Heading"

    @pytest.mark.asyncio
    async def test_section_granularity_skips_minio(self) -> None:
        """Section results (granularity='section') are never fetched from MinIO."""
        raw = [
            {
                "chunk_id": _CHUNK_ID,
                "doc_id": _DOC_ID,
                "section_id": _SECTION_ID,
                "granularity": "section",
                "text": "Section heading",
                "score": 0.80,
                "section_type": "body",
                "heading_path": "Section heading",
                "chunk_text_key": None,
            }
        ]

        store = MagicMock(spec=ChunkTextStorePort)
        store.get_batch = AsyncMock(return_value={})
        uc = _make_use_case(ann_results=raw, chunk_text_store=store)

        results, _, _ = await uc.execute(query_text=None, query_embedding=_DUMMY_VEC)

        assert results[0].text == "Section heading"
        # sections have no chunk_text_key → key_map is empty → get_batch never called
        store.get_batch.assert_not_awaited()
