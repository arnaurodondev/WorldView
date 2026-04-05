"""Use case: batch document metadata lookup for S8 citation display."""

from __future__ import annotations

from typing import TYPE_CHECKING

from content_store.domain.errors import DomainError

if TYPE_CHECKING:
    from uuid import UUID

    from content_store.application.ports.repositories import DocumentMetadataDTO, DocumentRepositoryPort

_MAX_BATCH_SIZE = 50


class BatchDocumentsUseCase:
    """Fetch document metadata for a list of doc_ids (read-only).

    Missing doc_ids are silently omitted — callers must handle partial results.
    Raises ``DomainError`` if more than 50 doc_ids are requested.
    """

    def __init__(self, repo: DocumentRepositoryPort) -> None:
        self._repo = repo

    async def execute(self, doc_ids: list[UUID]) -> list[DocumentMetadataDTO]:
        """Return metadata for each found doc_id (max 50).

        Args:
            doc_ids: List of document UUIDs to look up.

        Returns:
            Metadata DTOs for found documents; missing IDs not included.

        Raises:
            DomainError: If ``len(doc_ids) > 50``.
        """
        if len(doc_ids) > _MAX_BATCH_SIZE:
            raise DomainError(f"Too many doc_ids: max {_MAX_BATCH_SIZE}, got {len(doc_ids)}")
        if not doc_ids:
            return []
        return await self._repo.batch_get_metadata(doc_ids)
