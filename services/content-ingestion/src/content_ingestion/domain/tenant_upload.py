"""Domain entity and value objects for tenant-owned document uploads.

PLAN-0086 Wave D-1: Multi-Tenant Content Pipeline Isolation.

This module is pure domain — no infrastructure imports are permitted here.
The ``common.ids`` and ``common.time`` imports inside ``create()`` are deferred
(inside the method body) so that infrastructure concerns never leak into the
module-level domain boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class UploadStatus(str, Enum):
    """Lifecycle states for a tenant-uploaded document."""

    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


@dataclass(frozen=True)
class TenantDocumentUpload:
    """Immutable domain entity representing a tenant's uploaded document.

    Invariants (enforced in ``__post_init__``):
    - ``byte_size`` must be positive (zero-byte uploads are not valid).
    - ``content_hash`` must be exactly 64 hex characters (SHA-256 digest).
    - ``uploaded_at`` must be a UTC-aware datetime (tz-naive = programming error).

    All fields that populate as the pipeline progresses (``word_count``,
    ``chunk_count``, ``minio_silver_key``, etc.) are ``None`` until the
    corresponding pipeline stage completes.
    """

    # --- Identity ---
    id: UUID
    tenant_id: UUID
    uploaded_by_user_id: UUID

    # --- File metadata ---
    filename: str
    title: str
    content_type: str
    content_hash: str  # SHA-256 hex digest (64 chars)
    byte_size: int
    minio_bronze_key: str

    # --- Lifecycle ---
    status: UploadStatus
    uploaded_at: datetime

    # --- Pipeline outputs (populated as processing progresses) ---
    word_count: int | None = None
    chunk_count: int | None = None
    minio_silver_key: str | None = None
    error_message: str | None = None
    ready_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        # Enforce structural invariants at construction time so it's impossible
        # to create a logically invalid entity even via direct instantiation.
        if self.byte_size <= 0:
            raise ValueError("byte_size must be > 0")
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be 64-char hex string (SHA-256)")
        if self.uploaded_at.tzinfo is None:
            raise ValueError("uploaded_at must be UTC-aware (tzinfo must not be None)")

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        title: str,
        content_type: str,
        content_hash: str,
        byte_size: int,
        minio_bronze_key: str,
    ) -> TenantDocumentUpload:
        """Factory method — creates a new upload in PROCESSING state.

        Deferred imports: ``common.ids`` and ``common.time`` are imported here
        (not at module level) to keep the domain module free of infrastructure
        references while still using the canonical ID/time helpers.
        """
        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        return cls(
            id=new_uuid7(),
            tenant_id=tenant_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            title=title,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=byte_size,
            minio_bronze_key=minio_bronze_key,
            status=UploadStatus.PROCESSING,
            uploaded_at=utc_now(),
        )
