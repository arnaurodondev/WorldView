"""Embedding persistence helpers for the NLP article pipeline.

Contains:
- ``_write_section_embeddings`` — inserts ``SectionEmbeddingModel`` rows with
  deterministic UUID5 primary keys (PLAN-0084 B-3 idempotency).
- ``_write_chunk_embeddings``   — same for ``ChunkEmbeddingModel``.
- ``_build_chunk_entity_mentions`` — builds the entity_mentions JSONB payload
  for each chunk (PLAN-0078 Wave B).
- ``_compute_chunk_mention_pairs`` — computes (chunk_id, mention_id) overlap pairs
  for the chunk_entity_mentions join table.

All helpers operate on already-resolved ``Chunk`` and ``EntityMention`` domain
objects; no ML calls are made here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore[import-untyped]

from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import ChunkEmbeddingModel, SectionEmbeddingModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import Chunk, EntityMention


async def _write_section_embeddings(
    session: AsyncSession,
    section_embs: list[tuple[uuid.UUID, list[float]]],
    model_id: str,
    doc_id: uuid.UUID,
) -> None:
    """Insert SectionEmbeddingModel rows (best-effort, no flush).

    PLAN-0084 B-3 (T-B-3-02): ``embedding_id`` is a deterministic UUID5 derived
    from ``(doc_id, section_id, model_id)`` so Kafka replays produce the same ID
    and the INSERT uses ``ON CONFLICT (embedding_id) DO NOTHING`` instead of
    raising a PK violation on duplicate delivery.
    """
    for section_id, vec in section_embs:
        # Deterministic embedding_id: same section + model always → same UUID5.
        embedding_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(section_id), model_id))
        stmt = (
            pg_insert(SectionEmbeddingModel)
            .values(
                embedding_id=embedding_id,
                section_id=section_id,
                embedding=vec,
                model_id=model_id,
            )
            .on_conflict_do_nothing(index_elements=["embedding_id"])
        )
        await session.execute(stmt)


async def _write_chunk_embeddings(
    session: AsyncSession,
    chunk_embs: list[tuple[uuid.UUID, list[float]]],
    model_id: str,
    doc_id: uuid.UUID,
) -> None:
    """Insert ChunkEmbeddingModel rows (best-effort, no flush).

    PLAN-0084 B-3 (T-B-3-02): ``embedding_id`` is a deterministic UUID5 derived
    from ``(doc_id, chunk_id, model_id)`` so Kafka replays produce the same ID
    and the INSERT uses ``ON CONFLICT (embedding_id) DO NOTHING`` instead of
    raising a PK violation on duplicate delivery.
    """
    for chunk_id, vec in chunk_embs:
        # Deterministic embedding_id: same chunk + model always → same UUID5.
        embedding_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(chunk_id), model_id))
        stmt = (
            pg_insert(ChunkEmbeddingModel)
            .values(
                embedding_id=embedding_id,
                chunk_id=chunk_id,
                embedding=vec,
                model_id=model_id,
            )
            .on_conflict_do_nothing(index_elements=["embedding_id"])
        )
        await session.execute(stmt)


def _build_chunk_entity_mentions(
    chunks: list[Chunk],
    mentions: list[EntityMention],
    mention_floor: float,
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Build entity_mentions JSONB payload for each chunk (PLAN-0078 Wave B).

    Matches resolved EntityMention objects to chunks by char-offset overlap
    (same logic as _compute_chunk_mention_pairs).  Only mentions with
    ``confidence >= mention_floor`` are included to avoid GIN index bloat.

    Returns a mapping of chunk_id → list[mention_dict] where each dict has:
        entity_id (str|null), entity_type (str), char_start (int),
        char_end (int), gliner_score (float), raw_text (str).
    """
    result: dict[uuid.UUID, list[dict[str, Any]]] = {chunk.chunk_id: [] for chunk in chunks}
    for chunk in chunks:
        for mention in mentions:
            if (
                mention.section_id == chunk.section_id
                and mention.char_start < chunk.char_end
                and mention.char_end > chunk.char_start
                and mention.confidence >= mention_floor
            ):
                result[chunk.chunk_id].append(
                    {
                        "entity_id": str(mention.resolved_entity_id) if mention.resolved_entity_id else None,
                        "entity_type": mention.mention_class.value if mention.mention_class else None,
                        "char_start": mention.char_start,
                        "char_end": mention.char_end,
                        "gliner_score": mention.confidence,
                        "raw_text": mention.mention_text,
                    }
                )
    return result


def _compute_chunk_mention_pairs(
    chunks: list[Chunk],
    mentions: list[EntityMention],
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Return (chunk_id, mention_id) pairs for overlapping char ranges."""
    pairs: list[tuple[uuid.UUID, uuid.UUID]] = []
    for chunk in chunks:
        for mention in mentions:
            # Same section + char overlap
            if (
                mention.section_id == chunk.section_id
                and mention.char_start < chunk.char_end
                and mention.char_end > chunk.char_start
            ):
                pairs.append((chunk.chunk_id, mention.mention_id))
    return pairs
