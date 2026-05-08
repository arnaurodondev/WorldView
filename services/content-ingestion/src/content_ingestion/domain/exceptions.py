"""Domain exceptions for the Content Ingestion service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


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


# ── Tenant Upload domain errors (PLAN-0086 Wave D-1) ─────────────────────────


class UnsupportedFileTypeError(DomainError):
    """File MIME type is not in the allowed set (PDF, plain text)."""


class FileTooLargeError(DomainError):
    """File exceeds the configured size limit (default 50 MB).

    Attributes:
        byte_size: Actual size of the rejected file in bytes.
        limit:     Maximum allowed size in bytes.
    """

    def __init__(self, byte_size: int, limit: int) -> None:
        super().__init__(f"File size {byte_size} exceeds limit {limit}")
        self.byte_size = byte_size
        self.limit = limit


class TextExtractionError(DomainError):
    """Text extraction yielded empty or whitespace-only content.

    Raised when PDF/text parsing succeeds structurally but produces no
    usable text — e.g. a scanned image PDF with no OCR layer.
    """


class DuplicateDocumentError(DomainError):
    """Same content (tenant_id, content_hash) already exists for this tenant.

    Attributes:
        existing_doc_id: The UUID of the previously-uploaded document that
                         shares the same content hash within this tenant scope.
    """

    def __init__(self, existing_doc_id: UUID) -> None:
        super().__init__(f"Duplicate document: {existing_doc_id}")
        self.existing_doc_id = existing_doc_id


class UploadRateLimitError(DomainError):
    """Tenant has exceeded the upload rate limit for the current window.

    Attributes:
        resets_at: UTC datetime when the rate-limit window resets, suitable
                   for including in a 429 Retry-After response header.
    """

    def __init__(self, resets_at: datetime) -> None:
        super().__init__(f"Rate limit exceeded, resets at {resets_at.isoformat()}")
        self.resets_at = resets_at
