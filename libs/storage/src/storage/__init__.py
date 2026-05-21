"""storage — S3-compatible object storage abstraction for worldview."""

from storage.buckets import BucketTier
from storage.exceptions import (
    BucketNotFoundError,
    InvalidObjectKeyError,
    ObjectNotFoundError,
    StorageError,
    StoragePermissionError,
    StorageUnavailableError,
)
from storage.factory import build_object_storage
from storage.health import check_storage_health
from storage.interface import ObjectStorage
from storage.key_builder import KeyBuilder, KeyComponents
from storage.s3_adapter import S3ObjectStorage
from storage.settings import StorageSettings

__all__ = [
    "BucketNotFoundError",
    "BucketTier",
    "InvalidObjectKeyError",
    "KeyBuilder",
    "KeyComponents",
    "ObjectNotFoundError",
    "ObjectStorage",
    "S3ObjectStorage",
    "StorageError",
    "StoragePermissionError",
    "StorageSettings",
    "StorageUnavailableError",
    "build_object_storage",
    "check_storage_health",
]
