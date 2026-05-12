"""Artifact persistence phase for the NLP article pipeline.

Writes all NLP artifacts to nlp_db within the caller's open ``nlp_session``
transaction.  Must be called BEFORE ``nlp_session.commit()``.

Event emission (enriched, signal, temporal, document-ready outbox events) is
handled by the caller (``ArticleProcessingConsumer._run_pipeline``) so that
unit tests can patch those functions at the ``article_consumer`` module
namespace and have the patches intercept.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import TYPE_CHECKING, Any

from nlp_pipeline.infrastructure.messaging.consumers.blocks.embedding_writes import (
    _build_chunk_entity_mentions,
    _compute_chunk_mention_pairs,
    _write_chunk_embeddings,
    _write_section_embeddings,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk import ChunkRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_entity_mention import (
    ChunkEntityMentionRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.document_entity_stats import (
    DocumentEntityStatsRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import (
    EntityMentionRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.mention_resolution import (
    MentionResolutionRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.routing_decision import (
    RoutingDecisionRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.section import SectionRepository

# Type aliases for pre-built repos passed in from article_consumer._run_pipeline.
# The caller constructs them in the article_consumer namespace so patches at
# "article_consumer.SectionRepository" etc. intercept the construction.
_SectionRepo = SectionRepository
_ChunkRepo = ChunkRepository
_OutboxRepo = OutboxRepository
_RoutingRepo = RoutingDecisionRepository
_EntityMentionRepo = EntityMentionRepository
_DocEntityStatsRepo = DocumentEntityStatsRepository
_ChunkEntityMentionRepo = ChunkEntityMentionRepository
_MentionResolutionRepo = MentionResolutionRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.config import Settings
    from nlp_pipeline.domain.models import Chunk, EntityMention, RoutingDecision, Section
    from nlp_pipeline.infrastructure.messaging.consumers.blocks.ml_phase import MLPhaseResult


async def persist_artifacts(
    *,
    nlp_session: AsyncSession,
    # Pre-built repository instances constructed in article_consumer._run_pipeline
    # so that patches at "article_consumer.FooRepository" intercept them.
    section_repo: _SectionRepo | None = None,
    chunk_repo: _ChunkRepo | None = None,
    outbox_repo: _OutboxRepo | None = None,
    routing_decision_repo: _RoutingRepo | None = None,
    entity_mention_repo: _EntityMentionRepo | None = None,
    doc_entity_stats_repo: _DocEntityStatsRepo | None = None,
    chunk_entity_mention_repo: _ChunkEntityMentionRepo | None = None,
    mention_resolution_repo: _MentionResolutionRepo | None = None,
    doc_id: uuid.UUID,
    sections: list[Section],
    stats: Any,
    chunks: list[Chunk],
    chunk_embs: list[tuple[uuid.UUID, list[float]]],
    section_embs: list[tuple[uuid.UUID, list[float]]],
    pending: Any,
    gliner_mention_floor: float,
    settings: Settings,
    ml: MLPhaseResult,
) -> tuple[RoutingDecision, list[Chunk], list[EntityMention], Any]:
    """Persist all NLP artifacts to nlp_db within the caller's open transaction.

    Writes sections, chunks, entity mentions, stats, routing decision,
    embeddings, and chunk-entity-mention links.  Does NOT enqueue outbox
    events — that is handled by the caller so unit tests can patch the
    emission helpers at the ``article_consumer`` module namespace.

    Returns (routing_decision, chunks, final_mentions, outbox_repo) so the
    caller can proceed with event emission using the same outbox_repo instance.
    ``section_repo``, ``chunk_repo``, ``outbox_repo``, and
    ``routing_decision_repo`` may be passed in as pre-built instances
    (constructed in article_consumer._run_pipeline).  When omitted they are
    constructed here against ``nlp_session``.
    """
    _sr = section_repo if section_repo is not None else SectionRepository(nlp_session)
    _cr = chunk_repo if chunk_repo is not None else ChunkRepository(nlp_session)
    _or = outbox_repo if outbox_repo is not None else OutboxRepository(nlp_session)
    _rdr = routing_decision_repo if routing_decision_repo is not None else RoutingDecisionRepository(nlp_session)
    _emr = entity_mention_repo if entity_mention_repo is not None else EntityMentionRepository(nlp_session)
    _desr = doc_entity_stats_repo if doc_entity_stats_repo is not None else DocumentEntityStatsRepository(nlp_session)
    _cemr = (
        chunk_entity_mention_repo
        if chunk_entity_mention_repo is not None
        else ChunkEntityMentionRepository(nlp_session)
    )
    _mrr = mention_resolution_repo if mention_resolution_repo is not None else MentionResolutionRepository(nlp_session)

    chunks = _augment_chunks(chunks, ml.final_mentions, gliner_mention_floor)

    await _sr.add_batch(sections)
    await _cr.add_batch(chunks)
    await _emr.add_batch(ml.final_mentions)
    if ml.pending_resolution_audit:
        await _mrr.add_batch(ml.pending_resolution_audit)
    await _desr.upsert(stats)
    ml.routing_decision.processing_path = ml.final_path
    await _rdr.add(ml.routing_decision)
    await _write_section_embeddings(nlp_session, section_embs, model_id=settings.embedding_model_id, doc_id=doc_id)
    await _write_chunk_embeddings(nlp_session, chunk_embs, model_id=settings.embedding_model_id, doc_id=doc_id)
    if pending:
        from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
            EmbeddingPendingRepository,
        )

        await EmbeddingPendingRepository(nlp_session).save_batch(pending)
    pairs = _compute_chunk_mention_pairs(chunks, ml.final_mentions)
    if pairs:
        await _cemr.link_batch(pairs)

    return ml.routing_decision, chunks, ml.final_mentions, _or


def _augment_chunks(
    chunks: list[Chunk],
    final_mentions: list[EntityMention],
    mention_floor: float,
) -> list[Chunk]:
    """Add entity_mentions JSONB to each chunk before persisting."""
    if not (chunks and final_mentions):
        return chunks
    cm = _build_chunk_entity_mentions(chunks, final_mentions, mention_floor)
    return [dataclasses.replace(c, entity_mentions=cm[c.chunk_id]) for c in chunks]
