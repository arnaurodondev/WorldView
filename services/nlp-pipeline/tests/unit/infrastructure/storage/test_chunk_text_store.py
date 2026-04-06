"""Unit tests for MinIOChunkTextStore."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.storage.chunk_text_store import (
    MinIOChunkTextStore,
    _build_key,
)


def _make_storage(
    put_side_effect: Exception | None = None,
    get_side_effect: Exception | None = None,
) -> MagicMock:
    storage = MagicMock()
    storage.put_bytes = AsyncMock(side_effect=put_side_effect)
    storage.get_bytes = AsyncMock(side_effect=get_side_effect)
    return storage


@pytest.mark.unit
class TestBuildKey:
    def test_key_format(self) -> None:
        doc_id = uuid.UUID("018f1e2a-0000-7000-8000-000000000001")
        chunk_id = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")
        key = _build_key(doc_id, chunk_id)
        assert key.startswith("nlp-pipeline/chunk-text/")
        assert str(doc_id) in key
        assert str(chunk_id) in key
        assert key.endswith("/body/v1.txt")

    def test_key_contains_doc_and_chunk(self) -> None:
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        key = _build_key(doc_id, chunk_id)
        assert f"{doc_id}/{chunk_id}" in key


@pytest.mark.unit
class TestMinIOChunkTextStorePut:
    @pytest.mark.asyncio
    async def test_put_uploads_utf8_bytes(self) -> None:
        storage = _make_storage()
        store = MinIOChunkTextStore(storage, "worldview")
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        await store.put(chunk_id, doc_id, "Apple reported record revenue.")

        storage.put_bytes.assert_awaited_once()
        call_args = storage.put_bytes.call_args
        assert call_args.args[0] == "worldview"  # bucket
        assert "nlp-pipeline/chunk-text" in call_args.args[1]  # key
        assert call_args.args[2] == b"Apple reported record revenue."  # data
        assert "text/plain" in call_args.kwargs.get("content_type", "")

    @pytest.mark.asyncio
    async def test_put_returns_canonical_key(self) -> None:
        storage = _make_storage()
        store = MinIOChunkTextStore(storage, "worldview")
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        key = await store.put(chunk_id, doc_id, "some text")

        assert key.startswith("nlp-pipeline/chunk-text/")
        assert key.endswith("/body/v1.txt")

    @pytest.mark.asyncio
    async def test_put_handles_unicode_text(self) -> None:
        storage = _make_storage()
        store = MinIOChunkTextStore(storage, "worldview")
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        await store.put(chunk_id, doc_id, "Résumé: €50M revenue")

        data = storage.put_bytes.call_args.args[2]
        assert data == "Résumé: €50M revenue".encode()


@pytest.mark.unit
class TestMinIOChunkTextStoreGetBatch:
    @pytest.mark.asyncio
    async def test_get_batch_returns_decoded_text(self) -> None:
        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        key = _build_key(doc_id, chunk_id)

        storage = _make_storage()
        storage.get_bytes = AsyncMock(return_value=b"Revenue grew 12% YoY.")
        store = MinIOChunkTextStore(storage, "worldview")

        result = await store.get_batch({chunk_id: key})

        assert result == {chunk_id: "Revenue grew 12% YoY."}

    @pytest.mark.asyncio
    async def test_get_batch_empty_map_returns_empty(self) -> None:
        storage = _make_storage()
        store = MinIOChunkTextStore(storage, "worldview")

        result = await store.get_batch({})

        assert result == {}
        storage.get_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_batch_skips_failed_fetches(self) -> None:
        """Individual fetch failures must not raise; the chunk is omitted."""
        chunk_ok = uuid.uuid4()
        chunk_fail = uuid.uuid4()
        doc_id = uuid.uuid4()

        key_ok = _build_key(doc_id, chunk_ok)
        key_fail = _build_key(doc_id, chunk_fail)

        call_count = 0

        async def _side_effect(bucket: str, key: str) -> bytes:
            nonlocal call_count
            call_count += 1
            if key == key_fail:
                raise OSError("connection refused")
            return b"good text"

        storage = MagicMock()
        storage.get_bytes = AsyncMock(side_effect=_side_effect)
        store = MinIOChunkTextStore(storage, "worldview")

        result = await store.get_batch({chunk_ok: key_ok, chunk_fail: key_fail})

        assert chunk_ok in result
        assert result[chunk_ok] == "good text"
        assert chunk_fail not in result  # failed fetch omitted

    @pytest.mark.asyncio
    async def test_get_batch_parallelises_requests(self) -> None:
        """All gets should be issued concurrently (gather), not sequentially."""
        chunk_ids = [uuid.uuid4() for _ in range(5)]
        doc_id = uuid.uuid4()
        key_map = {cid: _build_key(doc_id, cid) for cid in chunk_ids}

        storage = MagicMock()
        storage.get_bytes = AsyncMock(return_value=b"text")
        store = MinIOChunkTextStore(storage, "worldview")

        await store.get_batch(key_map)

        assert storage.get_bytes.await_count == 5
