"""Article consumer — orchestrates all 8 S6 processing blocks (PRD §6.7 Blocks 3-10).

Consumes ``content.article.stored.v1`` from S5.  For each message:

1.  Downloads clean article text from MinIO silver key.
2.  Runs Blocks 3-10 in sequence: sectioning → NER → routing → suppression →
    embeddings → novelty → entity resolution → deep extraction.
3.  Writes all artifacts to nlp_db in one atomic transaction.
4.  Enqueues ``nlp.article.enriched.v1`` events via the outbox (committed
    inside the same transaction).
5.  Commits the Kafka offset only after the DB transaction succeeds.

Backpressure: each message acquires one slot on the BackpressureController
semaphore before any ML work begins. The slot is released on exit.

Idempotency: at-least-once; re-delivery is safe because section inserts use
the section_id as the primary key (duplicate inserts are no-ops or caught by
the CONFLICT guard at DB level).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from nlp_pipeline.application.blocks.deep_extraction import run_deep_extraction_block
from nlp_pipeline.application.blocks.embeddings import run_embeddings_block
from nlp_pipeline.application.blocks.entity_resolution import run_entity_resolution_block
from nlp_pipeline.application.blocks.ner import run_ner_block
from nlp_pipeline.application.blocks.novelty import run_novelty_gate
from nlp_pipeline.application.blocks.routing import compute_routing_score
from nlp_pipeline.application.blocks.sectioning import section_document
from nlp_pipeline.application.blocks.suppression import (
    ProcessingPath,
    apply_suppression_gate,
    should_generate_chunk_embeddings,
    should_run_deep_extraction,
    should_run_entity_resolution,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
    EntityAliasRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
    EntityProfileEmbeddingRepository,
)
from nlp_pipeline.infrastructure.nlp_db.models import ChunkEmbeddingModel, SectionEmbeddingModel
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk import ChunkRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_entity_mention import (
    ChunkEntityMentionRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.document_entity_stats import (
    DocumentEntityStatsRepository,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.document_source_metadata import (
    SQLAlchemyDocumentSourceMetadataRepository,
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
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient  # type: ignore[import-not-found]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
    from nlp_pipeline.config import Settings
    from nlp_pipeline.domain.models import Chunk, EntityMention, RoutingDecision, Section
    from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "content.article.stored.v1"

# Avro schema directory — 6 parents up from this file reaches /app in the container
# (/app/src/nlp_pipeline/infrastructure/messaging/consumers/ → /app)
_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra" / "kafka" / "schemas"

# Default source trust weight — used when intelligence_db source_trust_weights table
# is not queried. Contribution = 0.20 * 0.5 = 0.10 to routing score.
_DEFAULT_SOURCE_TRUST = 0.5


class _NoOpUnitOfWork:
    """Thin UoW — article consumer manages its own session inside process_message."""

    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class ArticleProcessingConsumer(BaseKafkaConsumer[None]):
    """Orchestrates S6 Blocks 3-10 for each incoming stored article.

    All ML clients and repository factories are injected at construction time.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        settings: Settings,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        intelligence_session_factory: async_sessionmaker[AsyncSession],
        storage: Any,  # ObjectStorage from libs/storage
        watchlist_cache: WatchlistCache,
        ner_client: NERClient,
        embedding_client: EmbeddingClient,
        extraction_client: ExtractionClient,
        backpressure: BackpressureController,
        chunk_text_store: ChunkTextStorePort | None = None,
    ) -> None:
        super().__init__(config)
        self._settings = settings
        self._nlp_sf = nlp_session_factory
        self._intel_sf = intelligence_session_factory
        self._storage = storage
        self._watchlist = watchlist_cache
        self._ner = ner_client
        self._emb = embedding_client
        self._ext = extraction_client
        self._bp = backpressure
        self._chunk_text_store = chunk_text_store

    # ── UoW (no-op — session managed inside process_message) ─────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Orchestrate all 8 blocks for one article event.

        Acquires one backpressure slot before ML work starts.
        After the main pipeline commits, writes citation metadata as a
        best-effort side effect (failure is logged but does not re-raise).
        """
        doc_id = uuid.UUID(str(value["doc_id"]))
        minio_key = str(value["minio_silver_key"])
        source_type = str(value["source_type"])
        is_backfill = bool(value.get("is_backfill", False))
        correlation_id: str | None = value.get("correlation_id") or None

        raw_published = value.get("published_at")
        published_at: datetime | None = None
        if raw_published:
            try:
                published_at = datetime.fromisoformat(str(raw_published))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                pass

        extracted_at: datetime = common.time.utc_now()

        async with self._bp:
            await self._run_pipeline(
                doc_id=doc_id,
                minio_key=minio_key,
                source_type=source_type,
                published_at=published_at,
                extracted_at=extracted_at,
                is_backfill=is_backfill,
                correlation_id=correlation_id,
            )

        # Best-effort: cache citation metadata for S8 RAG inline citations.
        # Failure must never cause NLP processing to fail.
        await self._write_source_metadata(
            doc_id=doc_id,
            title=value.get("title"),
            url=value.get("url"),
            published_at=published_at,
            source_name=value.get("source_name"),
            source_type=source_type,
            word_count=value.get("word_count"),
        )

    async def _run_pipeline(
        self,
        *,
        doc_id: uuid.UUID,
        minio_key: str,
        source_type: str,
        published_at: datetime | None,
        extracted_at: datetime,
        is_backfill: bool,
        correlation_id: str | None,
    ) -> None:
        """Download text and run Blocks 3-10 in one atomic nlp_db transaction."""

        # ── Block 3: Sectioning (pure) ────────────────────────────────────────
        text = await self._download_article(minio_key)
        sections = section_document(doc_id, text, source_type)

        # ── Block 4: NER (ML, outside DB transaction) ─────────────────────────
        mentions, stats = await run_ner_block(
            doc_id=doc_id,
            sections=sections,
            ner_client=self._ner,
            threshold=self._settings.gliner_threshold,
            batch_size=self._settings.gliner_batch_size,
        )

        # ── Block 5: Routing score (initial, novelty_score=0.0 provisional) ───
        watched_ids = await self._watchlist.get_all_watched()

        # Fetch price_impact signal — best-effort; defaults to 0.0 for articles
        # < 25h old (not yet labelled) or on any lookup error (PRD-0020 §6.7).
        price_impact_score = 0.0
        try:
            from nlp_pipeline.infrastructure.nlp_db.repositories.price_impact import (
                ArticlePriceImpactRepository,
            )

            async with self._nlp_sf() as impact_session:
                impact_repo = ArticlePriceImpactRepository(impact_session)
                max_impact = await impact_repo.get_max_impact_for_doc(doc_id)
                price_impact_score = float(max_impact)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "price_impact_lookup_failed",
                doc_id=str(doc_id),
            )

        decision_id = common.ids.new_uuid7()
        routing_decision = compute_routing_score(
            doc_id=doc_id,
            decision_id=decision_id,
            source_type=source_type,
            published_at=published_at,
            extracted_at=extracted_at,
            mentions=mentions,
            section_count=len(sections),
            source_trust_weight=_DEFAULT_SOURCE_TRUST,
            novelty_score=0.0,
            watched_entity_ids=watched_ids,
            price_impact_score=price_impact_score,
        )

        # ── Block 6: Initial suppression gate ────────────────────────────────
        initial_path = apply_suppression_gate(routing_decision)

        # ── Block 7: Embeddings (runs for ALL tiers; chunks only for FULL) ───
        generate_chunks = should_generate_chunk_embeddings(initial_path)
        chunks, chunk_embs, section_embs, pending = await run_embeddings_block(
            sections=sections,
            embedding_client=self._emb,
            model_id=self._settings.embedding_model_id,
            instruction_prefix=self._settings.embedding_instruction_prefix,
            generate_chunk_embeddings=generate_chunks,
            chunk_text_store=self._chunk_text_store,
        )

        # ── Block 8: Novelty gate (skip for HALT — can't downgrade further) ──
        final_path = initial_path
        if initial_path != ProcessingPath.HALT:
            async with self._intel_sf() as intel_session:
                ep_repo = EntityProfileEmbeddingRepository(intel_session)
                routing_decision, _novelty_score = await run_novelty_gate(
                    doc_id=doc_id,
                    routing_decision=routing_decision,
                    valkey_client=self._watchlist._client,  # type: ignore[attr-defined]
                    entity_profile_embedding_repo=ep_repo,
                    resolved_entity_ids=[],
                    entity_embeddings={},
                )
            final_path = apply_suppression_gate(routing_decision)

        # ── Blocks 9+10 and atomic DB write ───────────────────────────────────
        async with self._nlp_sf() as session:
            extraction_result: dict[str, Any] = {"events": [], "claims": [], "relations": []}
            final_mentions = list(mentions)

            # Block 9: Entity resolution (reads intel_db, writes audit to nlp_session)
            if should_run_entity_resolution(final_path):
                async with self._intel_sf() as intel_session:
                    alias_repo = EntityAliasRepository(intel_session)
                    ep_repo2 = EntityProfileEmbeddingRepository(intel_session)
                    canon_repo = CanonicalEntityRepository(intel_session)
                    mr_repo = MentionResolutionRepository(session)

                    resolved_mentions, _audit = await run_entity_resolution_block(
                        mentions=mentions,
                        alias_repo=alias_repo,
                        embedding_repo=ep_repo2,
                        canonical_entity_repo=canon_repo,
                        resolution_audit_repo=mr_repo,
                        embedding_client=self._emb,
                        intelligence_session=intel_session,
                        model_id=self._settings.embedding_model_id,
                        instruction_prefix=self._settings.embedding_instruction_prefix,
                    )
                    final_mentions = resolved_mentions

            # Block 10: Deep LLM extraction (writes claims to outbox via nlp_session)
            from nlp_pipeline.infrastructure.intelligence_db.repositories.claims import (
                ClaimsRepository,
            )

            claims_repo = ClaimsRepository(session)
            if should_run_deep_extraction(final_path):
                extraction_result, _signals = await run_deep_extraction_block(
                    doc_id=doc_id,
                    chunks=chunks,
                    mentions=final_mentions,
                    processing_path=final_path,
                    extraction_client=self._ext,
                    claims_repo=claims_repo,
                    model_id=self._settings.extraction_model_id,
                    published_at=published_at,
                    extracted_at=extracted_at,
                    outbox_topic_signal=self._settings.topic_signal_detected,
                )

            # Write all artifacts to nlp_db
            section_repo = SectionRepository(session)
            chunk_repo = ChunkRepository(session)
            mention_repo = EntityMentionRepository(session)
            stats_repo = DocumentEntityStatsRepository(session)
            routing_repo = RoutingDecisionRepository(session)
            cem_repo = ChunkEntityMentionRepository(session)
            outbox_repo = OutboxRepository(session)

            await section_repo.add_batch(sections)
            await chunk_repo.add_batch(chunks)
            await mention_repo.add_batch(final_mentions)
            await stats_repo.upsert(stats)
            await routing_repo.add(routing_decision)

            # Write embeddings directly (no dedicated repo)
            _write_section_embeddings(session, section_embs, model_id=self._settings.embedding_model_id)
            _write_chunk_embeddings(session, chunk_embs, model_id=self._settings.embedding_model_id)

            # Persist failed embeddings for retry by EmbeddingRetryWorker
            if pending:
                from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
                    EmbeddingPendingRepository,
                )

                pending_repo = EmbeddingPendingRepository(session)
                await pending_repo.save_batch(pending)

            # Link chunk↔mention by char offset overlap
            pairs = _compute_chunk_mention_pairs(chunks, final_mentions)
            if pairs:
                await cem_repo.link_batch(pairs)

            # Enqueue enriched event
            await _enqueue_enriched(
                outbox_repo=outbox_repo,
                settings=self._settings,
                doc_id=doc_id,
                source_type=source_type,
                published_at=published_at,
                is_backfill=is_backfill,
                routing_decision=routing_decision,
                sections=sections,
                chunks=chunks,
                mentions=final_mentions,
                extraction_result=extraction_result,
                correlation_id=correlation_id,
            )

            try:
                await session.commit()
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "nlp_commit_failed_intel_writes_may_be_orphaned",
                    doc_id=str(doc_id),
                    exc_info=True,
                )
                raise

        logger.info(  # type: ignore[no-any-return]
            "article_processed",
            doc_id=str(doc_id),
            routing_tier=(routing_decision.final_routing_tier or routing_decision.routing_tier).value,
            section_count=len(sections),
            chunk_count=len(chunks),
            mention_count=len(final_mentions),
        )

    # ── MinIO download ────────────────────────────────────────────────────────

    async def _download_article(self, minio_key: str) -> str:
        """Download cleaned article text from MinIO silver layer.

        The silver object is a JSON envelope (see content-store minio_silver.py):
        {"body": "<cleaned text>", "source_type": ..., ...}
        """
        if self._storage is None:
            msg = "Object storage not configured; cannot download article text"
            raise RuntimeError(msg)
        raw = await self._storage.get_bytes(self._settings.silver_bucket, minio_key)
        try:
            envelope = json.loads(raw)
            if isinstance(envelope, dict) and "body" in envelope:
                return str(envelope["body"])
        except (json.JSONDecodeError, ValueError):
            pass
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    # ── Source metadata cache (best-effort) ──────────────────────────────────

    async def _write_source_metadata(
        self,
        *,
        doc_id: uuid.UUID,
        title: str | None,
        url: str | None,
        published_at: datetime | None,
        source_name: str | None,
        source_type: str | None,
        word_count: int | None,
    ) -> None:
        """Write citation metadata to nlp_db.document_source_metadata.

        Best-effort: any exception is logged as a warning and swallowed so
        that NLP processing is never blocked by a metadata write failure.
        """
        from nlp_pipeline.domain.models import DocumentSourceMetadata

        try:
            metadata = DocumentSourceMetadata(
                doc_id=doc_id,
                title=str(title) if title is not None else None,
                url=str(url) if url is not None else None,
                published_at=published_at,
                source_name=str(source_name) if source_name is not None else None,
                source_type=str(source_type) if source_type is not None else None,
                word_count=int(word_count) if word_count is not None else None,
                created_at=common.time.utc_now(),
            )
            async with self._nlp_sf() as session:
                repo = SQLAlchemyDocumentSourceMetadataRepository(session)
                await repo.upsert(metadata)
                await session.commit()
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "source_metadata_write_failed",
                doc_id=str(doc_id),
                exc_info=True,
            )

    # ── Idempotency ───────────────────────────────────────────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        return False  # At-least-once; idempotency via DB-level constraints

    async def mark_processed(self, event_id: str) -> None:
        pass

    # ── Retry / DLQ ───────────────────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        # FailureInfo[None] carries no structured payload — original message
        # values are not available for retry at this level.
        logger.warning(  # type: ignore[no-any-return]
            "article_consumer_retry_skipped",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "article_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "article_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "article_consumer_dead_lettered",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )
        try:
            async with self._nlp_sf() as session:
                dlq_repo = DLQRepository(session)
                # FailureInfo[None] carries no structured record; serialize event_id only.
                raw_bytes = json.dumps({"event_id": failure.event_id}).encode()
                event_uuid = uuid.UUID(failure.event_id) if _is_valid_uuid(failure.event_id) else common.ids.new_uuid7()
                await dlq_repo.move_to_dlq(
                    original_event_id=event_uuid,
                    topic=_TOPIC,
                    payload_avro=raw_bytes,
                    error_detail=str(failure.last_error)[:1024],
                )
                await session.commit()
        except Exception:
            logger.exception(  # type: ignore[no-any-return]
                "dead_letter_write_failed",
                event_id=failure.event_id,
            )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        # S5 dispatcher publishes content.article.stored.v1 as Confluent Avro wire format
        # (5-byte header: magic 0x00 + 4-byte schema ID).  Fall back to JSON for plain payloads.
        if schema_path and raw and raw[0:1] == b"\x00":
            from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

            return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _TOPIC:
            return str(_SCHEMA_DIR / "content.article.stored.v1.avsc")
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))


# ── Module-level helpers (pure functions) ────────────────────────────────────


def _write_section_embeddings(
    session: AsyncSession,
    section_embs: list[tuple[uuid.UUID, list[float]]],
    model_id: str,
) -> None:
    """Insert SectionEmbeddingModel rows (best-effort, no flush)."""
    for section_id, vec in section_embs:
        session.add(
            SectionEmbeddingModel(
                embedding_id=common.ids.new_uuid7(),
                section_id=section_id,
                embedding=vec,
                model_id=model_id,
            ),
        )


def _write_chunk_embeddings(
    session: AsyncSession,
    chunk_embs: list[tuple[uuid.UUID, list[float]]],
    model_id: str,
) -> None:
    """Insert ChunkEmbeddingModel rows (best-effort, no flush)."""
    for chunk_id, vec in chunk_embs:
        session.add(
            ChunkEmbeddingModel(
                embedding_id=common.ids.new_uuid7(),
                chunk_id=chunk_id,
                embedding=vec,
                model_id=model_id,
            ),
        )


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


async def _enqueue_enriched(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    doc_id: uuid.UUID,
    source_type: str,
    published_at: datetime | None,
    is_backfill: bool,
    routing_decision: RoutingDecision,
    sections: list[Section],
    chunks: list[Chunk],
    mentions: list[EntityMention],
    extraction_result: dict[str, Any],
    correlation_id: str | None,
) -> None:
    effective_tier = routing_decision.final_routing_tier or routing_decision.routing_tier
    resolved_ids = [str(m.resolved_entity_id) for m in mentions if m.resolved_entity_id is not None]
    payload: dict[str, Any] = {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "nlp.article.enriched",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc_id),
        "source_type": source_type,
        "published_at": published_at.isoformat() if published_at else None,
        "is_backfill": is_backfill,
        "routing_tier": effective_tier.value,
        "routing_score": routing_decision.composite_score,
        "section_count": len(sections),
        "chunk_count": len(chunks),
        "mention_count": len(mentions),
        "resolved_entity_ids": resolved_ids,
        "relation_count": len(list(extraction_result.get("relations", []))),
        "claim_count": len(list(extraction_result.get("claims", []))),
        "event_count": len(list(extraction_result.get("events", []))),
        "provisional_entity_count": sum(1 for m in mentions if m.resolved_entity_id is None),
        "correlation_id": correlation_id,
    }
    await outbox_repo.add(
        topic=settings.topic_article_enriched,
        partition_key=str(doc_id),
        payload_avro=json.dumps(payload).encode(),
    )


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False
