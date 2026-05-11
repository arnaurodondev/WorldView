"""Integration tests for chunk text storage and retrieval (Option B — MinIO pattern).

Uses an in-memory ObjectStorage implementation to test the full
write → store key → search → fetch text flow without requiring a running MinIO
instance.  The in-memory store exercises exactly the same port/adapter boundary
as the real MinIOChunkTextStore.

Test scenarios:
  - T-I-CT-01: Block 7 uploads chunk texts; chunks returned with text_key set
  - T-I-CT-02: Search use case fetches text for results that have chunk_text_key
  - T-I-CT-03: Search use case gracefully returns heading_path when key is absent
  - T-I-CT-04: Valkey caching — second fetch skips get_batch call
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.embeddings import run_embeddings_block
from nlp_pipeline.application.use_cases.enhanced_chunk_search import (
    EnhancedChunkSearchUseCase,
)
from nlp_pipeline.domain.models import Section
from nlp_pipeline.infrastructure.storage.chunk_text_store import MinIOChunkTextStore

if TYPE_CHECKING:
    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort

# ── In-memory ObjectStorage for tests ────────────────────────────────────────


class _InMemoryObjectStorage:
    """Minimal in-memory implementation of the ObjectStorage interface for tests."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def put_bytes(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._data[f"{bucket}/{key}"] = data

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        full_key = f"{bucket}/{key}"
        if full_key not in self._data:
            raise KeyError(f"Object not found: {key!r}")
        return self._data[full_key]

    async def delete(self, bucket: str, key: str) -> None:
        self._data.pop(f"{bucket}/{key}", None)

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        prefix_full = f"{bucket}/{prefix}"
        return [k[len(bucket) + 1 :] for k in self._data if k.startswith(prefix_full)]

    async def exists(self, bucket: str, key: str) -> bool:
        return f"{bucket}/{key}" in self._data

    async def delete_prefix(self, bucket: str, prefix: str) -> int:
        to_del = [k for k in self._data if k.startswith(f"{bucket}/{prefix}")]
        for k in to_del:
            del self._data[k]
        return len(to_del)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_section(text: str) -> Section:
    doc_id = uuid.uuid4()
    return Section(
        section_id=uuid.uuid4(),
        doc_id=doc_id,
        section_index=0,
        char_start=0,
        char_end=len(text),
        text=text,
        section_type="body",
    )


def _make_embedding_client() -> MagicMock:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

    output = EmbeddingOutput(embedding=[0.1] * 32, model_id="bge", dimension=32)
    client = MagicMock()
    client.embed = AsyncMock(return_value=[output])
    return client


def _build_search_use_case(
    store: ChunkTextStorePort,
    ann_results: list[dict[str, Any]],
    valkey: Any | None = None,
) -> EnhancedChunkSearchUseCase:
    ann_repo = AsyncMock()
    ann_repo.ann_search = AsyncMock(return_value=(ann_results, len(ann_results)))
    ann_repo.fetch_entity_mentions = AsyncMock(return_value=[])

    meta_repo = AsyncMock()
    meta_repo.batch_get = AsyncMock(return_value={})

    canon_repo = AsyncMock()
    canon_repo.batch_get = AsyncMock(return_value={})

    return EnhancedChunkSearchUseCase(
        chunk_ann_repo=ann_repo,
        source_metadata_repo=meta_repo,
        canonical_entity_repo=canon_repo,
        valkey=valkey,
        embedding_client=None,
        chunk_text_store=store,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestChunkTextBlockIntegration:
    @pytest.mark.asyncio
    async def test_t_i_ct_01_block7_uploads_chunk_texts(self) -> None:
        """T-I-CT-01: run_embeddings_block uploads chunk text and sets text_key."""
        obj_storage = _InMemoryObjectStorage()
        store = MinIOChunkTextStore(obj_storage, "worldview")
        client = _make_embedding_client()

        text = (
            "Apple Inc. reported record quarterly revenue. "
            "The technology giant cited strong iPhone demand. "
            "CEO Tim Cook described conditions as exceptional."
        )
        sections = [_make_section(text)]

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
            chunk_text_store=store,
        )

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.text_key is not None, "text_key must be set after upload"
            assert chunk.text_key.startswith("nlp-pipeline/chunk-text/")
            assert chunk.text_key.endswith("/body/v1.txt")

            # Verify text is actually readable back from storage
            stored = await obj_storage.get_bytes("worldview", chunk.text_key)
            assert stored.decode("utf-8") == chunk.text

    @pytest.mark.asyncio
    async def test_t_i_ct_01_text_key_contains_chunk_and_doc_ids(self) -> None:
        """T-I-CT-01 (b): text_key encodes doc_id and chunk_id correctly."""
        obj_storage = _InMemoryObjectStorage()
        store = MinIOChunkTextStore(obj_storage, "worldview")
        client = _make_embedding_client()

        sections = [_make_section("Revenue rose. Costs fell. Margin improved.")]

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,
            chunk_text_store=store,
        )

        for chunk in chunks:
            assert str(chunk.chunk_id) in chunk.text_key  # type: ignore[operator]
            assert str(chunk.doc_id) in chunk.text_key  # type: ignore[operator]


@pytest.mark.integration
class TestChunkTextSearchIntegration:
    @pytest.mark.asyncio
    async def test_t_i_ct_02_search_returns_full_text(self) -> None:
        """T-I-CT-02: EnhancedChunkSearchUseCase populates text from MinIO."""
        obj_storage = _InMemoryObjectStorage()
        store = MinIOChunkTextStore(obj_storage, "worldview")

        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        section_id = uuid.uuid4()
        expected_text = "Apple Q3 revenue exceeded analyst expectations by 12%."

        # Pre-upload the chunk text (simulates what Block 7 does)
        text_key = await store.put(chunk_id, doc_id, expected_text)

        ann_results = [
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "section_id": section_id,
                "granularity": "chunk",
                "text": "",  # empty placeholder — should be replaced by MinIO fetch
                "score": 0.91,
                "section_type": "financial",
                "heading_path": None,
                "chunk_text_key": text_key,
            }
        ]

        uc = _build_search_use_case(store, ann_results)
        results, _, _ = await uc.execute(query_text=None, query_embedding=[0.0] * 32)

        assert len(results) == 1
        assert results[0].text == expected_text

    @pytest.mark.asyncio
    async def test_t_i_ct_03_search_falls_back_when_key_absent(self) -> None:
        """T-I-CT-03: No chunk_text_key → text falls back to heading_path."""
        obj_storage = _InMemoryObjectStorage()
        store = MinIOChunkTextStore(obj_storage, "worldview")

        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        section_id = uuid.uuid4()

        ann_results = [
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "section_id": section_id,
                "granularity": "chunk",
                "text": "Item 1A > Risk Factors",
                "score": 0.75,
                "section_type": "sec_section",
                "heading_path": "Item 1A > Risk Factors",
                "chunk_text_key": None,
            }
        ]

        uc = _build_search_use_case(store, ann_results)
        results, _, _ = await uc.execute(query_text=None, query_embedding=[0.0] * 32)

        assert results[0].text == "Item 1A > Risk Factors"

    @pytest.mark.asyncio
    async def test_t_i_ct_04_valkey_cache_avoids_second_minio_fetch(self) -> None:
        """T-I-CT-04: Text cached in Valkey — second call skips get_batch."""
        obj_storage = _InMemoryObjectStorage()
        store = MinIOChunkTextStore(obj_storage, "worldview")

        # Wrap store.get_batch to count calls
        original_get_batch = store.get_batch
        call_count = 0

        async def _counting_get_batch(key_map: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return await original_get_batch(key_map)

        store.get_batch = _counting_get_batch  # type: ignore[method-assign]

        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        section_id = uuid.uuid4()
        text = "Markets rallied on Fed comments."
        text_key = await store.put(chunk_id, doc_id, text)

        ann_results = [
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "section_id": section_id,
                "granularity": "chunk",
                "text": "",
                "score": 0.88,
                "section_type": "body",
                "heading_path": None,
                "chunk_text_key": text_key,
            }
        ]

        # Use fakeredis for Valkey
        import fakeredis.aioredis as fakeredis

        valkey = fakeredis.FakeRedis()

        uc = _build_search_use_case(store, ann_results, valkey=valkey)

        # First call — MinIO fetch + cache write
        results1, _, _ = await uc.execute(query_text=None, query_embedding=[0.0] * 32)
        assert results1[0].text == text
        assert call_count == 1

        # Second call — served from Valkey, no MinIO fetch
        results2, _, _ = await uc.execute(query_text=None, query_embedding=[0.0] * 32)
        assert results2[0].text == text
        assert call_count == 1  # get_batch NOT called again
