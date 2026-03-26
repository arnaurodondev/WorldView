"""MinHash signature repository — stores and retrieves 128-band MinHash vectors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from content_store.infrastructure.db.models import MinHashEntityMentionModel, MinHashSignatureModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from content_store.domain.entities import EntityMention, MinHashSignature


class MinHashRepository:
    """PostgreSQL repository for MinHash signatures and entity mentions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_signature(self, sig: MinHashSignature) -> None:
        """Insert a MinHash signature. Signature must be list[int], not numpy."""
        self._session.add(
            MinHashSignatureModel(
                sig_id=sig.id,
                doc_id=sig.doc_id,
                signature=sig.signature,
                shingle_type=sig.shingle_type,
            )
        )

    async def get_signature_by_doc_id(self, doc_id: UUID) -> MinHashSignatureModel | None:
        """Fetch the MinHash signature for a document."""
        result = await self._session.execute(
            select(MinHashSignatureModel).where(MinHashSignatureModel.doc_id == doc_id)
        )
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def create_entity_mention(self, mention: EntityMention) -> None:
        """Insert an entity mention linked to a MinHash signature."""
        self._session.add(
            MinHashEntityMentionModel(
                sig_id=mention.sig_id,
                mention_text_hash=mention.mention_text_hash,
                mention_text=mention.mention_text,
                entity_id=mention.entity_id,
                resolution_status=mention.resolution_status,
            )
        )

    async def create_entity_mentions(self, mentions: list[EntityMention]) -> None:
        """Batch-insert entity mentions."""
        for mention in mentions:
            await self.create_entity_mention(mention)
