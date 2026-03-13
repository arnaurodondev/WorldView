"""Unit tests for S3ObjectStoreAdapter (T-MI-18).

Integration tests (requiring live MinIO) are marked ``@pytest.mark.integration``
and excluded from the default ``make test`` run.
"""

from __future__ import annotations

import hashlib
import os
import socket
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.domain.value_objects import ObjectRef
from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter


@pytest.fixture()
def mock_storage() -> MagicMock:
    storage = MagicMock()
    storage.put_bytes = AsyncMock(return_value=None)
    storage.get_bytes = AsyncMock(return_value=b"hello bytes")
    storage.exists = AsyncMock(return_value=True)
    return storage


@pytest.fixture()
def adapter(mock_storage: MagicMock) -> S3ObjectStoreAdapter:
    return S3ObjectStoreAdapter(mock_storage, default_bucket="test-bucket")


# ---------------------------------------------------------------------------
# put()
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_put_returns_object_ref(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    data = b"market data payload"
    ref = await adapter.put("test-bucket", "market-ingestion/ohlcv/AAPL/v1.json", data, "application/json")

    assert isinstance(ref, ObjectRef)
    assert ref.bucket == "test-bucket"
    assert ref.key == "market-ingestion/ohlcv/AAPL/v1.json"
    assert ref.mime_type == "application/json"


@pytest.mark.unit
async def test_put_computes_correct_sha256(adapter: S3ObjectStoreAdapter) -> None:
    data = b"some binary content"
    ref = await adapter.put("bucket", "some/key", data, "application/octet-stream")

    expected = hashlib.sha256(data).hexdigest()
    assert ref.sha256 == expected


@pytest.mark.unit
async def test_put_records_byte_length(adapter: S3ObjectStoreAdapter) -> None:
    data = b"1234567890"
    ref = await adapter.put("bucket", "key", data)

    assert ref.byte_length == 10


@pytest.mark.unit
async def test_put_delegates_to_storage(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    data = b"payload"
    await adapter.put("my-bucket", "my/key", data, "text/plain")

    mock_storage.put_bytes.assert_awaited_once_with("my-bucket", "my/key", data, "text/plain")


@pytest.mark.unit
async def test_put_default_content_type(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    data = b"raw"
    await adapter.put("bucket", "key", data)

    # default content_type should be application/octet-stream
    call_args = mock_storage.put_bytes.call_args
    assert call_args[0][3] == "application/octet-stream"


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_returns_bytes(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    result = await adapter.get("bucket", "key")
    assert result == b"hello bytes"
    mock_storage.get_bytes.assert_awaited_once_with("bucket", "key")


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exists_delegates_and_returns_true(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    result = await adapter.exists("bucket", "key")
    assert result is True
    mock_storage.exists.assert_awaited_once_with("bucket", "key")


@pytest.mark.unit
async def test_exists_returns_false_when_absent(adapter: S3ObjectStoreAdapter, mock_storage: MagicMock) -> None:
    mock_storage.exists.return_value = False
    result = await adapter.exists("bucket", "missing-key")
    assert result is False


# ---------------------------------------------------------------------------
# ensure_bucket() — no-op
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_ensure_bucket_is_noop(adapter: S3ObjectStoreAdapter) -> None:
    # Should not raise
    await adapter.ensure_bucket("any-bucket")


# ---------------------------------------------------------------------------
# Integration tests (excluded by default — require live MinIO)
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


_HAS_STORAGE_ENDPOINT = bool(os.getenv("MARKET_INGESTION_STORAGE_ENDPOINT", "").strip())
_HAS_MINIO_PORT = _port_open("localhost", 7480)


@pytest.mark.integration
@pytest.mark.skipif(
    not (_HAS_STORAGE_ENDPOINT and _HAS_MINIO_PORT),
    reason="Integration test requires live MinIO on localhost:7480",
)
async def test_integration_put_get_roundtrip() -> None:
    """Real put → get → exists roundtrip against local MinIO."""
    from storage.s3_adapter import S3ObjectStorage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    endpoint = os.getenv("MARKET_INGESTION_STORAGE_ENDPOINT", "http://localhost:7480")
    access_key = os.getenv("MARKET_INGESTION_STORAGE_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MARKET_INGESTION_STORAGE_SECRET_KEY", "minioadmin")
    bucket = os.getenv("MARKET_INGESTION_STORAGE_BUCKET", "market-ingestion")

    settings = StorageSettings(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
    )
    storage = S3ObjectStorage(settings)
    adapter = S3ObjectStoreAdapter(storage, default_bucket=bucket)

    key = f"tests/mi-object-store/{int(time.time_ns())}.bin"
    payload = b"market-ingestion-object-store-roundtrip"

    ref = await adapter.put(bucket, key, payload, "application/octet-stream")
    assert ref.bucket == bucket
    assert ref.key == key

    exists = await adapter.exists(bucket, key)
    assert exists is True

    read_back = await adapter.get(bucket, key)
    assert read_back == payload

    await storage.delete(bucket, key)
