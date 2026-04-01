"""Unit tests for MinIO bronze-tier adapter and storage wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.app import _normalize_endpoint
from content_ingestion.infrastructure.storage.minio_bronze import (
    MinioBronzeAdapter,
    build_bronze_key,
)

from storage.settings import StorageSettings

pytestmark = pytest.mark.unit


# ── Key builder ───────────────────────────────────────────────────────────────


class TestBuildBronzeKey:
    def test_key_format(self) -> None:
        key = build_bronze_key("eodhd", "abc123")
        assert key == "content-ingestion/eodhd/abc123/raw/v1.json"

    def test_key_includes_source_type(self) -> None:
        key = build_bronze_key("sec_edgar", "xyz")
        assert "sec_edgar" in key

    def test_key_includes_url_hash(self) -> None:
        key = build_bronze_key("finnhub", "deadbeef")
        assert "deadbeef" in key


# ── MinioBronzeAdapter ────────────────────────────────────────────────────────


class TestMinioBronzeAdapterPutObject:
    async def test_put_object_calls_storage_put_bytes(self) -> None:
        storage = AsyncMock()
        adapter = MinioBronzeAdapter(storage, bucket="test-bucket")

        key = await adapter.put_object(
            source_type="eodhd",
            url_hash="abc123",
            raw_bytes=b"hello world",
            url="https://example.com/a",
        )

        storage.put_bytes.assert_awaited_once()
        call_args = storage.put_bytes.call_args
        assert call_args[0][0] == "test-bucket"
        assert call_args[0][1] == key
        assert key == "content-ingestion/eodhd/abc123/raw/v1.json"

    async def test_put_object_returns_correct_key(self) -> None:
        storage = AsyncMock()
        adapter = MinioBronzeAdapter(storage)

        key = await adapter.put_object(
            source_type="newsapi",
            url_hash="feed123",
            raw_bytes=b"data",
        )

        assert key == "content-ingestion/newsapi/feed123/raw/v1.json"

    async def test_put_object_envelope_is_json(self) -> None:
        """Verify the payload written to storage is valid JSON with expected fields."""
        import json

        storage = AsyncMock()
        adapter = MinioBronzeAdapter(storage, bucket="b")

        await adapter.put_object(
            source_type="eodhd",
            url_hash="h1",
            raw_bytes=b"test",
            url="https://example.com",
            is_backfill=True,
        )

        payload_bytes = storage.put_bytes.call_args[0][2]
        envelope = json.loads(payload_bytes)
        assert envelope["source_type"] == "eodhd"
        assert envelope["url_hash"] == "h1"
        assert envelope["url"] == "https://example.com"
        assert envelope["is_backfill"] is True
        assert envelope["byte_size"] == 4
        assert "raw_b64" in envelope
        assert "stored_at" in envelope


class TestMinioBronzeAdapterObjectExists:
    async def test_object_exists_delegates_to_storage(self) -> None:
        storage = AsyncMock()
        storage.exists.return_value = True
        adapter = MinioBronzeAdapter(storage, bucket="b")

        result = await adapter.object_exists("eodhd", "abc123")

        assert result is True
        storage.exists.assert_awaited_once_with("b", "content-ingestion/eodhd/abc123/raw/v1.json")

    async def test_object_exists_returns_false(self) -> None:
        storage = AsyncMock()
        storage.exists.return_value = False
        adapter = MinioBronzeAdapter(storage)

        result = await adapter.object_exists("finnhub", "xyz")

        assert result is False


# ── Endpoint normalization ────────────────────────────────────────────────────


def test_normalize_endpoint_adds_http_scheme_when_missing() -> None:
    assert _normalize_endpoint("localhost:7480") == "http://localhost:7480"


def test_normalize_endpoint_keeps_existing_scheme() -> None:
    assert _normalize_endpoint("http://localhost:7480") == "http://localhost:7480"
    assert _normalize_endpoint("https://minio.internal:9000") == "https://minio.internal:9000"


def test_storage_settings_mapping_from_service_config_like_values() -> None:
    service_settings = MagicMock()
    service_settings.minio_endpoint = "localhost:7480"
    service_settings.minio_access_key = "minioadmin"
    service_settings.minio_secret_key = "minioadmin"  # noqa: S105
    service_settings.minio_secure = False
    service_settings.minio_bucket = "worldview-bronze"

    storage_settings = StorageSettings(
        endpoint=_normalize_endpoint(service_settings.minio_endpoint),
        access_key=service_settings.minio_access_key,
        secret_key=service_settings.minio_secret_key,
        use_ssl=service_settings.minio_secure,
        default_bucket=service_settings.minio_bucket,
    )

    assert storage_settings.endpoint == "http://localhost:7480"
    assert storage_settings.default_bucket == "worldview-bronze"
