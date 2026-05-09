"""Port interfaces for the tenant document upload pipeline.

PLAN-0086 Wave D-1: Multi-Tenant Content Pipeline Isolation.

These ABCs define the application-layer boundary between use cases and
infrastructure implementations. Use cases depend only on these abstractions —
never on SQLAlchemy, asyncpg, Valkey, or MinIO directly.

Three ports are defined here:
- ``TenantDocumentUploadRepositoryPort`` — persistence for upload entities
- ``TenantDedupHashRepositoryPort`` — per-tenant content-hash deduplication
- ``UploadRateLimitPort`` — Valkey sliding-window rate limiter
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus


class TenantDocumentUploadRepositoryPort(ABC):
    """Persistence port for ``TenantDocumentUpload`` entities.

    All methods are scoped to a (doc_id, tenant_id) pair to enforce strict
    tenant isolation — an upload belonging to tenant A is never returned to
    tenant B, even if the caller somehow supplies the correct doc_id.
    """

    @abstractmethod
    async def create(self, doc: TenantDocumentUpload) -> None:
        """Persist a newly-created upload entity."""
        ...

    @abstractmethod
    async def get(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None:
        """Fetch an upload by (doc_id, tenant_id).

        Returns None for wrong tenant to avoid information leaks — callers
        cannot distinguish "not found" from "belongs to another tenant".
        """
        ...

    @abstractmethod
    async def get_for_update(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None:
        """Fetch with SELECT ... FOR UPDATE.

        Used by ``DeleteTenantDocumentUseCase`` to prevent TOCTOU race
        conditions when transitioning an upload to DELETED status.
        Returns None for wrong tenant (same semantics as ``get``).
        """
        ...

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
        status: UploadStatus | None,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> tuple[list[TenantDocumentUpload], int]:
        """Keyset-paginated list of uploads for a single tenant.

        Args:
            tenant_id: Scope to this tenant only.
            status:    When not None, filter to this upload status.
            limit:     Maximum number of rows to return.
            cursor:    Opaque keyset cursor — (uploaded_at, id) from the last
                       row of the previous page. Pass None for the first page.

        Returns:
            (items, total_count) — total_count is the total matching rows
            across all pages (not just the current page).
        """
        ...

    @abstractmethod
    async def set_deleted(self, doc_id: UUID, tenant_id: UUID) -> None:
        """Mark an upload as DELETED and set ``deleted_at`` to now."""
        ...

    @abstractmethod
    async def set_ready(self, doc_id: UUID, tenant_id: UUID, chunk_count: int, word_count: int) -> None:
        """Mark an upload as READY and populate pipeline output fields."""
        ...

    @abstractmethod
    async def set_failed(self, doc_id: UUID, tenant_id: UUID, error_message: str) -> None:
        """Mark an upload as FAILED with an error message."""
        ...


class TenantDedupHashRepositoryPort(ABC):
    """Port for per-tenant content-hash deduplication.

    Deduplication is scoped to (tenant_id, hash_type, hash_value) so that
    the same file uploaded by two different tenants is NOT considered a
    duplicate — each tenant's data is isolated.
    """

    @abstractmethod
    async def check_exists(self, hash_type: str, hash_value: str, tenant_id: UUID) -> UUID | None:
        """Check whether a content hash already exists for this tenant.

        Returns the existing ``doc_id`` UUID if a duplicate is found, else
        None. Callers should raise ``DuplicateDocumentError`` when non-None.
        """
        ...

    @abstractmethod
    async def insert(self, doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID) -> None:
        """Record a new (tenant_id, hash_type, hash_value) → doc_id mapping."""
        ...


class UploadRateLimitPort(ABC):
    """Valkey sliding-window rate limiter for per-tenant uploads.

    Designed to fail-open: if Valkey is unavailable the implementation MUST
    return True (allow) so that a cache outage doesn't block all uploads.
    Rate limits are advisory, not a security control.
    """

    @abstractmethod
    async def check_and_increment(self, tenant_id: UUID, window_seconds: int, limit: int) -> bool:
        """Atomically check + increment the tenant's upload counter.

        Args:
            tenant_id:      The tenant to rate-limit.
            window_seconds: Sliding window size in seconds (e.g. 86400 = 1 day).
            limit:          Maximum uploads allowed in the window.

        Returns:
            True  — upload is within the limit; counter was incremented.
            False — upload would exceed the limit; counter was NOT incremented.
            True  — also returned when Valkey is unavailable (fail-open).
        """
        ...

    @abstractmethod
    async def get_reset_at(self, tenant_id: UUID) -> datetime | None:
        """Return the UTC datetime when the current window resets.

        Returns None if there is no active rate-limit window (e.g. first
        upload, or Valkey unavailable).  Used to populate the
        ``UploadRateLimitError.resets_at`` field for the 429 response body.
        """
        ...
