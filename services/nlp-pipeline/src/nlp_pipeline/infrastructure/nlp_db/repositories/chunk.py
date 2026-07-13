"""Chunk repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.infrastructure.nlp_db.models import ChunkModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import Chunk


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chunk: Chunk) -> None:
        # PLAN-0063 W5-2: ``title_denorm`` and ``section_heading_denorm`` feed
        # the GENERATED ``tsv_english`` tsvector column (weights A and B).
        # ``chunk_text`` feeds weight D (and the entire ``tsv_simple``); it must
        # be the actual chunk body (NOT ``chunk_text_key`` which is a MinIO
        # object path — see BP-NEW-CHUNK-TEXT). Skipping any of these would
        # leave new chunks invisible to lexical search.
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
                title_denorm=chunk.title_denorm,
                section_heading_denorm=chunk.section_heading_denorm,
                chunk_text=chunk.text,
                # PLAN-0078 Wave B: persist GLiNER mention metadata for GIN filtering.
                entity_mentions=chunk.entity_mentions,
                # PLAN-0086 Wave C-1: tenant isolation — NULL = public/global content.
                tenant_id=chunk.tenant_id,
                # PLAN-0086 Wave C-1: denormalised document title for RAG citations;
                # truncated to 512 chars to match the DB column length constraint.
                document_title=chunk.title_denorm[:512] if chunk.title_denorm else None,
            )
            .on_conflict_do_nothing(index_elements=["chunk_id"])
        )
        await self._session.execute(stmt)

    async def add_batch(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            await self.add(chunk)

    async def update_entity_mentions_batch(self, chunks: list[Chunk]) -> None:
        """Refresh ONLY the ``entity_mentions`` JSONB for already-inserted chunks.

        BP-719 Mode B: the searchable chunk row (chunk_text + all lexical/denorm
        columns) is inserted EARLY, in its own committed transaction, BEFORE the
        ML enrichment phase (see ``persist_searchable_artifacts``). At insert time
        the ``entity_mentions`` JSONB carries the pre-resolution GLiNER mentions
        (no ``resolved_entity_id``). Once entity resolution finishes, this method
        UPDATES the JSONB in place with the resolved mentions so the happy-path
        row is byte-identical to the pre-BP-719 single-write behaviour.

        Why an explicit UPDATE (not a second ``add``): ``add`` uses
        ``ON CONFLICT (chunk_id) DO NOTHING`` — a second insert of an existing
        chunk is a no-op and would NOT refresh the JSONB. We therefore issue a
        targeted UPDATE that touches only the enrichment column and never the
        searchable ``chunk_text``. It is idempotent (same doc → same resolved
        JSONB) and a UPDATE against a missing row simply affects zero rows.
        """
        for chunk in chunks:
            await self._session.execute(
                update(ChunkModel)
                .where(ChunkModel.chunk_id == chunk.chunk_id)
                .values(entity_mentions=chunk.entity_mentions),
            )

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
