"""Chunk-entity-mention join table repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert

from nlp_pipeline.infrastructure.nlp_db.models import ChunkEntityMentionModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class ChunkEntityMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def link(self, chunk_id: UUID, mention_id: UUID) -> None:
        """Link a chunk to an entity mention (idempotent — ON CONFLICT DO NOTHING)."""
        stmt = (
            insert(ChunkEntityMentionModel)
            .values(chunk_id=chunk_id, mention_id=mention_id)
            .on_conflict_do_nothing(index_elements=["chunk_id", "mention_id"])
        )
        await self._session.execute(stmt)

    async def link_batch(self, pairs: list[tuple[UUID, UUID]]) -> None:
        for chunk_id, mention_id in pairs:
            await self.link(chunk_id, mention_id)
