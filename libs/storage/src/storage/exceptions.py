"""Unified exception hierarchy for the storage library."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for all storage-layer errors."""


class ObjectNotFoundError(StorageError):
    """Raised when a requested object key does not exist in the bucket."""


class BucketNotFoundError(StorageError):
    """Raised when the target bucket does not exist."""


class StoragePermissionError(StorageError):
    """Raised when the storage backend returns an access-denied response."""


class StorageUnavailableError(StorageError):
    """Raised when the storage backend is unreachable or returns a server error."""


class InvalidObjectKeyError(StorageError, ValueError):
    """Raised when an object key violates the canonical naming convention.

    Inherits from both :class:`StorageError` and :exc:`ValueError` so that
    callers can catch either depending on their context.
    """


class ETagMismatchError(StorageError):
    """Raised when an object's actual ETag does not match the caller's expected ETag.

    Used by claim-check consumers that store the producer's ETag alongside the
    object pointer and want to verify the object has not been overwritten or
    corrupted between produce and consume.
    """
