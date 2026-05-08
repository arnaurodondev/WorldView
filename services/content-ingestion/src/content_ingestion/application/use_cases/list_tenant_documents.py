"""ListTenantDocumentsUseCase — keyset-paginated list of tenant uploads.

PLAN-0086 Wave E-1: Multi-Tenant Content Pipeline Isolation.

Pagination uses an opaque base64 cursor encoding ``(uploaded_at, doc_id)``
from the last row of the previous page.  This keeps the API surface clean
while delegating the actual DB cursor predicate to the repository layer.

Read-only use case: uses ``ReadOnlyUnitOfWork`` to leverage the read replica
(R27) and prevent accidental writes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from content_ingestion.application.ports.tenant_upload import TenantDocumentUploadRepositoryPort
    from content_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus


# ── Pagination helpers ────────────────────────────────────────────────────────


def _encode_cursor(uploaded_at: datetime, doc_id: UUID) -> str:
    """Encode a keyset cursor as a URL-safe base64 string.

    The cursor encodes ``uploaded_at`` (ISO-8601) and ``doc_id`` joined by
    ``|`` — the same two columns used in the DESC ORDER BY clause.  URL-safe
    base64 avoids the need for extra percent-encoding in query strings.
    """
    raw = f"{uploaded_at.isoformat()}|{doc_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Decode a cursor string produced by ``_encode_cursor``.

    Args:
        cursor: URL-safe base64 string from a previous list response.

    Returns:
        (uploaded_at, doc_id) tuple for the repository WHERE clause.

    Raises:
        ValueError: If the cursor is malformed or cannot be decoded.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        dt_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(dt_str), UUID(id_str)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


# ── DTOs ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ListResult:
    """Response DTO for a paginated list of tenant documents.

    ``next_cursor`` is None on the last page (fewer items than the requested
    limit, or exactly limit items on the last real page).  Callers should
    pass ``next_cursor`` as the ``cursor`` parameter on the next request.

    ``total`` is the total number of documents matching the filter (ignoring
    the cursor), useful for rendering pagination controls in the UI.
    """

    items: list[TenantDocumentUpload]
    next_cursor: str | None
    total: int


# ── Use case ──────────────────────────────────────────────────────────────────


class ListTenantDocumentsUseCase:
    """Return a keyset-paginated list of uploads for a single tenant.

    Uses ``ReadOnlyUnitOfWork`` (R27) — this use case never writes.

    Args:
        repo: Repository for querying uploads.
        uow:  Read-only Unit of Work — provides a read-replica session.
    """

    def __init__(
        self,
        repo: TenantDocumentUploadRepositoryPort,
        uow: ReadOnlyUnitOfWork,
    ) -> None:
        self._repo = repo
        self._uow = uow

    async def execute(
        self,
        tenant_id: UUID,
        status: UploadStatus | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ListResult:
        """List tenant documents with optional status filter and keyset pagination.

        Args:
            tenant_id: Scope results to this tenant only.
            status:    When provided, only documents in this status are returned.
            limit:     Maximum rows per page (default 20; caller may cap it lower).
            cursor:    Opaque cursor from the previous page's ``next_cursor``
                       field.  Pass ``None`` for the first page.

        Returns:
            ``ListResult`` with items, optional next_cursor, and total count.
        """
        # Decode the cursor BEFORE opening the DB session — any ValueError from a
        # malformed cursor is a caller error and should surface before any I/O.
        decoded_cursor = _decode_cursor(cursor) if cursor else None

        async with self._uow:
            items, total = await self._repo.list_by_tenant(
                tenant_id=tenant_id,
                status=status,
                limit=limit,
                cursor=decoded_cursor,
            )

        # Build next_cursor only when a full page was returned — if fewer rows
        # came back than requested we are on the last page.
        next_cursor: str | None = None
        if len(items) == limit and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.uploaded_at, last.id)

        return ListResult(items=items, next_cursor=next_cursor, total=total)
