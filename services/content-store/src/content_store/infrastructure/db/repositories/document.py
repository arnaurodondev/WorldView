"""Document repository — CRUD + query operations on canonical documents."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from content_store.application.ports.repositories import DocumentMetadataDTO, DocumentRepositoryPort
from content_store.infrastructure.db.models import DocumentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from content_store.domain.entities import CanonicalDocument


class DocumentRepository(DocumentRepositoryPort):
    """PostgreSQL document repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: CanonicalDocument) -> None:
        """Insert a new canonical document.

        Flushes immediately so that FK-referencing tables (dedup_hashes,
        minhash_signatures) added in the same transaction can see this row.
        SQLAlchemy 2.0.x does not auto-order inserts by FK without relationship()
        declarations, so an explicit flush is required.
        """
        self._session.add(
            DocumentModel(
                doc_id=doc.id,
                source_type=doc.source_type,
                source_url=doc.source_url,
                title=doc.title,
                published_at=doc.published_at,
                ingested_at=doc.ingested_at,
                content_hash=doc.content_hash,
                normalized_hash=doc.normalized_hash,
                status=doc.status,
                dedup_result=doc.dedup_result,
                minio_silver_key=doc.minio_silver_key,
                word_count=doc.word_count,
                language=doc.language,
                corroborates_doc_id=doc.corroborates_doc_id,
                is_backfill=doc.is_backfill,
            )
        )
        await self._session.flush()

    async def get_by_id(self, doc_id: UUID) -> DocumentModel | None:
        """Fetch a document by its primary key."""
        result = await self._session.execute(select(DocumentModel).where(DocumentModel.doc_id == doc_id))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def get_by_content_hash(self, content_hash: str) -> DocumentModel | None:
        """Fetch a document by its unique content hash (Stage A dedup)."""
        result = await self._session.execute(select(DocumentModel).where(DocumentModel.content_hash == content_hash))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def update_status(self, doc_id: UUID, status: str) -> None:
        """Update a document's processing status."""
        result = await self._session.execute(select(DocumentModel).where(DocumentModel.doc_id == doc_id))
        model = result.scalar_one_or_none()
        if model:
            model.status = status

    async def list_by_source(
        self,
        source_type: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentModel]:
        """List documents filtered by source type, ordered by published_at desc."""
        result = await self._session.execute(
            select(DocumentModel)
            .where(DocumentModel.source_type == source_type)
            .order_by(DocumentModel.published_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def batch_get_metadata(self, doc_ids: list[UUID]) -> list[DocumentMetadataDTO]:
        """Fetch lightweight metadata for a list of doc_ids.

        Missing doc_ids are silently omitted.  ``source_name`` is always
        ``None`` — the ``documents`` table has no such column.
        """
        result = await self._session.execute(
            select(
                DocumentModel.doc_id,
                DocumentModel.title,
                DocumentModel.source_url,
                DocumentModel.published_at,
                DocumentModel.source_type,
                DocumentModel.word_count,
            ).where(DocumentModel.doc_id.in_(doc_ids))
        )
        return [
            DocumentMetadataDTO(
                doc_id=row.doc_id,
                title=row.title,
                url=row.source_url,
                published_at=row.published_at,
                source_name=None,
                source_type=row.source_type,
                word_count=row.word_count,
            )
            for row in result
        ]
