"""Health-check utility for object storage backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from storage.exceptions import StorageError

if TYPE_CHECKING:
    from storage.interface import ObjectStorage

logger = structlog.get_logger(__name__)


async def check_storage_health(store: ObjectStorage, bucket: str) -> bool:
    """Perform a lightweight liveness check against *bucket*.

    Executes a ``list_keys`` with a sentinel prefix (no real objects needed)
    to verify that the storage backend is reachable and the bucket is accessible.

    Args:
        store: An :class:`~storage.interface.ObjectStorage` instance.
        bucket: Bucket to probe.

    Returns:
        ``True`` if the backend is healthy, ``False`` otherwise.

    Note:
        This function never raises — it logs the error and returns ``False``.
        Services should treat a ``False`` result as a health-check failure
        but not as a hard error that should crash the process.
    """
    try:
        await store.list_keys(bucket, prefix="__health__")
        logger.debug("storage_health_ok", bucket=bucket)
        return True
    except StorageError as exc:
        logger.warning("storage_health_failed", bucket=bucket, error=str(exc))
        return False
    except Exception as exc:
        logger.error("storage_health_unexpected_error", bucket=bucket, error=str(exc))
        return False
