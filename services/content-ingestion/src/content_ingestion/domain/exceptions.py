"""Domain exceptions for the Content Ingestion service."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain exceptions in the Content Ingestion service."""


class StorageError(DomainError):
    """Raised when a MinIO or object-storage operation fails."""


class ConfigurationError(DomainError):
    """Raised when service configuration is invalid or incomplete."""


class QuotaExhaustedError(DomainError):
    """Raised when an API rate limit or daily quota is exhausted."""


class AdapterError(DomainError):
    """Raised when a source adapter (EODHD, SEC, Finnhub, NewsAPI) fails."""


class InvalidStateTransition(DomainError):  # noqa: N818
    """An entity state transition is not permitted from its current state."""
