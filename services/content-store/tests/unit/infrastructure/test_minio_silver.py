"""Unit tests for MinIO silver adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from content_store.domain.entities import CanonicalDocument
from content_store.infrastructure.storage.minio_silver import put_canonical, silver_key

pytestmark = pytest.mark.unit


class TestSilverKey:
    def test_key_format(self) -> None:
        key = silver_key("doc-123")
        assert key == "content-store/canonical/doc-123/body.json"

    def test_includes_doc_id(self) -> None:
        doc_id = "01234567-89ab-cdef-0123-456789abcdef"
        key = silver_key(doc_id)
        assert doc_id in key


class TestPutCanonical:
    async def test_writes_json_payload(self) -> None:
        store = AsyncMock()
        doc = CanonicalDocument(
            source_type="eodhd",
            content_hash="abc123",
            normalized_hash="def456",
            title="Test Article",
        )
        key = await put_canonical(store, "worldview-silver", doc, "Cleaned text content")

        store.put_bytes.assert_called_once()
        call_args = store.put_bytes.call_args
        assert call_args.args[0] == "worldview-silver"
        assert "body.json" in call_args.args[1]
        assert call_args.kwargs["content_type"] == "application/json"
        assert key == call_args.args[1]

    async def test_payload_contains_body(self) -> None:
        import json

        store = AsyncMock()
        doc = CanonicalDocument(
            source_type="eodhd",
            content_hash="abc123",
            normalized_hash="def456",
        )
        await put_canonical(store, "bucket", doc, "The body text")

        data = store.put_bytes.call_args.args[2]
        payload = json.loads(data)
        assert payload["body"] == "The body text"
        assert payload["doc_id"] == str(doc.id)
        assert payload["source_type"] == "eodhd"
        assert payload["content_hash"] == "abc123"
