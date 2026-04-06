"""Chunk repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.infrastructure.nlp_db.models import ChunkModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import Chunk


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chunk: Chunk) -> None:
        stmt = (
            pg_insert(ChunkModel)
            .values(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                section_id=chunk.section_id,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                token_count=chunk.token_count,
                sentence_start_idx=chunk.sentence_start_idx,
                sentence_end_idx=chunk.sentence_end_idx,
                speaker=chunk.speaker,
                heading_path=chunk.heading_path,
                chunk_text_key=chunk.text_key,
            )
            .on_conflict_do_nothing(index_elements=["chunk_id"])
        )
        await self._session.execute(stmt)

    async def add_batch(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            await self.add(chunk)

    async def get_by_doc(self, doc_id: UUID) -> list[ChunkModel]:
        result = await self._session.execute(
            select(ChunkModel).where(ChunkModel.doc_id == doc_id).order_by(ChunkModel.chunk_index),
        )
        return list(result.scalars().all())

    async def get_by_section(self, section_id: UUID) -> list[ChunkModel]:
        result = await self._session.execute(
            select(ChunkModel).where(ChunkModel.section_id == section_id).order_by(ChunkModel.chunk_index),
        )
        return list(result.scalars().all())
