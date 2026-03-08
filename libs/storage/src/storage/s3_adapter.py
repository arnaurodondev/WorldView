"""boto3-backed S3/MinIO object storage adapter."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from storage.exceptions import (
    BucketNotFoundError,
    ObjectNotFoundError,
    StoragePermissionError,
    StorageUnavailableError,
)
from storage.interface import ObjectStorage

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage.settings import StorageSettings

logger = structlog.get_logger(__name__)


def _map_client_error(error: Exception, bucket: str, key: str | None = None) -> StorageError:  # type: ignore[name-defined]
    """Map a ``botocore.exceptions.ClientError`` to a domain exception."""
    # Import locally to avoid a hard botocore dep at module import time
    try:
        code = error.response["Error"]["Code"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError):
        return StorageUnavailableError(str(error))

    if code in {"NoSuchKey", "404"}:
        return ObjectNotFoundError(f"Object not found: bucket={bucket!r}, key={key!r}")
    if code in {"NoSuchBucket", "NoSuchBucketAndNoSuchKey"}:
        return BucketNotFoundError(f"Bucket not found: {bucket!r}")
    if code in {"AccessDenied", "403"}:
        return StoragePermissionError(f"Access denied: bucket={bucket!r}, key={key!r}")
    return StorageUnavailableError(f"Storage error [{code}]: bucket={bucket!r}, key={key!r}")


# Re-export StorageError so _map_client_error's return annotation resolves.
from storage.exceptions import StorageError  # noqa: E402


class S3ObjectStorage(ObjectStorage):
    """boto3-backed implementation of :class:`~storage.interface.ObjectStorage`.

    Wraps all boto3 calls with ``asyncio.to_thread`` so they are non-blocking
    in an async context.

    Args:
        settings: :class:`~storage.settings.StorageSettings` instance.
            Constructed automatically by :func:`~storage.factory.build_object_storage`.
    """

    def __init__(self, settings: StorageSettings) -> None:
        import boto3

        self._settings = settings
        self._client = boto3.client(
            "s3",
            region_name=settings.region,
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            use_ssl=settings.use_ssl,
        )
        logger.debug(
            "s3_client_created",
            endpoint=settings.endpoint_url,
            region=settings.region,
        )

    # ------------------------------------------------------------------ helpers

    async def _run(self, fn: Callable[[], Any]) -> Any:
        """Run a blocking boto3 call in a thread pool executor."""
        return await asyncio.to_thread(fn)

    def _handle_client_error(self, exc: Exception, bucket: str, key: str | None = None) -> None:
        """Re-raise *exc* as the appropriate domain exception."""
        try:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError):
                raise _map_client_error(exc, bucket, key) from exc
        except ImportError:
            pass
        try:
            from botocore.exceptions import EndpointResolutionError

            if isinstance(exc, EndpointResolutionError):
                raise StorageUnavailableError(str(exc)) from exc
        except ImportError:
            pass

        raise StorageUnavailableError(str(exc)) from exc

    # ------------------------------------------------------------------ interface

    async def put_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        logger.debug("put_bytes", bucket=bucket, key=key, size=len(data))
        try:
            await self._run(
                lambda: self._client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
            )
        except Exception as exc:
            self._handle_client_error(exc, bucket, key)

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        logger.debug("get_bytes", bucket=bucket, key=key)
        try:
            response = await self._run(lambda: self._client.get_object(Bucket=bucket, Key=key))
            return response["Body"].read()  # type: ignore[no-any-return]
        except Exception as exc:
            self._handle_client_error(exc, bucket, key)
        return b""  # unreachable — _handle_client_error always raises

    async def delete(self, bucket: str, key: str) -> None:
        logger.debug("delete", bucket=bucket, key=key)
        try:
            await self._run(lambda: self._client.delete_object(Bucket=bucket, Key=key))
        except Exception as exc:
            self._handle_client_error(exc, bucket, key)

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        logger.debug("list_keys", bucket=bucket, prefix=prefix)
        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")

            def _paginate() -> list[str]:
                result: list[str] = []
                for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        result.append(obj["Key"])
                return result

            keys = await self._run(_paginate)
        except Exception as exc:
            self._handle_client_error(exc, bucket)
        return sorted(keys)

    async def exists(self, bucket: str, key: str) -> bool:
        logger.debug("exists", bucket=bucket, key=key)
        try:
            await self._run(lambda: self._client.head_object(Bucket=bucket, Key=key))
            return True
        except Exception as exc:
            try:
                from botocore.exceptions import ClientError

                if isinstance(exc, ClientError):
                    code = exc.response["Error"]["Code"]
                    if code in {"404", "NoSuchKey"}:
                        return False
            except ImportError:
                pass
            self._handle_client_error(exc, bucket, key)
        return False  # unreachable

    async def delete_prefix(self, bucket: str, prefix: str) -> int:
        logger.debug("delete_prefix", bucket=bucket, prefix=prefix)
        keys = await self.list_keys(bucket, prefix)
        if not keys:
            return 0

        # boto3 batch delete: max 1000 per call
        deleted = 0
        batch_size = 1000
        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]
            objects: list[dict[str, str]] = [{"Key": k} for k in batch]
            try:
                _captured = objects  # capture loop variable for nested def

                def _delete_batch(o: list[dict[str, str]] = _captured) -> Any:
                    return self._client.delete_objects(Bucket=bucket, Delete={"Objects": o})  # type: ignore[typeddict-item]

                await self._run(_delete_batch)
                deleted += len(batch)
            except Exception as exc:
                self._handle_client_error(exc, bucket)

        logger.info("delete_prefix_done", bucket=bucket, prefix=prefix, deleted=deleted)
        return deleted
