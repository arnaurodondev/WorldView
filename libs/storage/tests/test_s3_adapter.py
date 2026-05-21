"""Unit tests for storage.s3_adapter (S3ObjectStorage) using mocked boto3."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from storage.buckets import BucketTier
from storage.exceptions import (
    BucketNotFoundError,
    ObjectNotFoundError,
    StoragePermissionError,
)
from storage.s3_adapter import S3ObjectStorage
from storage.settings import StorageSettings


def _make_client_error(code: str) -> Exception:
    """Construct a fake botocore ClientError for a given error code."""
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": code, "Message": f"Error {code}"}},
        "operation",
    )


def _make_settings() -> StorageSettings:
    return StorageSettings(
        endpoint="http://localhost:9000",
        access_key="test",
        secret_key="test",
        region="us-east-1",
        use_ssl=False,
    )


class TestS3ObjectStorageInit:
    def test_creates_boto3_client(self) -> None:
        with patch("boto3.client") as mock_client:
            mock_client.return_value = MagicMock()
            store = S3ObjectStorage(_make_settings())
            assert store is not None
            mock_client.assert_called_once()


class TestPutBytes:
    @pytest.mark.asyncio
    async def test_calls_put_object(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            store = S3ObjectStorage(_make_settings())
            await store.put_bytes("bucket", "key/v1.bin", b"data", "application/octet-stream")

            mock_client.put_object.assert_called_once_with(
                Bucket="bucket",
                Key="key/v1.bin",
                Body=b"data",
                ContentType="application/octet-stream",
            )

    @pytest.mark.asyncio
    async def test_maps_no_such_bucket_error(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.put_object.side_effect = _make_client_error("NoSuchBucket")

            store = S3ObjectStorage(_make_settings())
            with pytest.raises(BucketNotFoundError):
                await store.put_bytes("missing-bucket", "k", b"")

    @pytest.mark.asyncio
    async def test_maps_access_denied_error(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.put_object.side_effect = _make_client_error("AccessDenied")

            store = S3ObjectStorage(_make_settings())
            with pytest.raises(StoragePermissionError):
                await store.put_bytes("bucket", "k", b"")


class TestGetBytes:
    @pytest.mark.asyncio
    async def test_returns_body_bytes(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.get_object.return_value = {"Body": io.BytesIO(b"content")}

            store = S3ObjectStorage(_make_settings())
            result = await store.get_bytes("bucket", "key")
            assert result == b"content"

    @pytest.mark.asyncio
    async def test_maps_no_such_key_error(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.get_object.side_effect = _make_client_error("NoSuchKey")

            store = S3ObjectStorage(_make_settings())
            with pytest.raises(ObjectNotFoundError):
                await store.get_bytes("bucket", "missing/key")


class TestBucketTierAcceptance:
    """W4-04 / LIB-006 — adapter accepts both raw strings and BucketTier enum."""

    @pytest.mark.asyncio
    async def test_put_bytes_with_bucket_tier_enum(self) -> None:
        """``put_bytes(BucketTier.BRONZE, ...)`` writes to the canonical bronze bucket."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            store = S3ObjectStorage(_make_settings())
            await store.put_bytes(BucketTier.BRONZE, "k", b"data")

            # StrEnum coerces to its value — the canonical bucket name string.
            mock_client.put_object.assert_called_once_with(
                Bucket="worldview-bronze",
                Key="k",
                Body=b"data",
                ContentType="application/octet-stream",
            )

    @pytest.mark.asyncio
    async def test_put_bytes_with_raw_string_still_works(self) -> None:
        """Back-compat: existing raw-string callers must continue to work unchanged."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            store = S3ObjectStorage(_make_settings())
            await store.put_bytes("worldview-bronze", "k", b"data")

            mock_client.put_object.assert_called_once_with(
                Bucket="worldview-bronze",
                Key="k",
                Body=b"data",
                ContentType="application/octet-stream",
            )

    @pytest.mark.asyncio
    async def test_get_bytes_with_bucket_tier_enum(self) -> None:
        """``get_bytes(BucketTier.SILVER, ...)`` reads from the canonical silver bucket."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.get_object.return_value = {"Body": io.BytesIO(b"payload")}

            store = S3ObjectStorage(_make_settings())
            result = await store.get_bytes(BucketTier.SILVER, "k")
            assert result == b"payload"

            mock_client.get_object.assert_called_once_with(
                Bucket="worldview-silver",
                Key="k",
            )


class TestDelete:
    @pytest.mark.asyncio
    async def test_calls_delete_object(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            store = S3ObjectStorage(_make_settings())
            await store.delete("bucket", "some/key/v1.bin")

            mock_client.delete_object.assert_called_once_with(Bucket="bucket", Key="some/key/v1.bin")


class TestExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_head_succeeds(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.head_object.return_value = {"ContentLength": 42}

            store = S3ObjectStorage(_make_settings())
            assert await store.exists("bucket", "key") is True

    @pytest.mark.asyncio
    async def test_returns_false_on_404(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.head_object.side_effect = _make_client_error("404")

            store = S3ObjectStorage(_make_settings())
            assert await store.exists("bucket", "key") is False


class TestListKeys:
    @pytest.mark.asyncio
    async def test_returns_sorted_keys(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            paginator = MagicMock()
            mock_client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [{"Contents": [{"Key": "svc/dom/b/v1.bin"}, {"Key": "svc/dom/a/v1.bin"}]}]

            store = S3ObjectStorage(_make_settings())
            keys = await store.list_keys("bucket", "svc/")
            assert keys == ["svc/dom/a/v1.bin", "svc/dom/b/v1.bin"]

    @pytest.mark.asyncio
    async def test_empty_bucket_returns_empty_list(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            paginator = MagicMock()
            mock_client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [{}]  # no "Contents" key

            store = S3ObjectStorage(_make_settings())
            keys = await store.list_keys("bucket")
            assert keys == []


class TestDeletePrefix:
    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            paginator = MagicMock()
            mock_client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [{"Contents": [{"Key": "svc/a/v1.bin"}, {"Key": "svc/b/v1.bin"}]}]
            mock_client.delete_objects.return_value = {}

            store = S3ObjectStorage(_make_settings())
            count = await store.delete_prefix("bucket", "svc/")
            assert count == 2
            mock_client.delete_objects.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_keys(self) -> None:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            paginator = MagicMock()
            mock_client.get_paginator.return_value = paginator
            paginator.paginate.return_value = [{}]

            store = S3ObjectStorage(_make_settings())
            count = await store.delete_prefix("bucket", "nonexistent/")
            assert count == 0
