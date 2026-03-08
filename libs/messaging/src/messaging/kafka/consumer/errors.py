"""Kafka consumer error hierarchy.

Two branches:
- :class:`RetryableError` — transient failures; consumer should back off and retry.
- :class:`FatalError` — permanent failures; consumer should dead-letter and move on.

All exceptions inherit from :class:`ConsumerError`.
"""

from __future__ import annotations


class ConsumerError(Exception):
    """Base class for all Kafka consumer errors."""


# ── Retryable branch ─────────────────────────────────────────────────────────


class RetryableError(ConsumerError):
    """Transient error that can be resolved by retrying after a back-off."""


class StorageUnavailableError(RetryableError):
    """Object storage (S3/MinIO) is temporarily unavailable."""


class DatabaseConnectionError(RetryableError):
    """Database connection failed or timed out."""


class NetworkTimeoutError(RetryableError):
    """Upstream network call timed out."""


class ServiceUnavailableError(RetryableError):
    """A downstream service is temporarily unavailable (e.g. 503)."""


class RateLimitedError(RetryableError):
    """Request was rate-limited by an upstream service (e.g. 429)."""


# ── Fatal branch ─────────────────────────────────────────────────────────────


class FatalError(ConsumerError):
    """Permanent error; retrying will not help. Route message to dead-letter queue."""


class SchemaVersionError(FatalError):
    """Message schema version is unsupported or incompatible."""


class MalformedDataError(FatalError):
    """Message payload cannot be parsed or is structurally invalid."""


class MissingRequiredFieldError(FatalError):
    """A required field is absent from the message payload."""


class BusinessRuleViolationError(FatalError):
    """Message violates a domain business rule."""
