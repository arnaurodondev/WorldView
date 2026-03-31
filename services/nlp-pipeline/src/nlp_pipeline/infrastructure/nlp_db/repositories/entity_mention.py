"""Entity mention repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from nlp_pipeline.infrastructure.nlp_db.models import EntityMentionModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import EntityMention


class EntityMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, mention: EntityMention) -> None:
        row = EntityMentionModel(
            mention_id=mention.mention_id,
            doc_id=mention.doc_id,
            section_id=mention.section_id,
            mention_text=mention.mention_text,
            mention_class=str(mention.mention_class),
            confidence=mention.confidence,
            char_start=mention.char_start,
            char_end=mention.char_end,
            resolved_entity_id=mention.resolved_entity_id,
            resolution_confidence=mention.resolution_confidence,
            resolution_stage=mention.resolution_stage,
        )
        self._session.add(row)

    async def add_batch(self, mentions: list[EntityMention]) -> None:
        for mention in mentions:
            await self.add(mention)

    async def get_by_doc(self, doc_id: UUID) -> list[EntityMentionModel]:
        result = await self._session.execute(select(EntityMentionModel).where(EntityMentionModel.doc_id == doc_id))
        return list(result.scalars().all())

    async def resolve(
        self,
        mention_id: UUID,
        entity_id: UUID,
        confidence: float,
        stage: int,
    ) -> None:
        """Update a mention with resolution result."""
        await self._session.execute(
            update(EntityMentionModel)
            .where(EntityMentionModel.mention_id == mention_id)
            .values(
                resolved_entity_id=entity_id,
                resolution_confidence=confidence,
                resolution_stage=stage,
            ),
        )
