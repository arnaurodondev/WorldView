"""GetTenantDocumentUseCase — fetch a single tenant document by ID.

PLAN-0086 Wave E-1: Multi-Tenant Content Pipeline Isolation.

Read-only use case: uses ``ReadOnlyUnitOfWork`` to leverage the read replica
(R27) and prevent accidental writes.  Returns None for a wrong-tenant lookup
rather than raising, so callers cannot distinguish "not found" from "wrong
tenant" — this prevents information leakage between tenants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from content_ingestion.application.ports.tenant_upload import TenantDocumentUploadRepositoryPort
    from content_ingestion.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from content_ingestion.domain.tenant_upload import TenantDocumentUpload


class GetTenantDocumentUseCase:
    """Return a single ``TenantDocumentUpload`` scoped to (doc_id, tenant_id).

    Returns ``None`` when no matching document exists or when the document
    belongs to a different tenant.  The API layer maps None → 404.

    Uses ``ReadOnlyUnitOfWork`` (R27) — this use case never writes.
    """

    def __init__(
        self,
        repo: TenantDocumentUploadRepositoryPort,
        uow: ReadOnlyUnitOfWork,
    ) -> None:
        # Both repo and uow are injected; the repo is scoped to the session
        # opened by the uow context manager.
        self._repo = repo
        self._uow = uow

    async def execute(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None:
        """Fetch the document or return None if not found / wrong tenant.

        Args:
            doc_id:    UUID of the document to retrieve.
            tenant_id: UUID of the requesting tenant (enforces isolation).

        Returns:
            The ``TenantDocumentUpload`` domain entity, or None.
        """
        async with self._uow:
            return await self._repo.get(doc_id, tenant_id)
