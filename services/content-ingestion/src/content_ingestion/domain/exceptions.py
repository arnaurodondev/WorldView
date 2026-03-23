"""Domain exceptions for the Content Ingestion service."""

from __future__ import annotations


class StorageError(Exception):
    """Raised when a MinIO or object-storage operation fails."""


class ConfigurationError(Exception):
    """Raised when service configuration is invalid or incomplete."""


class QuotaExhaustedError(Exception):
    """Raised when an API rate limit or daily quota is exhausted."""


class AdapterError(Exception):
    """Raised when a source adapter (EODHD, SEC, Finnhub, NewsAPI) fails."""
