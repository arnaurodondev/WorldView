"""Domain error hierarchy for the Market Ingestion service.

Retryable errors: transient failures that benefit from automated retry.
Fatal errors: data/logic issues that cannot be resolved by retry.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all Market Ingestion domain errors."""

    @property
    def is_retryable(self) -> bool:
        return False


class RetryableDomainError(DomainError):
    """Base class for errors that are safe to retry automatically."""

    @property
    def is_retryable(self) -> bool:
        return True


# ── Retryable errors ──────────────────────────────────────────────────────────


class ProviderRateLimited(RetryableDomainError):  # noqa: N818
    """Provider has returned a rate-limit response (HTTP 429)."""


class ProviderUnavailable(RetryableDomainError):  # noqa: N818
    """Provider is temporarily unavailable (5xx or connection timeout)."""


class StorageUnavailable(RetryableDomainError):  # noqa: N818
    """Object storage (MinIO/S3) is temporarily unavailable."""


class TaskLeaseLost(RetryableDomainError):  # noqa: N818
    """The worker's lease on an ingestion task has expired or been revoked."""


# ── Fatal errors ──────────────────────────────────────────────────────────────


class ProviderAuthError(DomainError):
    """Provider rejected the API key or credentials (HTTP 401/403)."""


class ProviderDataError(DomainError):
    """Provider returned malformed or unexpected data."""


class InvalidStateTransition(DomainError):  # noqa: N818
    """An entity state transition is not permitted from its current state."""


class WatermarkViolation(DomainError):  # noqa: N818
    """A monotonic watermark advancement was violated (new_ts <= current_ts)."""


class DuplicateTask(DomainError):  # noqa: N818
    """An ingestion task with this dedupe_key already exists."""
