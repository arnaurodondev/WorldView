"""Factory function for building an :class:`~storage.interface.ObjectStorage` instance."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from storage.s3_adapter import S3ObjectStorage
from storage.settings import StorageSettings

if TYPE_CHECKING:
    from storage.interface import ObjectStorage

logger = structlog.get_logger(__name__)


def build_object_storage(settings: StorageSettings | None = None) -> ObjectStorage:
    """Construct an :class:`~storage.interface.ObjectStorage` from environment settings.

    Args:
        settings: Optional pre-constructed :class:`StorageSettings`.  When
            ``None`` the settings are read from environment variables (``STORAGE_*``
            prefix) automatically.

    Returns:
        A fully initialised :class:`~storage.s3_adapter.S3ObjectStorage` instance.

    Example::

        from storage import build_object_storage

        store = build_object_storage()
        await store.put_bytes("worldview", "market-data/ohlcv/AAPL/v1.parquet", data)
    """
    resolved = settings or StorageSettings()
    logger.debug(
        "build_object_storage",
        endpoint=resolved.endpoint_url,
        default_bucket=resolved.default_bucket,
    )
    return S3ObjectStorage(resolved)
