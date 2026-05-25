"""Article consumer — orchestrates S6 Blocks 3-10 (PRD §6.7).

Consumes ``content.article.stored.v1`` from S5.  For each message:

1.  Downloads clean article text from MinIO silver key.
2.  Runs Blocks 3-10: sectioning → NER → routing → suppression → embeddings
    → novelty → entity resolution → deep extraction.
3.  Writes all artifacts to nlp_db in one atomic transaction.
4.  Enqueues ``nlp.article.enriched.v1`` via the outbox (same transaction).
5.  Commits the Kafka offset only after the DB transaction succeeds.

Processing logic lives in ``blocks/`` sub-modules.  All helper symbols are
re-exported here so existing imports from this module remain valid.

NOTE ON TESTABILITY: ``serialize_confluent_avro``, ``SectionRepository``,
``ChunkRepository``, and ``OutboxRepository`` are imported at this module
level so unit tests can patch them via
``patch("...article_consumer.<name>")``.  The functions that use them
(``_emit_temporal_events``, ``_enqueue_document_ready``) are defined here
rather than in the block sub-modules for the same reason.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]
from nlp_pipeline.application.blocks.deep_extraction import run_deep_extraction_block
from nlp_pipeline.application.blocks.embeddings import run_embeddings_block
from nlp_pipeline.application.blocks.ner import run_ner_block
from nlp_pipeline.application.blocks.routing import compute_routing_score
from nlp_pipeline.application.blocks.sectioning import section_document
from nlp_pipeline.application.blocks.suppression import (
    apply_suppression_gate,
    should_generate_chunk_embeddings,
    should_run_deep_extraction,
)
from nlp_pipeline.domain.enums import ProcessingPath
from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
    EntityAliasRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
    EntityProfileEmbeddingRepository,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.embedding_writes import (
    _build_chunk_entity_mentions,
    _compute_chunk_mention_pairs,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event import (
    _build_raw_claims,
    _build_raw_events,
    _build_raw_relations,
    _enqueue_enriched,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.helpers import _normalize_ref_variants
from nlp_pipeline.infrastructure.messaging.consumers.blocks.ml_phase import MLPhaseResult, run_ml_phase
from nlp_pipeline.infrastructure.messaging.consumers.blocks.persist import persist_artifacts
from nlp_pipeline.infrastructure.messaging.consumers.blocks.provisional import (
    _collect_extraction_refs,
    synthesize_provisional_refs,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.signal_events import _enqueue_signal_events
from nlp_pipeline.infrastructure.messaging.consumers.blocks.storage import (
    download_article,
    extract_url_from_silver,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.temporal_events import (
    _TEMPORAL_EVENT_TYPE_DB_NAMES,
    _TEMPORAL_EVENT_TYPES,
    _infer_temporal_scope,
    _normalize_temporal_events_for_emit,
)
from nlp_pipeline.infrastructure.metrics.prometheus import (
    record_article_processed,
    s6_embeddings_created_total,
    s6_intel_commit_failures_total,
    s6_ner_mentions_total,
    s6_ollama_queue_depth_current,
)
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
from nlp_pipeline.infrastructure.nlp_db.repositories.routing_decision import RoutingDecisionRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.section import SectionRepository
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository as OutboxRepositoryT
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "content.article.stored.v1"
_SCHEMA_DIR = find_schema_dir()
_DEFAULT_SOURCE_TRUST = 0.5

# Re-export block helpers so existing imports from this module remain valid.
__all__ = [
    "ArticleProcessingConsumer",
    "MLPhaseResult",
    "_build_chunk_entity_mentions",
    "_build_raw_claims",
    "_build_raw_events",
    "_build_raw_relations",
    "_collect_extraction_refs",
    "_compute_chunk_mention_pairs",
    "_emit_temporal_events",
    "_enqueue_document_ready",
    "_enqueue_enriched",
    "_enqueue_signal_events",
    "_infer_temporal_scope",
    "_normalize_ref_variants",
    "_normalize_temporal_events_for_emit",
    "_SCHEMA_DIR",
    "synthesize_provisional_refs",
]


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


class _NoOpUnitOfWork:
    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


async def _emit_temporal_events(
    *,
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_entity_ids: frozenset[str],
    doc_id: uuid.UUID,
    published_at: datetime | None,
    outbox_repo: OutboxRepositoryT,
    settings: Any,
    schema_path: str | None = None,
) -> None:
    """Block 13E — publish ``intelligence.temporal_event.v1`` for macro/geo events.

    Defined here (not in blocks/temporal_events.py) so that unit tests can patch
    ``serialize_confluent_avro`` at this module's namespace and intercept the call.

    Filters to _TEMPORAL_EVENT_TYPES, skips confidence < 0.5, serializes as
    Confluent Avro, and writes one outbox row per qualifying event.
    PLAN-0084 QA D-009: deterministic UUID5 event_ids prevent duplicate outbox rows.
    """
    if schema_path is None:
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

        schema_path = get_schema_path("intelligence.temporal_event.v1.avsc")

    confidence_threshold = 0.5

    for _idx, evt in enumerate(raw_events):
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]

        # ── Filter 1: event_type must be temporal ────────────────────────────
        raw_type = str(evt_d.get("event_type", "")).upper()
        if raw_type not in _TEMPORAL_EVENT_TYPES:
            continue

        # ── Filter 2: confidence threshold ──────────────────────────────────
        confidence = float(evt_d.get("extraction_confidence", 0.0))
        if confidence < confidence_threshold:
            continue

        # ── Build exposed_entities (skip provisional IDs — S7 needs canonicals)
        participant_ids: list[str] = [str(pid) for pid in evt_d.get("participant_entity_ids", [])]
        exposed_entities: list[dict[str, Any]] = [
            {"entity_id": pid, "exposure_type": "directly_affected", "confidence": confidence}
            for pid in participant_ids
            if pid not in provisional_entity_ids
        ]

        scope = _infer_temporal_scope(raw_type)

        # PLAN-0084 QA D-009: deterministic UUID5 — deduplicates Kafka replays.
        te_event_id = uuid.UUID(uuid5_from_parts(str(doc_id), raw_type, str(_idx)))
        payload: dict[str, Any] = {
            "event_id": str(te_event_id),
            "event_type": "intelligence.temporal_event",
            "schema_version": 1,
            "occurred_at": common.time.utc_now().isoformat(),
            # BP-448: normalize LLM "REGULATORY_ACTION" → DB-valid "regulatory".
            "temporal_event_type": _TEMPORAL_EVENT_TYPE_DB_NAMES.get(raw_type, raw_type.lower()),
            "scope": scope,
            "region": "",
            "title": str(evt_d.get("event_text", ""))[:500],
            "description": "",
            "source_article_ids": [str(doc_id)],
            "source_url": "",
            "active_from": published_at.isoformat() if published_at else common.time.utc_now().isoformat(),
            "active_until": "",
            "residual_impact_days": 90,
            "confidence": confidence,
            "exposed_entities": exposed_entities,
        }

        payload_bytes = serialize_confluent_avro(schema_path, payload)

        await outbox_repo.add(
            topic=settings.topic_temporal_event,
            partition_key=raw_type,
            payload_avro=payload_bytes,
            event_id=te_event_id,
        )

        logger.debug(  # type: ignore[no-any-return]
            "temporal_event_enqueued",
            doc_id=str(doc_id),
            event_type=raw_type,
            scope=scope,
            confidence=confidence,
            exposed_entity_count=len(exposed_entities),
        )


async def _enqueue_document_ready(
    *,
    outbox_repo: OutboxRepositoryT,
    settings: Any,
    doc_id: uuid.UUID,
    tenant_id: uuid.UUID,
    chunk_count: int,
    word_count: int,
    schema_path: str | None = None,
) -> None:
    """Emit nlp.document.ready.v1 to outbox for tenant documents (PLAN-0086 Wave F-1).

    Defined here so tests can patch ``serialize_confluent_avro`` at this module.
    The event is written inside the nlp_session transaction — atomically with
    all NLP artifacts.  S4 DocumentReadyConsumer transitions upload→READY.
    PLAN-0084 B-3: deterministic UUID5 event_id deduplicates Kafka replays.
    """
    if schema_path is None:
        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]

        schema_path = get_schema_path("nlp.document.ready.v1.avsc")

    event_id = uuid.UUID(uuid5_from_parts(str(doc_id), "document_ready_v1"))
    payload: dict[str, Any] = {
        "event_id": str(event_id),
        "event_type": "nlp.document.ready",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc_id),
        "tenant_id": str(tenant_id),
        "chunk_count": chunk_count,
        "word_count": word_count,
    }
    payload_bytes = serialize_confluent_avro(schema_path, payload)
    await outbox_repo.add(
        topic="nlp.document.ready.v1",
        partition_key=str(tenant_id),
        payload_avro=payload_bytes,
        event_id=event_id,
    )


async def _maybe_emit_temporal_events(
    *,
    outbox_repo: OutboxRepositoryT,
    settings: Any,
    doc_id: uuid.UUID,
    published_at: datetime | None,
    ml: MLPhaseResult,
) -> None:
    """Emit intelligence.temporal_event.v1 outbox events if Block 10 produced events.

    Defined here so tests can patch ``_emit_temporal_events`` and
    ``serialize_confluent_avro`` at the ``article_consumer`` module namespace.
    """
    if not (should_run_deep_extraction(ml.final_path) and ml.extraction_result.get("events")):
        return

    te_ref: dict[str, str] = {}
    for _m in ml.final_mentions:
        if _m.resolved_entity_id is not None:
            for _v in _normalize_ref_variants(_m.mention_text):
                te_ref.setdefault(_v, str(_m.resolved_entity_id))
        elif _m.provisional_queue_id is not None:
            for _v in _normalize_ref_variants(_m.mention_text):
                te_ref.setdefault(_v, str(_m.provisional_queue_id))

    prov_ids: frozenset[str] = frozenset(
        str(_m.provisional_queue_id) for _m in ml.final_mentions if _m.provisional_queue_id is not None
    )
    normalized = _normalize_temporal_events_for_emit(ml.extraction_result.get("events", []), te_ref, prov_ids)
    if normalized:
        await _emit_temporal_events(
            raw_events=normalized,
            entity_id_by_ref=te_ref,
            provisional_entity_ids=prov_ids,
            doc_id=doc_id,
            published_at=published_at,
            outbox_repo=outbox_repo,
            settings=settings,
        )


class ArticleProcessingConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Orchestrates S6 Blocks 3-10.  Processing logic is in ``blocks/`` modules.

    Idempotency (PLAN-0084 B-3): ValkeyDedupMixin + deterministic IDs everywhere.
    """

    _dedup_prefix: str = "nlp:dedup:article_consumer"
    _dedup_ttl_seconds: ClassVar[int] = 86400

    def __init__(
        self,
        config: ConsumerConfig,
        settings: Settings,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        intelligence_session_factory: async_sessionmaker[AsyncSession],
        storage: Any,
        watchlist_cache: WatchlistCache,
        ner_client: NERClient,
        embedding_client: EmbeddingClient,
        extraction_client: ExtractionClient,
        backpressure: BackpressureController,
        chunk_text_store: ChunkTextStorePort | None = None,
        usage_logger: LlmUsageLogProtocol | None = None,
        valkey_client: ValkeyClient | None = None,
    ) -> None:
        super().__init__(config)
        self._dedup_client = valkey_client
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
        self._usage_logger = usage_logger

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    async def _download_article(self, minio_key: str) -> str:
        """Download and unpack article text from MinIO (Block 3 storage step).

        Defined as a method so tests can patch it via
        ``patch.object(consumer, "_download_article", ...)``.
        """
        return await download_article(self._storage, self._settings.silver_bucket, minio_key)

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
        """Upsert citation metadata to nlp_db.document_source_metadata (best-effort).

        Defined as a method so tests can patch
        ``SQLAlchemyDocumentSourceMetadataRepository`` at this module namespace.
        Any exception is swallowed so NLP processing is never blocked by a
        metadata write failure.
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
            logger.warning("source_metadata_write_failed", doc_id=str(doc_id), exc_info=True)  # type: ignore[no-any-return]

    async def process_message(self, key: str | None, value: dict[str, Any], headers: dict[str, str]) -> None:
        """Orchestrate all 8 blocks for one article event."""
        doc_id = uuid.UUID(str(value["doc_id"]))
        minio_key = str(value["minio_silver_key"])
        source_type = str(value["source_type"])
        is_backfill = bool(value.get("is_backfill", False))
        correlation_id: str | None = value.get("correlation_id") or None
        source_name: str | None = value.get("source_name")

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
        doc_title: str | None = str(value["title"]) if value.get("title") is not None else None

        # F-MAJOR-001: idempotency check BEFORE acquiring the backpressure semaphore.
        async with self._nlp_sf() as check_session:
            if await RoutingDecisionRepository(check_session).get_by_doc(doc_id) is not None:
                logger.info("article_consumer.skip_already_processed", doc_id=str(doc_id))  # type: ignore[no-any-return]
                return

        async with self._bp:
            await self._run_pipeline(
                doc_id=doc_id,
                minio_key=minio_key,
                source_type=source_type,
                source_name=source_name,
                published_at=published_at,
                extracted_at=extracted_at,
                is_backfill=is_backfill,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                doc_title=doc_title,
            )

        url = value.get("url") or await extract_url_from_silver(self._storage, self._settings.silver_bucket, minio_key)
        await self._write_source_metadata(
            doc_id=doc_id,
            title=value.get("title"),
            url=url,
            published_at=published_at,
            source_name=source_name,
            source_type=source_type,
            word_count=value.get("word_count"),
        )

    async def _run_pipeline(
        self,
        *,
        doc_id: uuid.UUID,
        minio_key: str,
        source_type: str,
        source_name: str | None = None,
        published_at: datetime | None,
        extracted_at: datetime,
        is_backfill: bool,
        correlation_id: str | None,
        tenant_id: uuid.UUID | None = None,
        doc_title: str | None = None,
    ) -> None:
        """Download text and run Blocks 3-10 with D-004 dual-DB commit ordering."""

        # Block 3: Sectioning
        text = await self._download_article(minio_key)
        word_count: int = len(text.split())

        # RC-1: stub-article filter — skip articles below the minimum word count.
        # Finnhub (~91% stub rate) and SEC Edgar (~52% stub rate) frequently emit
        # headline-only records that have no relational signal but consume NER,
        # embedding, and LLM extraction budget. The word count is computed on the
        # raw downloaded text (not the message envelope field) because the envelope
        # field may be absent or stale for older events. Early return prevents all
        # downstream blocks from running; the document remains in content_store but
        # is not indexed in the NLP pipeline.
        if word_count < self._settings.min_word_count:
            logger.info(  # type: ignore[no-any-return]
                "article_consumer.stub_filtered",
                doc_id=str(doc_id),
                word_count=word_count,
                min_word_count=self._settings.min_word_count,
                source_type=source_type,
            )
            return

        sections = section_document(doc_id, text, source_type)
        if tenant_id is not None:
            sections = [dataclasses.replace(s, tenant_id=tenant_id) for s in sections]

        # Block 4: NER + deterministic mention IDs (PLAN-0084 B-3).
        # PLAN-0093 B-3 T-B-3-04: pass tenant_id through so EntityMention is
        # constructed with it (avoids the post-construction stamp going
        # missing in any future refactor).  The explicit post-construction
        # stamp below is retained as a belt-and-braces safeguard.
        mentions, stats = await run_ner_block(
            doc_id=doc_id,
            sections=sections,
            ner_client=self._ner,
            threshold=self._settings.gliner_threshold,
            batch_size=self._settings.gliner_batch_size,
            ner_model_id=self._settings.ner_model_id,
            section_token_limit=self._settings.gliner_section_token_limit,
            tenant_id=tenant_id,
        )
        for _i, m in enumerate(mentions):
            m.mention_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(_i), m.mention_text.lower().strip()))
        if tenant_id is not None:
            for m in mentions:
                m.tenant_id = tenant_id
        s6_ner_mentions_total.inc(len(mentions))

        # Blocks 5-6: Routing + suppression
        # PLAN-0093 C-1: watched_ids + price_impact no longer feed compute_routing_score
        # (the 3 dead signals are dropped). watched_ids is still fetched downstream for
        # other features, so we keep the call. price_impact lookup is dropped here — it
        # was always returning 0.0 anyway (article_impact_windows is empty until C-3).
        routing_decision = compute_routing_score(
            doc_id=doc_id,
            decision_id=uuid.UUID(uuid5_from_parts(str(doc_id), "routing_decision")),
            source_type=source_type,
            published_at=published_at,
            extracted_at=extracted_at,
            mentions=mentions,
            section_count=len(sections),
            source_trust_weight=_DEFAULT_SOURCE_TRUST,
            tier_deep=self._settings.routing_tier_deep,
            tier_medium=self._settings.routing_tier_medium,
            tier_light=self._settings.routing_tier_light,
        )
        initial_path = apply_suppression_gate(routing_decision)

        # Block 7: Embeddings + denorm fields (PLAN-0063 W5-2)
        chunks, chunk_embs, section_embs, pending = await run_embeddings_block(
            sections=sections,
            embedding_client=self._emb,
            model_id=self._settings.embedding_model_id,
            instruction_prefix=self._settings.embedding_instruction_prefix,
            generate_chunk_embeddings=should_generate_chunk_embeddings(initial_path),
            chunk_text_store=self._chunk_text_store,
        )
        if chunks:
            s_heading = {s.section_id: s.title for s in sections}
            chunks = [
                dataclasses.replace(
                    c, title_denorm=doc_title, section_heading_denorm=s_heading.get(c.section_id), tenant_id=tenant_id
                )
                for c in chunks
            ]
        s6_embeddings_created_total.inc(len(chunk_embs) + len(section_embs))

        # Blocks 8-10 + atomic DB write with D-004 dual-session ordering.
        # ALL repositories are constructed here (in article_consumer namespace)
        # so tests can patch them via patch("...article_consumer.FooRepository").
        async with self._nlp_sf() as nlp_s, self._intel_sf() as intel_s:
            section_repo = SectionRepository(nlp_s)
            chunk_repo = ChunkRepository(nlp_s)
            outbox_repo = OutboxRepository(nlp_s)
            routing_decision_repo = RoutingDecisionRepository(nlp_s)
            entity_mention_repo = EntityMentionRepository(nlp_s)
            doc_entity_stats_repo = DocumentEntityStatsRepository(nlp_s)
            chunk_entity_mention_repo = ChunkEntityMentionRepository(nlp_s)
            mention_resolution_repo = MentionResolutionRepository(nlp_s)
            entity_alias_repo = EntityAliasRepository(intel_s)
            entity_profile_emb_repo = EntityProfileEmbeddingRepository(intel_s)
            canonical_entity_repo = CanonicalEntityRepository(intel_s)

            # Pass run_deep_extraction_block from THIS module so tests can
            # patch "article_consumer.run_deep_extraction_block" and intercept.
            # Pass intel repos pre-built so tests can patch them at article_consumer.
            ml = await run_ml_phase(
                nlp_session=nlp_s,
                intel_session=intel_s,
                doc_id=doc_id,
                chunks=chunks,
                mentions=mentions,
                routing_decision=routing_decision,
                initial_path=initial_path,
                published_at=published_at,
                extracted_at=extracted_at,
                settings=self._settings,
                emb=self._emb,
                ext=self._ext,
                watchlist_client=self._watchlist._client,  # type: ignore[attr-defined]
                usage_logger=self._usage_logger,
                _deep_extraction_fn=run_deep_extraction_block,
                _alias_repo=entity_alias_repo,
                _profile_emb_repo=entity_profile_emb_repo,
                _canonical_repo=canonical_entity_repo,
                _mention_resolution_repo=mention_resolution_repo,
            )
            # persist_artifacts writes only DB rows; event emission is below
            # so tests can patch _enqueue_enriched etc. at article_consumer.
            # Pass pre-built repos so tests can patch them at article_consumer.
            routing_decision, chunks, final_mentions, outbox_repo = await persist_artifacts(
                nlp_session=nlp_s,
                section_repo=section_repo,
                chunk_repo=chunk_repo,
                outbox_repo=outbox_repo,
                routing_decision_repo=routing_decision_repo,
                entity_mention_repo=entity_mention_repo,
                doc_entity_stats_repo=doc_entity_stats_repo,
                chunk_entity_mention_repo=chunk_entity_mention_repo,
                mention_resolution_repo=mention_resolution_repo,
                doc_id=doc_id,
                sections=sections,
                stats=stats,
                chunks=chunks,
                chunk_embs=chunk_embs,
                section_embs=section_embs,
                pending=pending,
                gliner_mention_floor=self._settings.gliner_mention_floor,
                settings=self._settings,
                ml=ml,
            )

            # ── Outbox event emission (all within the open nlp_s transaction) ──
            # W1-01 (BUG-001): SUPPRESS-tier articles (ProcessingPath.HALT) must NOT
            # emit nlp.article.enriched.v1 — S7 would consume an empty document and
            # pollute the knowledge graph with dead-weight relations from zero-
            # extraction documents.  We also skip signal events and temporal events
            # because both require extraction output that does not exist on HALT
            # (deep extraction is gated by should_run_deep_extraction(HALT)==False
            # so ml.extraction_result["events"] is empty and ml.signals is empty).
            # Block 8 (price-impact labelling) is a SEPARATE worker (see
            # workers/price_impact_labelling_worker.py) and still runs against the
            # routing_decisions row written by persist_artifacts above — this gate
            # only affects the three outbox emissions below.
            if ml.final_path == ProcessingPath.HALT:
                tier_value = (
                    routing_decision.routing_tier.value
                    if hasattr(routing_decision.routing_tier, "value")
                    else routing_decision.routing_tier
                )
                logger.info(  # type: ignore[no-any-return]
                    "article_suppressed_skipping_enriched_event",
                    doc_id=str(doc_id),
                    routing_tier=tier_value,
                )
            else:
                await _enqueue_enriched(
                    outbox_repo=outbox_repo,
                    settings=self._settings,
                    doc_id=doc_id,
                    source_type=source_type,
                    source_name=source_name,
                    published_at=published_at,
                    is_backfill=is_backfill,
                    routing_decision=routing_decision,
                    sections=sections,
                    chunks=chunks,
                    mentions=final_mentions,
                    extraction_result=ml.extraction_result,
                    correlation_id=correlation_id,
                    extraction_model_id=(
                        self._settings.extraction_model_id if should_run_deep_extraction(ml.final_path) else None
                    ),
                )
                if ml.signals:
                    await _enqueue_signal_events(
                        outbox_repo=outbox_repo,
                        settings=self._settings,
                        signals=ml.signals,
                        doc_id=doc_id,
                        is_backfill=is_backfill,
                        correlation_id=correlation_id,
                    )
                await _maybe_emit_temporal_events(
                    outbox_repo=outbox_repo,
                    settings=self._settings,
                    doc_id=doc_id,
                    published_at=published_at,
                    ml=ml,
                )
            if tenant_id is not None:
                await _enqueue_document_ready(
                    outbox_repo=outbox_repo,
                    settings=self._settings,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    chunk_count=len(chunks),
                    word_count=word_count,
                )

            # D-004: Commit NLP FIRST so intel rollback is still safe on failure
            try:
                await nlp_s.commit()
            except Exception:
                logger.warning("nlp_commit_failed_intel_writes_rolled_back", doc_id=str(doc_id), exc_info=True)  # type: ignore[no-any-return]
                raise
            try:
                await intel_s.commit()
            except Exception:
                s6_intel_commit_failures_total.inc()
                logger.error("d004_intel_commit_failed", doc_id=str(doc_id), exc_info=True)  # type: ignore[no-any-return]
                raise

        tier = (routing_decision.final_routing_tier or routing_decision.routing_tier).value
        logger.info(
            "article_processed",
            doc_id=str(doc_id),
            routing_tier=tier,  # type: ignore[no-any-return]
            section_count=len(sections),
            chunk_count=len(chunks),
            mention_count=len(final_mentions),
        )
        record_article_processed(tier)
        s6_ollama_queue_depth_current.set(self._bp.gauge_value())

    async def _fetch_price_impact(self, doc_id: uuid.UUID) -> float:
        """Block 5: fetch price_impact. Best-effort; 0.0 on error."""
        try:
            from nlp_pipeline.infrastructure.nlp_db.repositories.impact_window import ArticleImpactWindowRepository

            async with self._nlp_sf() as s:
                return float(await ArticleImpactWindowRepository(s).get_max_impact_for_doc(doc_id))
        except Exception:
            logger.warning("price_impact_lookup_failed", doc_id=str(doc_id), exc_info=True)  # type: ignore[no-any-return]
            return 0.0

    # ── Kafka consumer lifecycle ───────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning("article_consumer_retry_skipped", event_id=failure.event_id, attempt=failure.attempt)  # type: ignore[no-any-return]

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error("article_consumer_failure", event_id=failure.event_id, error=str(failure.last_error))  # type: ignore[no-any-return]

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning("article_consumer_failure_retry", event_id=failure.event_id, attempt=failure.attempt)  # type: ignore[no-any-return]

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error("article_consumer_dead_lettered", event_id=failure.event_id, error=str(failure.last_error))  # type: ignore[no-any-return]
        try:
            async with self._nlp_sf() as session:
                event_uuid = uuid.UUID(failure.event_id) if _is_valid_uuid(failure.event_id) else common.ids.new_uuid7()
                diagnostic_bytes = failure.event_id.encode("utf-8")
                await DLQRepository(session).move_to_dlq(
                    original_event_id=event_uuid,
                    topic=_TOPIC,
                    payload_avro=diagnostic_bytes,
                    error_detail=str(failure.last_error)[:1024],
                )
                await session.commit()
        except Exception:
            logger.exception("dead_letter_write_failed", event_id=failure.event_id)  # type: ignore[no-any-return]

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
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
