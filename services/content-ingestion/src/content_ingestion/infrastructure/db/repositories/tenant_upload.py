"""Repositories implementing tenant-upload ports against PostgreSQL.

Two repositories live in this module:

- ``TenantDocumentUploadRepository`` — persistence for TenantDocumentUpload entities
- ``TenantDedupHashRepository``      — per-tenant content-hash deduplication

Both are injected into use cases via the application port interfaces; the
infrastructure layer is never imported directly from the domain or application
layers.

Original docstring (preserved for context):
Repository implementing TenantDocumentUploadRepositoryPort against PostgreSQL.

PLAN-0086 Wave D-2: Infrastructure adapter for tenant-owned document uploads.

All public methods scope their queries to ``(doc_id, tenant_id)`` or
``tenant_id`` — it is structurally impossible for a call to return data owned
by a different tenant.  The port contract documents this invariant; this
implementation enforces it via ``WHERE tenant_id = :tenant_id`` on every
statement.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import func, select, update

from content_ingestion.application.ports.tenant_upload import (
    TenantDedupHashRepositoryPort,
    TenantDocumentUploadRepositoryPort,
)
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus
from content_ingestion.infrastructure.db.models import TenantDocumentUploadModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()  # type: ignore[no-any-return]


def _model_to_domain(m: TenantDocumentUploadModel) -> TenantDocumentUpload:
    """Map an ORM row to the immutable domain entity.

    The domain entity is frozen — all fields are passed positionally or as
    keyword args at construction time, so this function is the single place
    where the ORM-to-domain mapping lives.
    """
    return TenantDocumentUpload(
        id=m.id,
        tenant_id=m.tenant_id,
        uploaded_by_user_id=m.uploaded_by_user_id,
        filename=m.filename,
        title=m.title,
        content_type=m.content_type,
        content_hash=m.content_hash,
        byte_size=m.byte_size,
        minio_bronze_key=m.minio_bronze_key,
        status=UploadStatus(m.status),
        uploaded_at=m.uploaded_at,
        word_count=m.word_count,
        chunk_count=m.chunk_count,
        minio_silver_key=m.minio_silver_key,
        error_message=m.error_message,
        ready_at=m.ready_at,
        deleted_at=m.deleted_at,
    )


class TenantDocumentUploadRepository(TenantDocumentUploadRepositoryPort):
    """PostgreSQL implementation of ``TenantDocumentUploadRepositoryPort``.

    All queries include a ``tenant_id`` predicate.  Using ``flush()`` after
    ``add()`` ensures the row is visible within the same transaction (e.g. for
    immediate follow-up reads), without requiring a ``commit()``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: TenantDocumentUpload) -> None:
        """Persist a new upload entity.

        Only the fields known at creation time are written — pipeline-output
        columns (``word_count``, ``chunk_count``, ``minio_silver_key``, etc.)
        are left NULL and populated by later set_ready / set_failed calls.
        """
        model = TenantDocumentUploadModel(
            id=doc.id,
            tenant_id=doc.tenant_id,
            uploaded_by_user_id=doc.uploaded_by_user_id,
            filename=doc.filename,
            title=doc.title,
            content_type=doc.content_type,
            content_hash=doc.content_hash,
            byte_size=doc.byte_size,
            minio_bronze_key=doc.minio_bronze_key,
            status=doc.status.value,
            uploaded_at=doc.uploaded_at,
        )
        self._session.add(model)
        # flush() makes the row visible within the current transaction without
        # committing — allows immediate follow-up queries in the same UoW.
        await self._session.flush()

    async def get(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None:
        """Fetch an upload by (doc_id, tenant_id), or None on miss/wrong tenant."""
        stmt = select(TenantDocumentUploadModel).where(
            TenantDocumentUploadModel.id == doc_id,
            TenantDocumentUploadModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _model_to_domain(model) if model else None

    async def get_for_update(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None:
        """Fetch with SELECT ... FOR UPDATE.

        Prevents TOCTOU races when multiple workers or requests try to
        transition the same upload (e.g. concurrent delete + pipeline-ready).
        Returns None for wrong tenant — same semantics as ``get``.
        """
        stmt = (
            select(TenantDocumentUploadModel)
            .where(
                TenantDocumentUploadModel.id == doc_id,
                TenantDocumentUploadModel.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _model_to_domain(model) if model else None

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        status: UploadStatus | None,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> tuple[list[TenantDocumentUpload], int]:
        """Keyset-paginated list of uploads for a single tenant.

        Pagination is keyset (not offset) so it remains stable under concurrent
        inserts.  The cursor is ``(uploaded_at, id)`` from the last row of the
        previous page — both DESC so that the most recent uploads appear first.

        The total_count is computed against the base filter (tenant + optional
        status) before applying the cursor, so callers always know the total
        matching row count for the whole result set.
        """
        # --- Base predicate (tenant scope + optional status filter) ---
        base_where = [TenantDocumentUploadModel.tenant_id == tenant_id]
        if status is not None:
            base_where.append(TenantDocumentUploadModel.status == status.value)

        # --- Total count (no cursor applied — reflects the full filtered set) ---
        # Use a subquery-based count so SQLAlchemy generates clean SQL.
        count_subq = select(TenantDocumentUploadModel.id).where(*base_where).subquery()
        count_stmt = select(func.count()).select_from(count_subq)
        count_result = await self._session.execute(count_stmt)
        total: int = count_result.scalar_one()

        # --- Keyset cursor predicate ---
        # Standard keyset: rows where (uploaded_at, id) is strictly "before"
        # the cursor value in DESC order.  This gives stable pagination even
        # when new rows are inserted between pages.
        page_where = list(base_where)
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            page_where.append(
                (TenantDocumentUploadModel.uploaded_at < cursor_dt)
                | ((TenantDocumentUploadModel.uploaded_at == cursor_dt) & (TenantDocumentUploadModel.id < cursor_id))
            )

        page_stmt = (
            select(TenantDocumentUploadModel)
            .where(*page_where)
            .order_by(
                TenantDocumentUploadModel.uploaded_at.desc(),
                TenantDocumentUploadModel.id.desc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(page_stmt)
        models = result.scalars().all()
        return [_model_to_domain(m) for m in models], total

    async def set_deleted(self, doc_id: UUID, tenant_id: UUID) -> None:
        """Mark the upload as DELETED and record the deletion timestamp."""
        from common.time import utc_now  # type: ignore[import-untyped]

        stmt = (
            update(TenantDocumentUploadModel)
            .where(
                TenantDocumentUploadModel.id == doc_id,
                TenantDocumentUploadModel.tenant_id == tenant_id,
            )
            .values(status="deleted", deleted_at=utc_now())
        )
        await self._session.execute(stmt)

    async def set_ready(
        self,
        doc_id: UUID,
        tenant_id: UUID,
        chunk_count: int,
        word_count: int,
    ) -> None:
        """Mark the upload as READY and populate pipeline output counts."""
        from common.time import utc_now  # type: ignore[import-untyped]

        stmt = (
            update(TenantDocumentUploadModel)
            .where(
                TenantDocumentUploadModel.id == doc_id,
                TenantDocumentUploadModel.tenant_id == tenant_id,
            )
            .values(
                status="ready",
                ready_at=utc_now(),
                chunk_count=chunk_count,
                word_count=word_count,
            )
        )
        await self._session.execute(stmt)


class TenantDedupHashRepository(TenantDedupHashRepositoryPort):
    """PostgreSQL implementation of ``TenantDedupHashRepositoryPort``.

    Deduplication is implemented against the ``tenant_document_uploads`` table:
    we check whether a row with the same ``(tenant_id, content_hash)`` already
    exists.  This avoids a separate dedup-hash table while preserving the port
    contract.

    The ``idx_tdu_tenant_hash`` index (created in migration 0007) makes the
    ``check_exists`` query efficient — it is a partial B-tree index on
    ``(tenant_id, content_hash)``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_exists(self, hash_type: str, hash_value: str, tenant_id: UUID) -> UUID | None:
        """Return the existing ``doc_id`` if a duplicate content hash is found.

        Args:
            hash_type:  Hash algorithm identifier — only ``"sha256"`` is used.
            hash_value: Hex-encoded hash of the document content.
            tenant_id:  Scope to this tenant only (cross-tenant isolation).

        Returns:
            The ``id`` UUID of the first matching upload, or None if no
            duplicate exists.
        """
        # The table stores content_hash directly on the upload row so dedup is
        # a simple equality check.  hash_type is accepted for interface
        # compatibility (future-proofing for BLAKE3 etc.) but not stored.
        stmt = (
            select(TenantDocumentUploadModel.id)
            .where(
                TenantDocumentUploadModel.tenant_id == tenant_id,
                TenantDocumentUploadModel.content_hash == hash_value,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row  # type: ignore[return-value, no-any-return]  # mapped_column UUID

    async def insert(self, doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID) -> None:
        """No-op: the dedup hash is stored on the upload row itself.

        ``tenant_document_uploads.content_hash`` IS the dedup hash.  The use
        case calls ``upload_repo.create(doc)`` first, which writes the hash
        alongside the upload row; no separate insert is required.
        """
        # Intentionally empty — the dedup hash lives on the upload row.
        # This method satisfies the port contract without writing a duplicate row.
