"""Unit tests for storage.s3_adapter (S3ObjectStorage) using mocked boto3."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from storage.buckets import BucketTier
from storage.exceptions import (
    BucketNotFoundError,
    ETagMismatchError,
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


class TestETag:
    """W4-05 / LIB-007 — adapter surfaces S3 ETag and supports opt-in verification."""

    @pytest.mark.asyncio
    async def test_put_bytes_returns_etag_string(self) -> None:
        """``put_bytes`` returns the ETag (quotes stripped) when S3 supplies one."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            # MinIO/S3 wrap the ETag in literal double quotes — adapter must strip them.
            mock_client.put_object.return_value = {"ETag": '"abc123deadbeef"'}

            store = S3ObjectStorage(_make_settings())
            etag = await store.put_bytes("bucket", "k", b"data")

            assert etag == "abc123deadbeef"
            assert isinstance(etag, str)

    @pytest.mark.asyncio
    async def test_put_bytes_returns_none_when_etag_missing(self) -> None:
        """When the backend returns no ETag header, ``put_bytes`` yields ``None``."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            # Some S3-compatible backends omit ETag entirely (or return "").
            mock_client.put_object.return_value = {}

            store = S3ObjectStorage(_make_settings())
            etag = await store.put_bytes("bucket", "k", b"data")

            assert etag is None

    @pytest.mark.asyncio
    async def test_put_bytes_return_value_is_optional_for_callers(self) -> None:
        """Back-compat: existing callers that ignore the return value still work."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.put_object.return_value = {"ETag": '"xyz"'}

            store = S3ObjectStorage(_make_settings())
            # Assigning to ``_`` mimics the previous void-return contract.
            _ = await store.put_bytes("bucket", "k", b"data")

            mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_bytes_without_expected_etag_is_back_compat(self) -> None:
        """Default ``get_bytes`` call (no ETag) must behave exactly as before."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            # Include an ETag header to prove it's IGNORED when caller passes none.
            mock_client.get_object.return_value = {
                "Body": io.BytesIO(b"content"),
                "ETag": '"some-etag"',
            }

            store = S3ObjectStorage(_make_settings())
            result = await store.get_bytes("bucket", "key")

            assert result == b"content"

    @pytest.mark.asyncio
    async def test_get_bytes_with_matching_expected_etag_returns_bytes(self) -> None:
        """When ``expected_etag`` matches the backend ETag, the bytes are returned."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.get_object.return_value = {
                "Body": io.BytesIO(b"payload"),
                "ETag": '"abc123"',
            }

            store = S3ObjectStorage(_make_settings())
            result = await store.get_bytes("bucket", "key", expected_etag="abc123")

            assert result == b"payload"

    @pytest.mark.asyncio
    async def test_get_bytes_with_mismatched_expected_etag_raises(self) -> None:
        """A bogus ``expected_etag`` raises ``ETagMismatchError`` and does NOT return bytes."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.get_object.return_value = {
                "Body": io.BytesIO(b"payload"),
                "ETag": '"abc123"',
            }

            store = S3ObjectStorage(_make_settings())
            with pytest.raises(ETagMismatchError) as exc_info:
                await store.get_bytes("bucket", "key", expected_etag="bogus-etag")

            # Both values should appear in the error message for debuggability.
            msg = str(exc_info.value)
            assert "abc123" in msg
            assert "bogus-etag" in msg

    @pytest.mark.asyncio
    async def test_put_get_roundtrip_with_etag(self) -> None:
        """End-to-end: persist ETag from put, pass back to get — succeeds."""
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            mock_client.put_object.return_value = {"ETag": '"roundtrip-etag"'}
            mock_client.get_object.return_value = {
                "Body": io.BytesIO(b"data"),
                "ETag": '"roundtrip-etag"',
            }

            store = S3ObjectStorage(_make_settings())
            etag = await store.put_bytes("bucket", "k", b"data")
            assert etag == "roundtrip-etag"

            # Producer hands the ETag to a downstream consumer (via Kafka payload),
            # who verifies on the way out.
            result = await store.get_bytes("bucket", "k", expected_etag=etag)
            assert result == b"data"
