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
    """Persist the ENRICHMENT NLP artifacts to nlp_db within the caller's open txn.

    BP-719 Mode B: the SEARCHABLE artefacts (sections, chunks/chunk_text, chunk +
    section embeddings, embedding-pending queue) are persisted EARLIER by
    ``persist_searchable_artifacts`` in a separate committed transaction, BEFORE the
    ML enrichment phase runs — so an enrichment failure / watchdog timeout can never
    lose the searchable document. This function therefore writes only the
    enrichment-derived rows: entity mentions, mention-resolution audit, doc entity
    stats, routing decision, and chunk-entity-mention links — plus an in-place
    refresh of the already-inserted chunks' ``entity_mentions`` JSONB with the now-
    resolved mentions. Does NOT enqueue outbox events — that is handled by the caller
    so unit tests can patch the emission helpers at the ``article_consumer`` module
    namespace.

    ``sections``, ``chunk_embs``, ``section_embs``, and ``pending`` are accepted for
    backwards-compatible call sites but are no longer written here (they belong to
    ``persist_searchable_artifacts``).

    Returns (routing_decision, chunks, final_mentions, outbox_repo) so the
    caller can proceed with event emission using the same outbox_repo instance.
    ``section_repo``, ``chunk_repo``, ``outbox_repo``, and
    ``routing_decision_repo`` may be passed in as pre-built instances
    (constructed in article_consumer._run_pipeline).  When omitted they are
    constructed here against ``nlp_session``.
    """
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

    # PLAN-0093 C-2 (F-NPL-005): apply ``settings.min_persist_floor`` BEFORE writing
    # to the entity_mentions table. The chunks.entity_mentions JSONB already filters
    # by ``gliner_mention_floor`` in ``_augment_chunks`` above — this brings the
    # audited table writer into parity. Without this filter, ~26% of all
    # entity_mentions rows had confidence < 0.6 (noise) yet still flowed into the
    # resolution cascade, consuming ~3.3 LLM resolution attempts each.
    #
    # NOTE: we filter ``ml.final_mentions`` here only for the table write — the
    # in-memory ``ml.final_mentions`` list itself is NOT mutated because the
    # caller still passes it into downstream emitters (chunk-entity-mention pairs,
    # outbox events, etc.) which compute chunk overlaps from the full list. The
    # JSONB cache + low-confidence overlap is intentionally permissive there for
    # future-proofing (re-resolution may upgrade scores later).
    persistable_mentions = [m for m in ml.final_mentions if m.confidence >= settings.min_persist_floor]
    # BP-719 Mode B: sections, chunks (chunk_text), section/chunk embeddings, and
    # the embedding-pending queue are ALL persisted EARLIER, in their own committed
    # transaction (``persist_searchable_artifacts``), BEFORE the ML enrichment phase
    # — so an enrichment failure / 900s-watchdog timeout can no longer lose the
    # searchable document. Here (post-ML) we only write the ENRICHMENT artefacts and
    # refresh the already-inserted chunks' ``entity_mentions`` JSONB with the now-
    # resolved mentions (the pre-ML insert carried the pre-resolution GLiNER JSONB).
    if chunks:
        await _cr.update_entity_mentions_batch(chunks)
    await _emr.add_batch(persistable_mentions)
    if ml.pending_resolution_audit:
        # F-DB-NEW-001 (BP-587): ``mention_resolutions.mention_id`` has a FK to
        # ``entity_mentions.mention_id``.  Sub-floor mentions are filtered out of
        # ``entity_mentions`` above (PLAN-0093 C-2), so their accompanying
        # resolution-audit rows have no FK target → ``ForeignKeyViolationError``
        # → the consumer treats it as retryable → ``content.article.stored.v1``
        # stalls indefinitely (entity_mentions=0 for 26h until detected).
        # Mirror the chunk_entity_mention fix: only persist audit rows whose
        # mention_id survives the floor filter.
        _persistable_ids = {m.mention_id for m in persistable_mentions}
        _audit_to_write = [r for r in ml.pending_resolution_audit if r.mention_id in _persistable_ids]
        if _audit_to_write:
            await _mrr.add_batch(_audit_to_write)
    await _desr.upsert(stats)
    ml.routing_decision.processing_path = ml.final_path
    await _rdr.add(ml.routing_decision)
    # PLAN-0093 C-2: chunk_entity_mentions has FK on entity_mentions.mention_id,
    # so the pair computation must use the same filtered set we just persisted —
    # otherwise links pointing at filtered-out mentions would raise FK violations.
    pairs = _compute_chunk_mention_pairs(chunks, persistable_mentions)
    if pairs:
        await _cemr.link_batch(pairs)

    return ml.routing_decision, chunks, persistable_mentions, _or


async def persist_searchable_artifacts(
    *,
    nlp_session: AsyncSession,
    section_repo: _SectionRepo | None = None,
    chunk_repo: _ChunkRepo | None = None,
    doc_id: uuid.UUID,
    sections: list[Section],
    chunks: list[Chunk],
    chunk_embs: list[tuple[uuid.UUID, list[float]]],
    section_embs: list[tuple[uuid.UUID, list[float]]],
    pending: Any,
    gliner_mention_floor: float,
    settings: Settings,
    ner_mentions: list[EntityMention],
) -> list[Chunk]:
    """Persist the SEARCHABLE artefacts (BP-719 Mode B) — call BEFORE the ML phase.

    Writes the rows that make a document retrievable by chat/RAG — sections, chunks
    (``chunk_text`` + the lexical/denorm columns feeding the tsvector), chunk and
    section embeddings, and the embedding-pending queue — into the caller's open
    ``nlp_session``. The CALLER commits this session in its OWN transaction, so a
    subsequent enrichment failure, deep-extraction timeout, or 900s Kafka watchdog
    cancellation can no longer discard the searchable document (previously
    everything was written in a single trailing transaction that rolled back whole).

    The chunk ``entity_mentions`` JSONB is populated here from the PRE-resolution
    GLiNER mentions (``ner_mentions``) so a doc is still usefully filterable even if
    enrichment never completes. On the happy path ``persist_artifacts`` later
    refreshes this JSONB in place with the resolved mentions (see
    ``ChunkRepository.update_entity_mentions_batch``), so the final row is identical
    to the pre-BP-719 single-write behaviour.

    Idempotency: sections/chunks use ``ON CONFLICT (pk) DO NOTHING`` and embeddings
    use deterministic UUID5 ids with ``DO NOTHING`` — so reprocessing the same Kafka
    message (e.g. after an enrichment retry / redelivery) never duplicates a chunk
    or embedding.

    Returns the augmented ``chunks`` (with the pre-resolution JSONB attached) so the
    caller can carry the same objects into the ML/enrichment phase.
    """
    _sr = section_repo if section_repo is not None else SectionRepository(nlp_session)
    _cr = chunk_repo if chunk_repo is not None else ChunkRepository(nlp_session)

    chunks = _augment_chunks(chunks, ner_mentions, gliner_mention_floor)

    await _sr.add_batch(sections)
    await _cr.add_batch(chunks)
    await _write_section_embeddings(nlp_session, section_embs, model_id=settings.embedding_model_id, doc_id=doc_id)
    await _write_chunk_embeddings(nlp_session, chunk_embs, model_id=settings.embedding_model_id, doc_id=doc_id)
    if pending:
        from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
            EmbeddingPendingRepository,
        )

        await EmbeddingPendingRepository(nlp_session).save_batch(pending)

    return chunks


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
