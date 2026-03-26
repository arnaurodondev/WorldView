"""Domain error hierarchy for the Content Store service."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all S5 domain errors."""


# ── Document errors ────────────────────────────────────────────────────────────


class DocumentNotFoundError(DomainError):
    """Raised when a document cannot be found by its ID."""


class DocumentAlreadyExistsError(DomainError):
    """Raised when a document with the same content_hash already exists."""


# ── Deduplication errors ───────────────────────────────────────────────────────


class DeduplicationError(DomainError):
    """Base class for dedup-stage failures."""


class HashComputationError(DeduplicationError):
    """Raised when hash computation fails (corrupt input, encoding error)."""


class LSHLookupError(DeduplicationError):
    """Raised when Valkey LSH lookup fails (connection, timeout)."""


# ── Storage errors ─────────────────────────────────────────────────────────────


class StorageError(DomainError):
    """Raised when MinIO operations fail."""


class BronzeObjectNotFoundError(StorageError):
    """Raised when the bronze-tier raw object cannot be found."""


# ── Infrastructure errors ──────────────────────────────────────────────────────


class ConfigurationError(DomainError):
    """Raised when required configuration is missing or invalid."""
