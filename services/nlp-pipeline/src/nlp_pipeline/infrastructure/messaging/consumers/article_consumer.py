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

import contextlib
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
from nlp_pipeline.infrastructure.metrics.prometheus import (
    record_article_processed,
    record_entity_resolved,
    s6_claims_extracted_total,
    s6_embeddings_created_total,
    s6_ner_mentions_total,
    s6_ollama_queue_depth_current,
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


# Walk up the directory tree to find infra/kafka/schemas/ — works both in development
# (repo root is a few levels up) and in Docker (schemas copied to /app/infra/kafka/schemas/).
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()

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

        # F-009: Extract tenant_id from Kafka headers or event value if present.
        # Articles are platform-global but entity_mentions need tenant isolation.
        raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None
        tenant_id: uuid.UUID | None = None
        if raw_tenant:
            with contextlib.suppress(ValueError, AttributeError):
                tenant_id = uuid.UUID(str(raw_tenant))

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

        # F-MAJOR-001: Idempotency check BEFORE acquiring the backpressure
        # semaphore.  On re-delivery of an already-processed message the slot
        # would otherwise be wasted, reducing throughput for real work.
        async with self._nlp_sf() as check_session:
            check_routing_repo = RoutingDecisionRepository(check_session)
            if await check_routing_repo.get_by_doc(doc_id) is not None:
                logger.info(  # type: ignore[no-any-return]
                    "article_consumer.skip_already_processed",
                    doc_id=str(doc_id),
                )
                return

        async with self._bp:
            await self._run_pipeline(
                doc_id=doc_id,
                minio_key=minio_key,
                source_type=source_type,
                published_at=published_at,
                extracted_at=extracted_at,
                is_backfill=is_backfill,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
            )

        # Best-effort: cache citation metadata for S8 RAG inline citations.
        # Failure must never cause NLP processing to fail.
        # url and source_name are not in the content.article.stored.v1 Avro schema;
        # fall back to reading source_url from the silver JSON envelope.
        url = value.get("url") or await self._extract_url_from_silver(minio_key)
        await self._write_source_metadata(
            doc_id=doc_id,
            title=value.get("title"),
            url=url,
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
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        """Download text and run Blocks 3-10 with D-004 dual-DB commit ordering.

        D-004 session lifecycle invariant:
          Both nlp_session and intel_session are opened at the top of the DB
          write phase.  nlp_session is committed FIRST.  If that commit fails,
          intel_session rolls back automatically via its context manager
          __aexit__.  If intel_session commit fails AFTER nlp_session committed,
          the error is logged but NOT re-raised — intel writes (provisional
          entity queue inserts) are idempotent on retry thanks to the UNIQUE
          constraint on (normalized_surface, mention_class).

        NOTE: The idempotency check (routing_decision exists?) is performed in
        ``process_message`` BEFORE the backpressure semaphore is acquired so
        that re-delivered messages do not waste a concurrency slot.
        """

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
            ner_model_id=self._settings.ner_model_id,
            section_token_limit=self._settings.gliner_section_token_limit,
        )

        # F-009: Stamp tenant_id from Kafka envelope onto every mention so
        # entity_mentions can be filtered by tenant at query time.
        if tenant_id is not None:
            for mention in mentions:
                mention.tenant_id = tenant_id

        s6_ner_mentions_total.inc(len(mentions))

        # ── Block 5: Routing score (initial, novelty_score=0.0 provisional) ───
        watched_ids = await self._watchlist.get_all_watched()

        # Fetch price_impact signal — best-effort; defaults to 0.0 for articles
        # < 25h old (not yet labelled) or on any lookup error (PRD-0026 §6.7).
        # Queries article_impact_windows (multi-window table, migration 0009).
        price_impact_score = 0.0
        try:
            from nlp_pipeline.infrastructure.nlp_db.repositories.impact_window import (
                ArticleImpactWindowRepository,
            )

            async with self._nlp_sf() as impact_session:
                impact_repo = ArticleImpactWindowRepository(impact_session)
                max_impact = await impact_repo.get_max_impact_for_doc(doc_id)
                price_impact_score = float(max_impact)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "price_impact_lookup_failed",
                doc_id=str(doc_id),
                exc_info=True,
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
            novelty_score=1.0,  # Assume novel for initial routing; Block 8 novelty gate downgrades near-duplicates
            watched_entity_ids=watched_ids,
            price_impact_score=price_impact_score,
            tier_deep=self._settings.routing_tier_deep,
            tier_medium=self._settings.routing_tier_medium,
            tier_light=self._settings.routing_tier_light,
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

        s6_embeddings_created_total.inc(len(chunk_embs) + len(section_embs))

        # ── D-004: Open BOTH sessions at the top level ───────────────────────
        # intel_session is used by Block 8 (novelty gate reads) and Block 9
        # (entity resolution reads + provisional queue writes).
        # nlp_session owns all NLP artifact writes + outbox.
        # Commit order: nlp_session FIRST, then intel_session (best-effort).
        async with self._nlp_sf() as nlp_session, self._intel_sf() as intel_session:
            # ── Block 8: Novelty gate (skip for HALT — can't downgrade further)
            final_path = initial_path
            if initial_path != ProcessingPath.HALT:
                # D-004: use the top-level intel_session — no nested context
                # manager, so the session stays open until the coordinated
                # commit sequence below.
                ep_repo = EntityProfileEmbeddingRepository(intel_session)
                routing_decision, _novelty_score = await run_novelty_gate(
                    doc_id=doc_id,
                    routing_decision=routing_decision,
                    valkey_client=self._watchlist._client,  # type: ignore[attr-defined]
                    entity_profile_embedding_repo=ep_repo,
                    resolved_entity_ids=[],
                    entity_embeddings={},
                    minhash_threshold=self._settings.novelty_minhash_threshold,
                    embedding_threshold=self._settings.novelty_embedding_threshold,
                )
                final_path = apply_suppression_gate(routing_decision)

            # ── Blocks 9+10 and atomic DB write ──────────────────────────────
            extraction_result: dict[str, Any] = {"events": [], "claims": [], "relations": []}
            final_mentions = list(mentions)

            # Block 9: Entity resolution (reads intel_db, writes audit to nlp_session)
            # D-004: use the top-level intel_session — no nested context manager.
            if should_run_entity_resolution(final_path):
                alias_repo = EntityAliasRepository(intel_session)
                ep_repo2 = EntityProfileEmbeddingRepository(intel_session)
                canon_repo = CanonicalEntityRepository(intel_session)
                # MentionResolutionRepository writes audit trail to nlp_db.
                mr_repo = MentionResolutionRepository(nlp_session)

                resolved_mentions, resolution_audit = await run_entity_resolution_block(
                    mentions=mentions,
                    alias_repo=alias_repo,
                    embedding_repo=ep_repo2,
                    canonical_entity_repo=canon_repo,
                    resolution_audit_repo=mr_repo,
                    embedding_client=self._emb,
                    intelligence_session=intel_session,
                    model_id=self._settings.embedding_model_id,
                    instruction_prefix=self._settings.embedding_instruction_prefix,
                    auto_resolve_threshold=self._settings.entity_resolution_auto_resolve_threshold,
                    provisional_threshold=self._settings.entity_resolution_provisional_threshold,
                )
                final_mentions = resolved_mentions
                # stage: 1=exact, 2=ticker, 3=fuzzy, 4=ann
                _stage_to_method = {1: "exact", 2: "ticker", 3: "fuzzy", 4: "ann"}
                for res in resolution_audit:
                    if res.is_winner:
                        record_entity_resolved(_stage_to_method.get(res.stage, "unknown"))

            # Block 10: Deep LLM extraction (writes claims to outbox via nlp_session)
            from nlp_pipeline.infrastructure.intelligence_db.repositories.claims import (
                ClaimsRepository,
            )

            claims_repo = ClaimsRepository(nlp_session)
            signals: list = []
            if should_run_deep_extraction(final_path):
                extraction_result, signals = await run_deep_extraction_block(
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

            if should_run_deep_extraction(final_path):
                s6_claims_extracted_total.inc(len(list(extraction_result.get("claims", []))))

            # Write all artifacts to nlp_db
            section_repo = SectionRepository(nlp_session)
            chunk_repo = ChunkRepository(nlp_session)
            mention_repo = EntityMentionRepository(nlp_session)
            stats_repo = DocumentEntityStatsRepository(nlp_session)
            routing_repo = RoutingDecisionRepository(nlp_session)
            cem_repo = ChunkEntityMentionRepository(nlp_session)
            outbox_repo = OutboxRepository(nlp_session)

            await section_repo.add_batch(sections)
            await chunk_repo.add_batch(chunks)
            await mention_repo.add_batch(final_mentions)
            await stats_repo.upsert(stats)
            await routing_repo.add(routing_decision)

            # Write embeddings directly (no dedicated repo)
            _write_section_embeddings(nlp_session, section_embs, model_id=self._settings.embedding_model_id)
            _write_chunk_embeddings(nlp_session, chunk_embs, model_id=self._settings.embedding_model_id)

            # Persist failed embeddings for retry by EmbeddingRetryWorker
            if pending:
                from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
                    EmbeddingPendingRepository,
                )

                pending_repo = EmbeddingPendingRepository(nlp_session)
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
                extraction_model_id=(
                    self._settings.extraction_model_id if should_run_deep_extraction(final_path) else None
                ),
            )

            # Enqueue signal events (nlp.signal.detected.v1) — must be inside the
            # same transaction so signals are never lost on commit failure.
            if signals:
                await _enqueue_signal_events(
                    outbox_repo=outbox_repo,
                    settings=self._settings,
                    signals=signals,
                    doc_id=doc_id,
                    is_backfill=is_backfill,
                    correlation_id=correlation_id,
                )

            # ── D-004: Commit NLP FIRST, then intel ──────────────────────────
            # If nlp_session.commit() fails, intel_session rolls back
            # automatically via its context manager __aexit__ (no orphaned
            # intel writes).  The exception propagates up for Kafka retry.
            try:
                await nlp_session.commit()
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "nlp_commit_failed_intel_writes_rolled_back",
                    doc_id=str(doc_id),
                    exc_info=True,
                )
                raise

            # Intel commit (best-effort — idempotent on retry).
            # NLP is already committed; if intel fails the provisional queue
            # inserts will be retried on next article re-delivery.
            try:
                await intel_session.commit()
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "d004_intel_commit_failed",
                    doc_id=str(doc_id),
                    exc_info=True,
                )
                # DON'T re-raise — NLP is committed; intel writes are
                # idempotent on retry (provisional_entity_queue has
                # UNIQUE constraint on (normalized_surface, mention_class)).

        _final_tier = (routing_decision.final_routing_tier or routing_decision.routing_tier).value
        logger.info(  # type: ignore[no-any-return]
            "article_processed",
            doc_id=str(doc_id),
            routing_tier=_final_tier,
            section_count=len(sections),
            chunk_count=len(chunks),
            mention_count=len(final_mentions),
        )
        record_article_processed(_final_tier)
        # Update backpressure depth gauge after each article so /metrics reflects
        # current queue depth without requiring a separate polling task.
        s6_ollama_queue_depth_current.set(self._bp.gauge_value())

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

    async def _extract_url_from_silver(self, minio_key: str) -> str | None:
        """Best-effort: extract source_url from the silver JSON envelope.

        The silver object written by content-store includes ``source_url``
        which is the original article URL. Falls back to None on any error.
        """
        if self._storage is None:
            return None
        try:
            raw = await self._storage.get_bytes(self._settings.silver_bucket, minio_key)
            envelope = json.loads(raw)
            if isinstance(envelope, dict):
                return envelope.get("source_url") or None
        except Exception:
            return None
        return None

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
    extraction_model_id: str | None = None,
) -> None:
    effective_tier = routing_decision.final_routing_tier or routing_decision.routing_tier
    resolved_ids = [str(m.resolved_entity_id) for m in mentions if m.resolved_entity_id is not None]

    # Build entity_id lookup from resolved mentions so extraction results
    # (which use entity_ref text names) can be mapped to canonical UUIDs
    # that S7 (knowledge-graph) expects in raw_relations/raw_events/raw_claims.
    entity_id_by_ref: dict[str, str] = {}
    for m in mentions:
        if m.resolved_entity_id is not None:
            entity_id_by_ref[m.mention_text.lower()] = str(m.resolved_entity_id)

    raw_relations = _build_raw_relations(extraction_result.get("relations", []), entity_id_by_ref)
    raw_events = _build_raw_events(extraction_result.get("events", []), entity_id_by_ref)
    raw_claims = _build_raw_claims(extraction_result.get("claims", []), entity_id_by_ref)

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
        # KG-001 fix: include actual extracted data arrays for S7 graph materialization.
        # Keep counts for backwards compatibility with existing consumers / dashboards.
        "relation_count": len(list(extraction_result.get("relations", []))),
        "claim_count": len(list(extraction_result.get("claims", []))),
        "event_count": len(list(extraction_result.get("events", []))),
        "raw_relations": raw_relations,
        "raw_events": raw_events,
        "raw_claims": raw_claims,
        "provisional_entity_count": sum(1 for m in mentions if m.resolved_entity_id is None),
        "extraction_model_id": extraction_model_id,
        "correlation_id": correlation_id,
    }
    await outbox_repo.add(
        topic=settings.topic_article_enriched,
        partition_key=str(doc_id),
        payload_avro=json.dumps(payload).encode(),
    )


def _build_raw_relations(
    relations: list[Any],
    entity_id_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction relations into the dict format S7 expects.

    S7's ``_parse_raw_relations`` requires ``subject_entity_id``, ``object_entity_id``,
    and ``raw_type``.  Skips relations where either entity ref cannot be resolved.
    """
    result: list[dict[str, Any]] = []
    for rel in relations:
        rel_d: dict[str, Any] = dict(rel) if not isinstance(rel, dict) else rel  # type: ignore[call-overload]
        subject_ref = str(rel_d.get("subject_ref", "")).lower()
        object_ref = str(rel_d.get("object_ref", "")).lower()
        subject_id = entity_id_by_ref.get(subject_ref)
        object_id = entity_id_by_ref.get(object_ref)
        if subject_id is None or object_id is None:
            continue  # skip unresolved — S7 cannot materialize without entity UUIDs
        result.append(
            {
                "subject_entity_id": subject_id,
                "object_entity_id": object_id,
                "raw_type": str(rel_d.get("predicate", "")),
                "extraction_confidence": float(rel_d.get("confidence", 0.5)),
                "entity_provisional": bool(rel_d.get("entity_provisional", False)),
                "provisional_queue_id": rel_d.get("provisional_queue_id"),
            }
        )
    return result


def _build_raw_events(
    events: list[Any],
    entity_id_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction events into the dict format S7 expects.

    S7's ``_parse_raw_events`` requires ``subject_entity_id`` and ``event_type``.
    Uses the first resolvable entity_ref as subject.  Skips events with no
    resolvable entity.
    """
    result: list[dict[str, Any]] = []
    for evt in events:
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]
        # Find the first resolvable entity ref from the entity_refs list
        entity_refs = evt_d.get("entity_refs", [])
        subject_id: str | None = None
        participant_ids: list[str] = []
        for ref in entity_refs:  # type: ignore[union-attr]
            eid = entity_id_by_ref.get(str(ref).lower())
            if eid is not None:
                if subject_id is None:
                    subject_id = eid
                participant_ids.append(eid)
        if subject_id is None:
            continue  # skip unresolved
        result.append(
            {
                "subject_entity_id": subject_id,
                "event_type": str(evt_d.get("event_type", "")),
                "event_text": str(evt_d.get("description", "")),
                "extraction_confidence": float(evt_d.get("confidence", 0.5)),
                "participant_entity_ids": participant_ids,
            }
        )
    return result


def _build_raw_claims(
    claims: list[Any],
    entity_id_by_ref: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction claims into the dict format S7 expects.

    S7's ``_parse_raw_claims`` requires ``subject_entity_id`` and ``claim_type``.
    Skips claims where the entity ref cannot be resolved.
    """
    result: list[dict[str, Any]] = []
    for claim in claims:
        claim_d: dict[str, Any] = dict(claim) if not isinstance(claim, dict) else claim  # type: ignore[call-overload]
        entity_ref = str(claim_d.get("entity_ref", "")).lower()
        subject_id = entity_id_by_ref.get(entity_ref)
        if subject_id is None:
            continue  # skip unresolved
        result.append(
            {
                "subject_entity_id": subject_id,
                "claim_type": str(claim_d.get("claim_type", "")),
                "polarity": str(claim_d.get("polarity", "neutral")),
                "claim_text": str(claim_d.get("evidence_text", "")),
                "extraction_confidence": float(claim_d.get("confidence", 0.5)),
            }
        )
    return result


async def _enqueue_signal_events(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    signals: list,
    doc_id: uuid.UUID,
    is_backfill: bool,
    correlation_id: str | None,
) -> None:
    """Write nlp.signal.detected.v1 events to the outbox for each high-confidence signal.

    One outbox record per signal.  The partition key is the entity_id so that
    S10 (alert service) fans out per-entity.  market_impact_score defaults to 0.0
    here; it is updated later by PriceImpactLabellingWorker (PLAN-0020).
    """
    for signal in signals:
        payload: dict[str, Any] = {
            "event_id": str(signal.signal_id),
            "event_type": "nlp.signal.detected",
            "schema_version": 1,
            "occurred_at": signal.detected_at.isoformat(),
            "doc_id": str(signal.doc_id),
            "claim_id": str(signal.signal_id),
            "claimer_entity_id": None,
            "subject_entity_id": str(signal.entity_id),
            "claim_type": signal.signal_type,
            "polarity": "neutral",
            "extraction_confidence": float(signal.confidence),
            "is_backfill": is_backfill,
            "correlation_id": correlation_id,
            "market_impact_score": 0.0,
        }
        await outbox_repo.add(
            topic=settings.topic_signal_detected,
            partition_key=str(signal.entity_id),
            payload_avro=json.dumps(payload).encode(),
        )


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False
