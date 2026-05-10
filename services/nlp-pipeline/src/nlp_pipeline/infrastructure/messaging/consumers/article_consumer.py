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
import dataclasses
import json
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore[import-untyped]

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from contracts.events.nlp.article_enriched import encode_raw_array  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import (  # type: ignore[import-untyped]
    find_schema_dir,
    get_schema_path,
)
from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
    serialize_confluent_avro,
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
    s6_extraction_entity_ref_hallucinated_total,
    s6_intel_commit_failures_total,
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
from storage.key_builder import KeyBuilder  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
    from nlp_pipeline.config import Settings
    from nlp_pipeline.domain.models import Chunk, EntityMention, RoutingDecision, Section
    from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

# PLAN-0062 F-006: producer-side R28 enforcement — emit Confluent-Avro framed
# bytes for ``nlp.signal.detected.v1`` instead of raw ``json.dumps(...).encode()``.
_NLP_SIGNAL_DETECTED_SCHEMA_PATH = get_schema_path("nlp.signal.detected.v1.avsc")

# Block 13E: schema path for the temporal-event outbox topic (intelligence.temporal_event.v1).
# The schema lives alongside all other Avro schemas in the infra/kafka/schemas/ dir.
_TEMPORAL_EVENT_SCHEMA_PATH = get_schema_path("intelligence.temporal_event.v1.avsc")

# PLAN-0086 Wave F-1: schema path for the nlp.document.ready.v1 outbox event.
# Emitted after tenant documents are fully processed so S4 can mark them READY.
_NLP_DOCUMENT_READY_SCHEMA_PATH = get_schema_path("nlp.document.ready.v1.avsc")

# Block 13E: event_type values produced by Block 10 deep extraction that
# represent a temporal / macro-geopolitical scope requiring S7 KG linking.
# Any event whose event_type is NOT in this set is skipped by _emit_temporal_events.
_TEMPORAL_EVENT_TYPES: frozenset[str] = frozenset(
    {"MACRO", "REGULATORY_ACTION", "GEOPOLITICAL", "SANCTIONS", "NATURAL_DISASTER"}
)

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "content.article.stored.v1"


_SCHEMA_DIR = find_schema_dir()

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


class ArticleProcessingConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Orchestrates S6 Blocks 3-10 for each incoming stored article.

    All ML clients and repository factories are injected at construction time.

    Idempotency strategy (PLAN-0084 B-3)
    -------------------------------------
    This consumer uses ``ValkeyDedupMixin`` for fast-path dedup (Valkey
    SET with 24h TTL).  The mixin's at-least-once fallback is safe because
    every downstream write uses a deterministic ID (``uuid5_from_parts``) or
    ``INSERT ... ON CONFLICT DO NOTHING``:

    - ``routing_decisions.decision_id``  — ``uuid5_from_parts(doc_id, "routing_decision")``
    - ``entity_mentions.mention_id``     — ``uuid5_from_parts(doc_id, idx, surface)``
    - ``section_embeddings.embedding_id``— ``uuid5_from_parts(doc_id, section_id, model_id)``
    - ``chunk_embeddings.embedding_id``  — ``uuid5_from_parts(doc_id, chunk_id, model_id)``
    - outbox ``event_id`` for ``nlp.article.enriched.v1`` — ``uuid5_from_parts(doc_id, "article_enriched_v1")``
    - outbox ``event_id`` for ``nlp.signal.detected.v1``  — ``uuid5_from_parts(doc_id, signal_kind, signal_idx)``
    - outbox ``event_id`` for ``intelligence.temporal_event.v1`` — ``uuid5_from_parts(doc_id, raw_type, str(loop_idx))``

    Cross-reference: R9 (STANDARDS.md §3.11), PLAN-0084 Wave B-3.
    """

    # ── ValkeyDedupMixin class attributes (PLAN-0084 B-3) ────────────────────
    # Unique key prefix ensures no collision with other consumers' dedup sets.
    _dedup_prefix: str = "nlp:dedup:article_consumer"
    # 24-hour TTL — matches the default on the mixin but declared explicitly here
    # so the intent is visible when reading this class in isolation.
    _dedup_ttl_seconds: ClassVar[int] = 86400

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
        usage_logger: LlmUsageLogProtocol | None = None,
        # PLAN-0084 B-3: Valkey client injected for ValkeyDedupMixin.
        # None means at-least-once mode (safe because all writes are idempotent).
        valkey_client: ValkeyClient | None = None,
    ) -> None:
        super().__init__(config)
        # ValkeyDedupMixin reads _dedup_client for dedup checks.
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
        # PLAN-0057 A-5 / F-CRIT-03: optional cost/latency logger threaded into
        # the deep-extraction block.  When None (unit-test default) the block
        # silently skips usage logging.
        self._usage_logger = usage_logger

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

        # PLAN-0063 W5-2: pull the doc title from the inbound event so the
        # chunk-creation block can populate ``title_denorm`` (weight A) on every
        # chunk it builds. ``str(...)`` only when present; the consumer must
        # tolerate absent titles (older sources) without raising.
        raw_title = value.get("title")
        doc_title: str | None = str(raw_title) if raw_title is not None else None

        # D-INIT-6 (2026-05-09): pull source_name off the inbound event so it can
        # ride along on the outbound nlp.article.enriched.v1 envelope. The KG
        # enriched_consumer needs source_name to stamp evidence-row provenance;
        # previously it tried to look this up via a cross-DB query against
        # ``document_source_metadata`` (an nlp_db table) from its intelligence_db
        # session pool — that's both an R7 cross-service-DB violation AND a
        # guaranteed UndefinedTableError. The fix is to propagate source_name
        # through the event itself. None is fine — the consumer logs a warning
        # and continues, never re-querying.
        source_name: str | None = value.get("source_name")

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

        # Best-effort: cache citation metadata for S8 RAG inline citations.
        # Failure must never cause NLP processing to fail.
        # url is not in the content.article.stored.v1 Avro schema;
        # fall back to reading source_url from the silver JSON envelope.
        url = value.get("url") or await self._extract_url_from_silver(minio_key)
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
        # D-INIT-6: source_name flows through the pipeline so _enqueue_enriched can
        # include it in the outbound enriched.v1 payload. None is acceptable — the
        # consumer side handles missing source_name without a cross-DB fallback.
        # Default None keeps existing internal callers (and unit tests that drive
        # _run_pipeline directly) working without churn while the new code path
        # in process_message() always supplies a value.
        source_name: str | None = None,
        published_at: datetime | None,
        extracted_at: datetime,
        is_backfill: bool,
        correlation_id: str | None,
        tenant_id: uuid.UUID | None = None,
        doc_title: str | None = None,
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
        # PLAN-0086 Wave F-1: compute word_count early so it is available for
        # the nlp.document.ready.v1 outbox event emitted at the end of the
        # pipeline for tenant documents.  Split on whitespace — consistent with
        # the word_count stored on the upload row by the S4 use case.
        _pipeline_word_count: int = len(text.split())
        sections = section_document(doc_id, text, source_type)

        # PLAN-0086 Wave C-1: stamp tenant_id on every section so the sections
        # table supports per-tenant isolation. Section is a frozen dataclass so
        # we use dataclasses.replace to produce new objects without mutation.
        if tenant_id is not None:
            sections = [dataclasses.replace(s, tenant_id=tenant_id) for s in sections]

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

        # PLAN-0084 B-3 (T-B-3-02): replace random mention_id values (assigned in
        # run_ner_block) with deterministic UUID5s derived from (doc_id, loop_index,
        # normalized_surface).  The 0-based loop index is the position in the NMS-
        # deduped output list; for a given doc the NER output is deterministic at
        # inference time so this index is stable across replays.  The INSERT uses
        # ON CONFLICT DO NOTHING (see entity_mention.py add_batch) so replays are
        # no-ops at the DB level.
        for _i, mention in enumerate(mentions):
            mention.mention_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(_i), mention.mention_text.lower().strip()))

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

        # PLAN-0084 B-3 (T-B-3-02): deterministic routing-decision ID.
        # Same doc_id always yields the same decision_id — safe for replays because
        # routing_decisions INSERT uses ON CONFLICT DO NOTHING (see routing_decision.py).
        decision_id = uuid.UUID(uuid5_from_parts(str(doc_id), "routing_decision"))
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

        # PLAN-0063 W5-2 / FR-T1-2: populate denorm fields (title + section
        # heading) on every chunk so the GENERATED ``tsv_english`` tsvector
        # column gets weight A (title) and weight B (section heading) when the
        # row is INSERTed. ``Chunk`` is a frozen dataclass — we use
        # ``dataclasses.replace`` to swap the two extra fields in. We resolve
        # ``section_heading_denorm`` per-chunk by indexing on ``section_id`` so
        # each chunk inherits the heading of its parent section. We pick
        # ``section.title`` (the heading) over ``heading_path`` because the
        # heading alone is the cleanest analyst-relevant signal — it is the
        # text users actually search for ("Risk Factors", "MD&A", etc.) — while
        # heading_path includes structural path noise.
        if chunks:
            section_heading_by_id = {s.section_id: s.title for s in sections}
            chunks = [
                dataclasses.replace(
                    chunk,
                    title_denorm=doc_title,
                    section_heading_denorm=section_heading_by_id.get(chunk.section_id),
                    # PLAN-0086 Wave C-1: stamp tenant_id on every chunk so the
                    # chunks table supports per-tenant isolation. Chunk is a frozen
                    # dataclass — dataclasses.replace creates a new instance.
                    tenant_id=tenant_id,
                )
                for chunk in chunks
            ]

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
                # A-007: explicit CanonicalEntityPort annotation so mypy and
                # the architecture test (IG-LAYER-002) can verify that this
                # variable is typed against the port ABC, not the concrete
                # infrastructure class.
                canon_repo: CanonicalEntityPort = CanonicalEntityRepository(intel_session)
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
                # PLAN-0057 A-4 (F-CRIT-02): persist the audit trail. Previously
                # the list was iterated for Prometheus only, then dropped on the
                # floor — every UNRESOLVED / PROVISIONAL / AUTO_RESOLVED outcome
                # was invisible to ops and to the next-cycle worker. Writes go
                # through the same nlp_session so commit ordering is preserved.
                #
                # PLAN-0052 platform-QA fix (2026-05-01): defer the audit batch
                # to AFTER `mention_repo.add_batch(final_mentions)` below. SQLA
                # autoflush would otherwise flush the children
                # (`mention_resolutions.mention_id`) before the parents
                # (`entity_mentions.mention_id`) are in the session, producing
                # `mention_resolutions_mention_id_fkey` violations and a silent
                # full-pipeline drop (3,081 docs in → 0 mention_resolutions).
                # The audit batch is captured in `resolution_audit` and stashed
                # in the closure variable below; the actual `add_batch` runs
                # after `mention_repo.add_batch(final_mentions)`.
                pending_resolution_audit = resolution_audit
            else:
                pending_resolution_audit = []

            # Block 10: Deep LLM extraction.
            # PLAN-0057 D-1 (F-CRIT-08): the previous code instantiated a
            # ``ClaimsRepository`` here and threaded it through the block to
            # write each extracted claim to the ``claim.extracted`` outbox
            # topic. That topic had ZERO consumer groups subscribed (verified
            # via ``kafka-consumer-groups --describe``); KG ingests claims via
            # the ``raw_claims`` array on the ``nlp.article.enriched.v1``
            # event built later in this method. The dead producer is gone.
            signals: list = []
            if should_run_deep_extraction(final_path):
                extraction_result, signals = await run_deep_extraction_block(
                    doc_id=doc_id,
                    chunks=chunks,
                    mentions=final_mentions,
                    processing_path=final_path,
                    extraction_client=self._ext,
                    model_id=self._settings.extraction_model_id,
                    published_at=published_at,
                    extracted_at=extracted_at,
                    outbox_topic_signal=self._settings.topic_signal_detected,
                    # PLAN-0057 A-5 / F-CRIT-03: pass through the optional cost
                    # logger so each per-window LLM call writes one row to
                    # nlp_db.llm_usage_log. None when not wired (unit tests).
                    usage_logger=self._usage_logger,
                )

            if should_run_deep_extraction(final_path):
                s6_claims_extracted_total.inc(len(list(extraction_result.get("claims", []))))

                # PLAN-0052 platform-QA round 9 (2026-05-01): Option 2 —
                # synthetic-provisional-on-demand. The deep-extraction LLM
                # frequently references UNRESOLVED mentions in its output
                # (mining companies, geo locations, novel orgs not yet
                # canonicalised). Without a queue_id, ``_build_raw_*`` would
                # silently drop every relation/event/claim referencing them.
                # ``synthesize_provisional_refs`` scans the LLM output, finds
                # matching UNRESOLVED mentions, and inserts a
                # ``provisional_entity_queue`` row inline (SAVEPOINT-guarded,
                # churn-guard applied). The downstream ``_build_raw_*`` then
                # picks up the new ``provisional_queue_id`` and emits the row
                # with ``entity_provisional=True``. KG enriched_consumer
                # already accepts and persists these as
                # ``relation_evidence_raw`` rows; the unresolved-resolution-
                # worker later canonicalises the queue entry, at which point
                # KG promotes the relation evidence to a real ``relation_id``.
                await synthesize_provisional_refs(
                    mentions=final_mentions,
                    extraction_result=extraction_result,
                    intelligence_session=intel_session,
                )

            # Write all artifacts to nlp_db
            section_repo = SectionRepository(nlp_session)
            chunk_repo = ChunkRepository(nlp_session)
            mention_repo = EntityMentionRepository(nlp_session)
            stats_repo = DocumentEntityStatsRepository(nlp_session)
            routing_repo = RoutingDecisionRepository(nlp_session)
            cem_repo = ChunkEntityMentionRepository(nlp_session)
            outbox_repo = OutboxRepository(nlp_session)

            # PLAN-0078 Wave B: augment chunks with denormalised entity mention
            # metadata BEFORE write so the GIN-indexed entity_mentions column
            # is populated at INSERT time.  Block 9 has already resolved
            # ``resolved_entity_id`` on each EntityMention, so the JSONB will
            # include entity_id for resolved mentions and null for unresolved.
            if chunks and final_mentions:
                chunk_mention_map = _build_chunk_entity_mentions(
                    chunks, final_mentions, self._settings.gliner_mention_floor
                )
                chunks = [
                    dataclasses.replace(chunk, entity_mentions=chunk_mention_map[chunk.chunk_id]) for chunk in chunks
                ]

            await section_repo.add_batch(sections)
            await chunk_repo.add_batch(chunks)
            await mention_repo.add_batch(final_mentions)
            # PLAN-0052 platform-QA fix (2026-05-01): persist the resolution
            # audit AFTER the parent entity_mentions are in the session, so
            # SQLA's autoflush can satisfy the
            # `mention_resolutions_mention_id_fkey` constraint. See the
            # deferring branch in Block 9 above for the full rationale.
            # `mr_repo` is only defined when the resolution branch ran; we
            # rebuild a fresh local one here so the deferred write doesn't
            # reach across an undefined-name path.
            if pending_resolution_audit:
                deferred_mr_repo = MentionResolutionRepository(nlp_session)
                await deferred_mr_repo.add_batch(pending_resolution_audit)
            await stats_repo.upsert(stats)
            # PLAN-0057 A-4 (F-CRIT-06): persist Block 6 suppression-gate output
            # alongside the routing tier. final_path is the result of
            # apply_suppression_gate(), accounting for any novelty-driven downgrade
            # earlier in this method.
            routing_decision.processing_path = final_path
            await routing_repo.add(routing_decision)

            # Write embeddings directly (no dedicated repo).
            # PLAN-0084 B-3: async helpers use ON CONFLICT DO NOTHING + deterministic IDs.
            await _write_section_embeddings(
                nlp_session, section_embs, model_id=self._settings.embedding_model_id, doc_id=doc_id
            )
            await _write_chunk_embeddings(
                nlp_session, chunk_embs, model_id=self._settings.embedding_model_id, doc_id=doc_id
            )

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
                # D-INIT-6: propagate source_name through to the outbound
                # nlp.article.enriched.v1 payload so KG can stamp evidence
                # provenance without a cross-DB query.
                source_name=source_name,
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

            # Block 13E: emit intelligence.temporal_event.v1 for macro / geopolitical
            # events found by Block 10. Must be inside the same DB transaction so
            # temporal event rows are never lost on commit failure.  No second LLM
            # call — reuses the extraction_result already produced above.
            # Build the entity_id_by_ref lookup from resolved/provisional mentions
            # so _emit_temporal_events can map participant_entity_ids to real UUIDs.
            if should_run_deep_extraction(final_path) and extraction_result.get("events"):
                # Reuse the same resolved-mention lookup that _enqueue_enriched uses:
                # resolved entities first (canonical UUID), then provisional (queue UUID).
                _te_entity_id_by_ref: dict[str, str] = {}
                for _m in final_mentions:
                    if _m.resolved_entity_id is not None:
                        for _v in _normalize_ref_variants(_m.mention_text):
                            _te_entity_id_by_ref.setdefault(_v, str(_m.resolved_entity_id))
                    elif _m.provisional_queue_id is not None:
                        for _v in _normalize_ref_variants(_m.mention_text):
                            _te_entity_id_by_ref.setdefault(_v, str(_m.provisional_queue_id))

                # Track which mention refs map to provisional queue entries so
                # _emit_temporal_events can skip them (spec: exposed_entities only
                # contains resolved canonical entity UUIDs).
                _te_provisional_ids: frozenset[str] = frozenset(
                    str(_m.provisional_queue_id) for _m in final_mentions if _m.provisional_queue_id is not None
                )

                # BP-349: normalize raw LLM output (confidence→extraction_confidence,
                # description→event_text, entity_refs→participant_entity_ids) before
                # passing to _emit_temporal_events which expects the processed format.
                # QG-3: _normalize_temporal_events_for_emit does NOT skip events with
                # zero resolvable entity refs — macro events are globally scoped.
                _te_normalized = _normalize_temporal_events_for_emit(
                    extraction_result.get("events", []),
                    _te_entity_id_by_ref,
                    _te_provisional_ids,
                )
                if _te_normalized:
                    await _emit_temporal_events(
                        raw_events=_te_normalized,
                        entity_id_by_ref=_te_entity_id_by_ref,
                        provisional_entity_ids=_te_provisional_ids,
                        doc_id=doc_id,
                        published_at=published_at,
                        outbox_repo=outbox_repo,
                        settings=self._settings,
                    )

            # PLAN-0086 Wave F-1 (T-F-1-03): emit nlp.document.ready.v1 for
            # tenant documents.  This event is consumed by S4 to transition the
            # upload row to status=READY and store pipeline output counts.
            # Condition: tenant_id is not None (platform articles have no tenant).
            # Must be inside the nlp_session transaction so the outbox row is
            # committed atomically with all NLP artifacts above — if commit()
            # fails the event is never enqueued and S4 never marks the upload as
            # ready, leaving it in PROCESSING status (visible via the S4 API).
            if tenant_id is not None:
                await _enqueue_document_ready(
                    outbox_repo=outbox_repo,
                    settings=self._settings,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    chunk_count=len(chunks),
                    word_count=_pipeline_word_count,
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

            # Intel commit (D-004 dual-commit).
            # NLP is already committed above.  If intel fails we log at ERROR,
            # increment the Prometheus counter, and RE-RAISE so that the Kafka
            # offset is NOT committed — the message will be re-delivered and the
            # intel writes will be retried.  The idempotency-skip at the top of
            # process_message (routing_decision exists?) fires on re-delivery,
            # preventing the full NLP pipeline from running again.  Intel writes
            # are idempotent on retry because provisional_entity_queue has a
            # UNIQUE constraint on (normalized_surface, mention_class) and all
            # other intel inserts use ON CONFLICT DO NOTHING.
            try:
                await intel_session.commit()
            except Exception:
                s6_intel_commit_failures_total.inc()
                logger.error(  # type: ignore[no-any-return]
                    "d004_intel_commit_failed",
                    doc_id=str(doc_id),
                    exc_info=True,
                )
                raise  # re-raise so Kafka offset is not committed → re-delivery

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

        S-006: Validate the key against the canonical silver-key pattern before
        attempting the download.  A non-canonical key means the upstream event was
        malformed or tampered — reject immediately so the error is visible rather
        than producing a confusing storage 404 or returning garbled content.
        """
        # S-006: Reject keys that do not match the silver-layer canonical pattern.
        # Pattern: silver/<source>/<YYYY>/<MM>/<DD>/<uuid>.txt
        # An invalid key is a hard error — re-delivery would produce the same failure.
        if not KeyBuilder.is_valid_silver_key(minio_key):
            raise ValueError(f"Rejected non-canonical minio_key: {minio_key!r}")

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

    # ── Idempotency (PLAN-0084 B-3) ──────────────────────────────────────────
    # is_duplicate / mark_processed are now provided by ValkeyDedupMixin.
    # The no-op stubs that previously lived here have been removed; the mixin
    # handles Valkey SET/EXISTS with a 24h TTL and safe at-least-once fallback.
    # See ValkeyDedupMixin docstring in libs/messaging for the failure contract.

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

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
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
) -> dict[uuid.UUID, list[dict]]:
    """Build entity_mentions JSONB payload for each chunk (PLAN-0078 Wave B).

    Matches resolved EntityMention objects to chunks by char-offset overlap
    (same logic as _compute_chunk_mention_pairs).  Only mentions with
    ``confidence >= mention_floor`` are included to avoid GIN index bloat.

    Returns a mapping of chunk_id → list[mention_dict] where each dict has:
        entity_id (str|null), entity_type (str), char_start (int),
        char_end (int), gliner_score (float), raw_text (str).
    """
    result: dict[uuid.UUID, list[dict]] = {chunk.chunk_id: [] for chunk in chunks}
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


async def _enqueue_enriched(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    doc_id: uuid.UUID,
    source_type: str,
    # D-INIT-6: human-readable source label (RSS feed name, EODHD provider, etc.).
    # Travels in the enriched.v1 payload so KG can stamp evidence-row provenance
    # without a cross-service DB query (the previous fallback queried
    # document_source_metadata from intelligence_db — wrong DB, R7 violation).
    # Default None keeps existing unit tests that call _enqueue_enriched
    # directly working; the production caller in _run_pipeline always supplies
    # the value pulled off the inbound event.
    source_name: str | None = None,
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

    # PLAN-0057 B-1 (F-CRIT-07): the prior version of this lookup was built only
    # from RESOLVED mentions, but the deep-extraction prompt told the LLM to use
    # entity_refs drawn from the FULL mention list. The LLM correctly followed
    # the prompt and picked unresolved-but-mentioned surfaces; the
    # ``_build_raw_*`` helpers below silently dropped every relation/event/claim
    # whose ref didn't appear in this dict. Empirically that destroyed ~80% of
    # extracted output (producer log claims=5 → consumer log claims=2; relations
    # ~100% drop because BOTH endpoints had to resolve).
    #
    # The fix: include both RESOLVED mentions (real canonical UUID) AND
    # PROVISIONAL mentions that have a ``provisional_queue_id`` (synthetic UUID
    # pointing into ``provisional_entity_queue``). Track which keys are
    # provisional so we can tag downstream raw_* rows with
    # ``entity_provisional=True`` and ``provisional_queue_id=<queue UUID>``.
    # KG-side ``enriched_consumer._parse_raw_relations`` already accepts these
    # fields and is wired to promote provisional rows once the corresponding
    # canonical_entity is created via the entity.canonical.created.v1 stream.
    entity_id_by_ref: dict[str, str] = {}
    provisional_refs: set[str] = set()

    # PLAN-0052 platform-QA fix (2026-05-01): seed the lookup with multiple
    # normalized variants of each mention surface so the LLM's slightly
    # different rendering (drops "Corp"/"Inc", normalizes whitespace, etc.)
    # still matches. Without this, the consumer log showed
    # `relations=0, events=0` for every doc despite extraction producing
    # 1-3 of each — the F-CRIT-07 entity_id_by_ref miss persisted.
    # Variants we seed for each mention:
    #   - exact lowercase
    #   - whitespace-collapsed lowercase
    #   - stripped of common corporate suffixes (Inc, Corp, Ltd, LLC, PLC,
    #     Co, Holdings, Group, AG, NV, SA)
    # The first variant that matches wins — we never overwrite a more-
    # specific key with a less-specific one (resolved beats provisional
    # naturally because resolved mentions are added to the dict first).
    # Local closure over the module-level _BUILD_RAW_SUFFIX_RX so we don't
    # duplicate the regex literal — the build_raw_* helpers below also need it.
    def _ref_variants(text: str) -> list[str]:
        """Return all normalized lookup variants for a mention surface."""
        out: list[str] = []
        lower = text.lower().strip()
        out.append(lower)
        # whitespace-collapsed (multiple spaces → single)
        collapsed = " ".join(lower.split())
        if collapsed != lower:
            out.append(collapsed)
        # suffix-stripped (try until the regex no longer matches; defensive
        # against rare double-suffixes like "Foo Holdings Inc")
        stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
        while stripped != collapsed:
            if stripped and stripped not in out:
                out.append(stripped)
            collapsed = stripped
            stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
        return out

    for m in mentions:
        if m.resolved_entity_id is not None:
            value = str(m.resolved_entity_id)
            for variant in _ref_variants(m.mention_text):
                # Don't clobber an earlier (more-specific) key. setdefault
                # gives "first writer wins" without an extra branch.
                entity_id_by_ref.setdefault(variant, value)
        elif m.provisional_queue_id is not None:
            value = str(m.provisional_queue_id)
            for variant in _ref_variants(m.mention_text):
                if variant not in entity_id_by_ref:
                    entity_id_by_ref[variant] = value
                    provisional_refs.add(variant)
        # else: UNRESOLVED with no queue id (truly unknown surface) — still
        # excluded from the lookup so downstream relations referring to it
        # are dropped (no synthetic id to point to).

    # Hallucination detection: count entity_refs produced by the LLM that are NOT
    # in the known-entities lookup. These are refs the model invented rather than
    # copying from the {entities} list we provided in the prompt. A non-zero count
    # here indicates model drift and should be monitored in Grafana.
    _all_llm_refs: set[str] = set()
    for _rel in extraction_result.get("relations", []):
        if isinstance(_rel, dict):
            _all_llm_refs.add(str(_rel.get("subject_ref", "")).lower().strip())
            _all_llm_refs.add(str(_rel.get("object_ref", "")).lower().strip())
    for _evt in extraction_result.get("events", []):
        if isinstance(_evt, dict):
            for _ref in _evt.get("entity_refs") or []:
                _all_llm_refs.add(str(_ref).lower().strip())
    for _clm in extraction_result.get("claims", []):
        if isinstance(_clm, dict):
            _all_llm_refs.add(str(_clm.get("entity_ref", "")).lower().strip())
    _all_llm_refs.discard("")
    _hallucinated = sum(1 for _r in _all_llm_refs if _r not in entity_id_by_ref)
    if _hallucinated > 0:
        s6_extraction_entity_ref_hallucinated_total.inc(_hallucinated)

    # SA-3 fix (2026-05-10): pass published_at so each relation row gets
    # evidence_date = published_at (or None → KG falls back to utc_now()).
    # Without this, KG's _parse_dt receives None and stamps all rows with now(),
    # making every evidence_date the same day and breaking the confidence trend chart.
    raw_relations = _build_raw_relations(
        extraction_result.get("relations", []),
        entity_id_by_ref,
        provisional_refs,
        published_at=published_at,
    )
    raw_events = _build_raw_events(extraction_result.get("events", []), entity_id_by_ref, provisional_refs)
    raw_claims = _build_raw_claims(extraction_result.get("claims", []), entity_id_by_ref, provisional_refs)

    # PLAN-0062 Wave B: encode raw_* arrays as JSON strings transported through
    # the Avro envelope.  Defining nested record schemas for relations/events/
    # claims would be brittle (the LLM output dicts have many optional fields)
    # and slow to evolve — JSON-string transport keeps the wire format flat
    # while still gaining schema enforcement on the metadata fields.  KG
    # ``EnrichedArticleConsumer`` JSON-decodes these back into RawRelation /
    # RawEvent / RawClaim dataclasses.
    # PLAN-0084 B-3 (T-B-3-02): deterministic event_id for the enriched event.
    # Same doc_id → same UUID5 on replay, so the outbox INSERT ON CONFLICT DO NOTHING
    # guard prevents duplicate outbox rows on Kafka re-delivery.
    enriched_event_id = uuid5_from_parts(str(doc_id), "article_enriched_v1")

    payload: dict[str, Any] = {
        "event_id": enriched_event_id,
        "event_type": "nlp.article.enriched",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc_id),
        "source_type": source_type,
        # D-INIT-6: ride-along provenance label (None when the inbound event didn't
        # carry one — KG consumer handles None without re-querying).
        "source_name": source_name,
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
        "raw_relations_json": encode_raw_array(raw_relations),
        "raw_events_json": encode_raw_array(raw_events),
        "raw_claims_json": encode_raw_array(raw_claims),
        "provisional_entity_count": sum(1 for m in mentions if m.resolved_entity_id is None),
        "extraction_model_id": extraction_model_id,
        "correlation_id": correlation_id,
    }
    schema_path = str(_SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
    await outbox_repo.add(
        topic=settings.topic_article_enriched,
        partition_key=str(doc_id),
        payload_avro=serialize_confluent_avro(schema_path, payload),
        # Pass deterministic event_id so the outbox PK INSERT ON CONFLICT DO NOTHING
        # deduplicates replay deliveries at the outbox-table level as well.
        event_id=uuid.UUID(enriched_event_id),
    )


# PLAN-0052 platform-QA fix (2026-05-01): symmetric normalization on the
# LLM-side ref. The lookup dict was widened with stripped suffixes /
# whitespace-collapsed variants of each mention, but the LLM may also
# output the OPPOSITE direction — e.g. mention is "NVIDIA Corp" (variant
# adds "nvidia") while LLM returns "NVIDIA Corporation". Without
# normalizing the LLM ref too, that miss persists. We try the raw ref
# first (cheapest), then fall back through the same variant list.
_BUILD_RAW_SUFFIX_RX = re.compile(
    r"\s+(inc|corp|corporation|ltd|llc|plc|co|holdings|group|ag|nv|sa|s\.a\.|s\.p\.a\.)\.?$",
    re.IGNORECASE,
)


def _normalize_ref_variants(text: str) -> list[str]:
    """Same shape as the closure helper in `_emit_enriched_event`.

    Kept duplicated rather than refactored into a shared module to keep this
    fix self-contained — the build_raw_* helpers are module-private and the
    normalization rules are identical to the lookup-population rules.
    """
    out: list[str] = []
    lower = text.lower().strip()
    if not lower:
        return out
    out.append(lower)
    collapsed = " ".join(lower.split())
    if collapsed != lower:
        out.append(collapsed)
    stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
    while stripped and stripped != collapsed:
        if stripped not in out:
            out.append(stripped)
        collapsed = stripped
        stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
    return out


def _resolve_ref(
    raw_ref: str,
    entity_id_by_ref: dict[str, str],
) -> tuple[str | None, str | None]:
    """Return (entity_id, matched_key) for the first variant that hits."""
    for variant in _normalize_ref_variants(raw_ref):
        eid = entity_id_by_ref.get(variant)
        if eid is not None:
            return eid, variant
    return None, None


# ── Synthetic-provisional-on-demand (PLAN-0052 platform-QA round 9) ──────────


def _collect_extraction_refs(extraction_result: dict[str, Any]) -> set[str]:
    """Return the set of normalized entity surface forms the LLM referenced.

    Walks the extraction result and yields every ``subject_ref``/``object_ref``
    on relations, every ``entity_refs`` element on events, and every
    ``entity_ref`` on claims. Each is normalized through ``_normalize_ref_variants``
    and the union of all variants is returned. The article-consumer uses this
    to find UNRESOLVED mentions that the LLM has actually used; those are
    promoted to PROVISIONAL inline so ``_build_raw_*`` can address them.
    """
    refs: set[str] = set()

    def _ingest(raw: object) -> None:
        if not isinstance(raw, str):
            return
        for variant in _normalize_ref_variants(raw):
            refs.add(variant)

    for rel in extraction_result.get("relations", []):
        if isinstance(rel, dict):
            _ingest(rel.get("subject_ref"))
            _ingest(rel.get("object_ref"))

    for evt in extraction_result.get("events", []):
        if isinstance(evt, dict):
            ents = evt.get("entity_refs")
            if isinstance(ents, list):
                for e in ents:
                    _ingest(e)

    for clm in extraction_result.get("claims", []):
        if isinstance(clm, dict):
            _ingest(clm.get("entity_ref"))

    return refs


async def synthesize_provisional_refs(
    *,
    mentions: list[Any],
    extraction_result: dict[str, Any],
    intelligence_session: object,
) -> int:
    """Promote LLM-referenced UNRESOLVED mentions to PROVISIONAL inline.

    Called after Block 10 deep extraction completes and BEFORE
    ``_enqueue_enriched`` builds the Kafka payload. For every entity surface
    the LLM referenced (via ``relations.subject_ref`` / ``relations.object_ref``
    / ``events.entity_refs`` / ``claims.entity_ref``), find the matching
    UNRESOLVED mention in the local ``mentions`` list. If found and not
    already queued, call ``ensure_provisional_for_mention`` which inserts a
    ``provisional_entity_queue`` row inline (SAVEPOINT-guarded, churn-guard
    applied) and stashes the queue_id on the mention.

    The downstream ``_build_raw_relations`` / ``_build_raw_events`` /
    ``_build_raw_claims`` then see the new ``provisional_queue_id`` and emit
    rows with ``entity_provisional=True`` and ``provisional_queue_id=<uuid>``.
    KG ``enriched_consumer`` already accepts and persists these.

    Returns the number of mentions promoted (for observability).
    """
    if not extraction_result:
        return 0

    # Lazy-import the helper so the consumer module's import-time graph stays
    # compatible with unit tests that mock entity_resolution at the module level.
    from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

    referenced = _collect_extraction_refs(extraction_result)
    if not referenced:
        return 0

    # Build a quick lookup of UNRESOLVED mentions by their normalised variants
    # so a single LLM ref can match against any surface form.
    candidate_index: dict[str, Any] = {}
    for m in mentions:
        if m.resolved_entity_id is not None or m.provisional_queue_id is not None:
            continue
        for variant in _normalize_ref_variants(m.mention_text):
            candidate_index.setdefault(variant, m)

    promoted = 0
    seen_mentions: set[uuid.UUID] = set()
    for ref in referenced:
        m = candidate_index.get(ref)
        if m is None:
            continue
        if m.mention_id in seen_mentions:
            continue
        seen_mentions.add(m.mention_id)
        queue_id = await ensure_provisional_for_mention(m, intelligence_session)
        if queue_id is not None:
            promoted += 1

    if promoted:
        logger.info(  # type: ignore[no-any-return]
            "synthesize_provisional_refs.complete",
            promoted=promoted,
            referenced=len(referenced),
        )
    return promoted


def _build_raw_relations(
    relations: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
    *,
    published_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Convert LLM extraction relations into the dict format S7 expects.

    S7's ``_parse_raw_relations`` requires ``subject_entity_id``, ``object_entity_id``,
    and ``raw_type``. Skips relations where either entity ref cannot be resolved
    (truly unknown surface). When a ref points to a PROVISIONAL mention, sets
    ``entity_provisional=True`` and emits the corresponding queue id as
    ``provisional_queue_id`` so KG can promote the row once a canonical entity
    is later created (PLAN-0057 B-1, F-CRIT-07).

    SA-3 fix (2026-05-10): ``published_at`` is now included in each relation dict as
    ``evidence_date``.  KG's ``_parse_dt`` falls back to ``now()`` when the field is
    absent, which stamps all rows with today's date and breaks the confidence trend
    chart (every point clusters on the ingestion day rather than the article date).
    Passing the article's ``published_at`` propagates historically-dated evidence so
    the 90-day trend chart shows meaningful multi-day variation.
    """
    # ISO string once — all rows in this batch share the same article date
    evidence_date_iso: str | None = published_at.isoformat() if published_at else None

    result: list[dict[str, Any]] = []
    for rel in relations:
        rel_d: dict[str, Any] = dict(rel) if not isinstance(rel, dict) else rel  # type: ignore[call-overload]
        subject_ref = str(rel_d.get("subject_ref", ""))
        object_ref = str(rel_d.get("object_ref", ""))
        subject_id, subject_match = _resolve_ref(subject_ref, entity_id_by_ref)
        object_id, object_match = _resolve_ref(object_ref, entity_id_by_ref)
        if subject_id is None or object_id is None:
            continue  # skip truly unresolved — neither resolved nor provisional
        # Provisional flag uses the matched-key (post-normalization) so the
        # provisional_refs set lookup stays consistent with the lookup we
        # actually used.
        subject_is_provisional = subject_match in provisional_refs
        object_is_provisional = object_match in provisional_refs
        # Pick whichever endpoint is provisional as the queue_id reference.
        # If both endpoints are provisional we surface the SUBJECT queue id —
        # KG promotes by queue_id so either is fine; subject is the conventional
        # primary endpoint of a relation.
        provisional_qid: str | None = None
        if subject_is_provisional:
            provisional_qid = subject_id
        elif object_is_provisional:
            provisional_qid = object_id
        result.append(
            {
                "subject_entity_id": subject_id,
                "object_entity_id": object_id,
                "raw_type": str(rel_d.get("predicate", "")),
                "extraction_confidence": float(rel_d.get("confidence", 0.5)),
                "evidence_text": str(rel_d.get("evidence_text", "")) or None,
                "entity_provisional": subject_is_provisional or object_is_provisional,
                "provisional_queue_id": provisional_qid,
                # SA-3 (2026-05-10): carry article publication date into each relation row.
                # KG ``_parse_dt`` treats None as utc_now() fallback — that's fine here
                # for articles where published_at is unknown (e.g. wire-feed items).
                "evidence_date": evidence_date_iso,
            }
        )
    return result


def _normalize_temporal_events_for_emit(
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """Normalize raw LLM event dicts into the format _emit_temporal_events expects.

    Unlike _build_raw_events, this does NOT skip events with no resolvable entity
    refs — macro/geopolitical events are globally scoped and often have no
    company-specific participants.  In that case participant_entity_ids=[] is emitted
    and S7 stores a temporal_event with an empty entity_event_exposures set.

    Maps: confidence→extraction_confidence, description→event_text, entity_refs→participant_entity_ids
    """
    result: list[dict[str, Any]] = []
    for evt in raw_events:
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]
        participant_ids: list[str] = []
        for ref in evt_d.get("entity_refs", []) or []:
            eid, _ = _resolve_ref(str(ref), entity_id_by_ref)
            if eid is not None and eid not in provisional_ids:
                participant_ids.append(eid)
        result.append(
            {
                "event_type": str(evt_d.get("event_type", "")).upper(),
                "event_text": str(evt_d.get("description", "")),
                "extraction_confidence": float(evt_d.get("confidence", 0.5)),
                "participant_entity_ids": participant_ids,
            }
        )
    return result


def _build_raw_events(
    events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction events into the dict format S7 expects.

    S7's ``_parse_raw_events`` requires ``subject_entity_id`` and ``event_type``.
    Uses the first resolvable entity_ref as subject. Skips events with no
    resolvable entity. When the subject ref is PROVISIONAL, sets
    ``entity_provisional=True`` and ``provisional_queue_id`` per PLAN-0057 B-1.
    """
    result: list[dict[str, Any]] = []
    for evt in events:
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]
        # Find the first resolvable entity ref from the entity_refs list.
        # PLAN-0052 platform-QA fix: use _resolve_ref so suffix-stripped /
        # whitespace-collapsed LLM output still matches.
        entity_refs = evt_d.get("entity_refs", [])
        subject_id: str | None = None
        subject_ref_lower: str | None = None
        participant_ids: list[str] = []
        for ref in entity_refs:  # type: ignore[union-attr]
            eid, matched = _resolve_ref(str(ref), entity_id_by_ref)
            if eid is not None:
                if subject_id is None:
                    subject_id = eid
                    subject_ref_lower = matched
                participant_ids.append(eid)
        if subject_id is None:
            continue  # skip truly unresolved
        is_provisional = (subject_ref_lower or "") in provisional_refs
        result.append(
            {
                "subject_entity_id": subject_id,
                "event_type": str(evt_d.get("event_type", "")).upper(),
                "event_text": str(evt_d.get("description", "")),
                "extraction_confidence": float(evt_d.get("confidence", 0.5)),
                "participant_entity_ids": participant_ids,
                "entity_provisional": is_provisional,
                "provisional_queue_id": subject_id if is_provisional else None,
            }
        )
    return result


def _build_raw_claims(
    claims: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction claims into the dict format S7 expects.

    S7's ``_parse_raw_claims`` requires ``subject_entity_id`` and ``claim_type``.
    Skips claims where the entity ref cannot be resolved. PLAN-0057 B-1: when
    the subject_ref is a PROVISIONAL surface, emit ``entity_provisional=True``
    and the queue UUID so KG can promote the claim once a canonical lands.
    """
    result: list[dict[str, Any]] = []
    for claim in claims:
        claim_d: dict[str, Any] = dict(claim) if not isinstance(claim, dict) else claim  # type: ignore[call-overload]
        # PLAN-0052 platform-QA fix: same suffix-stripping / whitespace-
        # collapsed lookup as the relations + events helpers above.
        entity_ref_raw = str(claim_d.get("entity_ref", ""))
        subject_id, matched_key = _resolve_ref(entity_ref_raw, entity_id_by_ref)
        if subject_id is None:
            continue  # skip truly unresolved
        is_provisional = (matched_key or "") in provisional_refs
        result.append(
            {
                "subject_entity_id": subject_id,
                "claim_type": str(claim_d.get("claim_type", "")),
                "polarity": str(claim_d.get("polarity", "neutral")),
                "claim_text": str(claim_d.get("evidence_text", "")),
                "extraction_confidence": float(claim_d.get("confidence", 0.5)),
                "entity_provisional": is_provisional,
                "provisional_queue_id": subject_id if is_provisional else None,
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

    PLAN-0084 B-3 (T-B-3-02): the outbox ``event_id`` for each signal is derived
    deterministically from ``(doc_id, signal_type, loop_index)`` so Kafka replays
    of the same article produce the same outbox primary keys and the INSERT ON
    CONFLICT DO NOTHING guard prevents duplicate signal rows.
    """
    for signal_index, signal in enumerate(signals):
        # Deterministic outbox event_id: same doc + signal type + position → same UUID5.
        # signal.signal_type is stable for a given doc (LLM output is deterministic
        # at temperature=0); the 0-based loop index provides positional disambiguation
        # when multiple signals of the same type are extracted from one article.
        outbox_event_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(signal.signal_type), str(signal_index)))
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
        # PLAN-0062 F-006 / DS F-001: build Avro bytes BEFORE the outbox add so
        # a serialization failure aborts the transaction instead of poisoning
        # the outbox with a half-written row.
        payload_bytes = serialize_confluent_avro(
            _NLP_SIGNAL_DETECTED_SCHEMA_PATH,
            payload,
        )
        await outbox_repo.add(
            topic=settings.topic_signal_detected,
            partition_key=str(signal.entity_id),
            payload_avro=payload_bytes,
            event_id=outbox_event_id,
        )


def _infer_temporal_scope(event_type: str) -> str:
    """Map a Block-10 event_type to the intelligence.temporal_event.v1 scope field.

    Scope semantics (per Avro schema doc + PRD-0018 §6.2):
    - ``GLOBAL``   — events with broad cross-border reach (geopolitical, sanctions).
    - ``NATIONAL`` — country-level policy or economic releases (macro, regulatory).
    - ``REGIONAL`` — geographically bounded natural events.

    Defaults to ``NATIONAL`` for any unrecognised type so the consumer never
    receives an invalid scope value.
    """
    scope_map: dict[str, str] = {
        "GEOPOLITICAL": "GLOBAL",
        "SANCTIONS": "GLOBAL",
        "MACRO": "NATIONAL",
        "REGULATORY_ACTION": "NATIONAL",
        "NATURAL_DISASTER": "REGIONAL",
    }
    return scope_map.get(event_type.upper(), "NATIONAL")


async def _emit_temporal_events(
    *,
    raw_events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_entity_ids: frozenset[str],
    doc_id: uuid.UUID,
    published_at: datetime | None,
    outbox_repo: OutboxRepository,
    settings: Any,
) -> None:
    """Block 13E — publish ``intelligence.temporal_event.v1`` for macro/geo events.

    Reuses the Block 10 extraction output (``raw_events``); adds NO second LLM
    call.  The function:

    1. Filters events to the ``_TEMPORAL_EVENT_TYPES`` set.
    2. Skips events with ``extraction_confidence < 0.5``.
    3. Builds an Avro payload matching the ``intelligence.temporal_event.v1``
       schema for each qualifying event.
    4. Resolves ``participant_entity_ids`` to canonical entity UUIDs (provisional
       IDs are intentionally excluded — the KG consumer only accepts confirmed
       canonical entities in ``exposed_entities``).
    5. Writes each payload to the outbox via ``outbox_repo.add()`` so the
       transactional guarantee of the enclosing nlp_db commit is preserved.

    All payloads use Confluent Avro wire format (magic byte + schema-id header)
    so the S7 ``TemporalEventConsumer`` can deserialise them without extra
    negotiation.
    """
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

        # ── Build exposed_entities from participant_entity_ids ───────────────
        # Participant IDs arrive as a list of string UUIDs already resolved by
        # _build_raw_events (they are the values from entity_id_by_ref).
        # We skip provisional entries because S7 requires confirmed canonical
        # entity UUIDs in entity_event_exposures.
        participant_ids: list[str] = [str(pid) for pid in evt_d.get("participant_entity_ids", [])]
        exposed_entities: list[dict[str, Any]] = [
            {
                "entity_id": pid,
                "exposure_type": "directly_affected",
                # Carry the same extraction confidence for all participants —
                # S7 stores this as entity_event_exposures.confidence.
                "confidence": confidence,
            }
            for pid in participant_ids
            if pid not in provisional_entity_ids  # skip provisional queue UUIDs
        ]

        # ── Infer scope from event_type ───────────────────────────────────────
        scope = _infer_temporal_scope(raw_type)

        # ── Build Avro payload (all fields match intelligence.temporal_event.v1.avsc)
        # Avro empty-string convention: the S7 consumer converts "" → NULL for
        # region, active_until, source_url, description (per avsc doc field).
        # PLAN-0084 QA D-009: deterministic event_id prevents duplicate outbox rows
        # on Kafka re-delivery. UUID5 is derived from (doc_id, event_type, loop_index)
        # so each qualifying temporal event in an article gets a stable, unique ID
        # that bypasses the outbox ON CONFLICT (event_id) DO NOTHING guard on replay.
        te_event_id = uuid.UUID(uuid5_from_parts(str(doc_id), raw_type, str(_idx)))
        payload: dict[str, Any] = {
            "event_id": str(te_event_id),
            "event_type": "intelligence.temporal_event",  # envelope field
            "schema_version": 1,
            "occurred_at": common.time.utc_now().isoformat(),
            # Lowercase event type for the temporal_event_type column
            # (e.g. "macro", "geopolitical") — consumer stores as-is.
            "temporal_event_type": raw_type.lower(),
            "scope": scope,
            # Region is unknown from article text alone; S7 converts "" → NULL.
            "region": "",
            # Truncate to 500 chars per Avro field doc constraint.
            "title": str(evt_d.get("event_text", ""))[:500],
            "description": "",
            "source_article_ids": [str(doc_id)],
            "source_url": "",
            # active_from defaults to article publication date; fall back to now()
            # if published_at is absent (should be rare for DEEP-tier articles).
            "active_from": published_at.isoformat() if published_at else common.time.utc_now().isoformat(),
            # active_until="" means still active / open-ended; S7 stores NULL.
            "active_until": "",
            # 90 days of residual market impact — conservative default matching
            # the structured EODHD events in PRD-0018 §6.5.
            "residual_impact_days": 90,
            "confidence": confidence,
            "exposed_entities": exposed_entities,
        }

        # Serialize BEFORE adding to outbox so a schema mismatch aborts the
        # transaction instead of poisoning the outbox with un-serializable bytes
        # (same pattern as _enqueue_signal_events / PLAN-0062 F-006).
        payload_bytes = serialize_confluent_avro(_TEMPORAL_EVENT_SCHEMA_PATH, payload)

        await outbox_repo.add(
            topic=settings.topic_temporal_event,
            # Partition by event_type so that all MACRO events land on the
            # same S7 partition, reducing out-of-order temporal event upserts.
            partition_key=raw_type,
            payload_avro=payload_bytes,
            # PLAN-0084 QA D-009: pass deterministic event_id so the outbox
            # INSERT ON CONFLICT (event_id) DO NOTHING guard deduplicates
            # Kafka re-deliveries of the same article at the outbox-table level.
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
    outbox_repo: OutboxRepository,
    settings: Any,
    doc_id: uuid.UUID,
    tenant_id: uuid.UUID,
    chunk_count: int,
    word_count: int,
) -> None:
    """Write nlp.document.ready.v1 event to the outbox for a tenant document.

    PLAN-0086 Wave F-1 (T-F-1-03): called inside the nlp_session transaction
    so the event is committed atomically with all NLP artifacts (sections,
    chunks, entity_mentions).  S4 ``DocumentReadyConsumer`` receives this
    event and calls ``TenantDocumentUploadRepository.set_ready()``.

    event_id uses a deterministic UUID5 derived from (doc_id, "document_ready_v1")
    so Kafka replays of the same doc produce the same outbox PK, and the
    INSERT ON CONFLICT DO NOTHING guard deduplicates them at the outbox level.
    """
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
    payload_bytes = serialize_confluent_avro(_NLP_DOCUMENT_READY_SCHEMA_PATH, payload)
    await outbox_repo.add(
        topic="nlp.document.ready.v1",
        partition_key=str(tenant_id),
        payload_avro=payload_bytes,
        # Deterministic event_id: ON CONFLICT DO NOTHING deduplicates replays.
        event_id=event_id,
    )


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False
