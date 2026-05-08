"""DeleteTenantDocumentUseCase — soft-delete a tenant-owned document.

PLAN-0086 Wave E-1: Multi-Tenant Content Pipeline Isolation.

The deletion is a soft-delete: the DB row is kept and the ``status`` column
transitions from any non-DELETED state → DELETED.  Physical MinIO deletion is
NOT performed here; a separate GC job handles that asynchronously.

The operation is wrapped in a single write transaction that atomically:
  1. Fetches the document with SELECT … FOR UPDATE (prevents TOCTOU races).
  2. Validates that the document exists and belongs to the calling tenant.
  3. Validates that the document is not already in DELETED state.
  4. Calls ``set_deleted()`` to write the status transition.
  5. Appends a ``content.document.deleted.v1`` outbox event.
  6. Commits — the outbox dispatcher fans the event out to Kafka.

A ``SELECT … FOR UPDATE`` is used in step 1 to prevent concurrent delete
requests for the same document from both succeeding and emitting two events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from content_ingestion.domain.exceptions import AlreadyDeletedError, NotFoundError
from content_ingestion.domain.tenant_upload import UploadStatus

if TYPE_CHECKING:
    from content_ingestion.application.ports.repositories import OutboxPort
    from content_ingestion.application.ports.tenant_upload import TenantDocumentUploadRepositoryPort
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

log = structlog.get_logger()  # type: ignore[no-any-return]


class DeleteTenantDocumentUseCase:
    """Soft-delete a tenant document and emit a deletion event via the outbox.

    Args:
        upload_repo: Repository for upload persistence (fetch + status update).
        outbox:      Transactional outbox port for event publishing.
        uow:         Unit of Work — wraps the whole operation in one transaction.
    """

    def __init__(
        self,
        upload_repo: TenantDocumentUploadRepositoryPort,
        outbox: OutboxPort,
        uow: UnitOfWork,
    ) -> None:
        self._upload_repo = upload_repo
        self._outbox = outbox
        self._uow = uow

    async def execute(self, doc_id: UUID, tenant_id: UUID) -> None:
        """Soft-delete the document and publish the deletion event.

        Args:
            doc_id:    UUID of the document to delete.
            tenant_id: UUID of the requesting tenant (enforces isolation).

        Raises:
            NotFoundError:      Document does not exist or belongs to a different tenant.
            AlreadyDeletedError: Document is already in the DELETED state.
        """
        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        async with self._uow:
            # SELECT … FOR UPDATE prevents two concurrent delete requests from
            # both passing the status check and emitting two events.
            doc = await self._upload_repo.get_for_update(doc_id, tenant_id)

            if doc is None:
                # Return the same error regardless of "not found" vs "wrong tenant"
                # to avoid leaking information about other tenants' documents.
                raise NotFoundError(f"Document {doc_id} not found for tenant {tenant_id}")

            if doc.status == UploadStatus.DELETED:
                raise AlreadyDeletedError(f"Document {doc_id} is already deleted")

            # Write the status transition — ``set_deleted`` also stamps ``deleted_at``.
            await self._upload_repo.set_deleted(doc_id, tenant_id)

            # Append outbox event — committed atomically with the status update.
            await self._outbox.append(
                aggregate_type="content_document",
                aggregate_id=doc_id,
                event_type="content.document.deleted",
                topic="content.document.deleted.v1",
                payload={
                    "event_id": str(new_uuid7()),
                    "event_type": "content.document.deleted",
                    "schema_version": 1,
                    "occurred_at": utc_now().isoformat(),
                    "doc_id": str(doc_id),
                    "tenant_id": str(tenant_id),
                },
            )

            await self._uow.commit()

        log.info(
            "tenant_document_deleted",
            doc_id=str(doc_id),
            tenant_id=str(tenant_id),
        )
