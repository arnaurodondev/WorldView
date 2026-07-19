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

import asyncio
import contextlib
import dataclasses
import json
import sys
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from common.ids import PUBLIC_TENANT_ID, uuid5_from_parts  # type: ignore[import-untyped]
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    _ASYNCPG_CONN_ERRORS,
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import FatalError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]
from nlp_pipeline.application.blocks.deep_extraction import run_deep_extraction_block
from nlp_pipeline.application.blocks.embeddings import run_embeddings_block
from nlp_pipeline.application.blocks.ner import run_ner_block
from nlp_pipeline.application.blocks.routing import _AUTHORITATIVE_FILING_SOURCES, compute_routing_score
from nlp_pipeline.application.blocks.sectioning import section_document
from nlp_pipeline.application.blocks.suppression import (
    apply_deep_extraction_value_gate,
    apply_suppression_gate,
    should_generate_chunk_embeddings,
    should_generate_section_embeddings,
    should_run_deep_extraction,
)
from nlp_pipeline.domain.enums import ProcessingPath, RoutingTier
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
from nlp_pipeline.infrastructure.messaging.consumers.blocks.persist import (
    persist_artifacts,
    persist_searchable_artifacts,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.provisional import (
    _collect_extraction_refs,
    synthesize_provisional_refs,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.signal_events import _enqueue_signal_events
from nlp_pipeline.infrastructure.messaging.consumers.blocks.storage import (
    download_article,
    extract_title_from_silver,
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
    record_learned_router_shadow,
    record_pre_persist_tenant_substituted,
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
    from nlp_pipeline.application.blocks.learned_routing import LearnedRouter
    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
    from nlp_pipeline.config import Settings
    from nlp_pipeline.domain.models import EntityMention, RoutingDecision
    from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository as OutboxRepositoryT
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "content.article.stored.v1"
_SCHEMA_DIR = find_schema_dir()
_DEFAULT_SOURCE_TRUST = 0.5

# Re-export block helpers so existing imports from this module remain valid.
__all__ = [
    "_SCHEMA_DIR",
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
    "synthesize_provisional_refs",
]


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


def _infer_block_source(mention: EntityMention) -> str:
    """Best-effort classifier mapping an offending mention back to its block.

    PLAN-0099 W2 T-W2-04 instrumentation.  Used only when the pre-persist
    safety net fires (``tenant_id is None`` at persist boundary), so this is
    not on the hot path.  We inspect domain fields that each block stamps:

    * Block 9 PROVISIONAL path → ``provisional_queue_id`` is set
    * Block 9 resolution path  → ``resolution_outcome`` is set
    * Block 4 NER              → only ``ner_model_id`` is set
    * Otherwise                → "unknown" (fall-through enum value)

    Block 10 (deep extraction) does not currently emit ``EntityMention`` rows
    but the enum reserves ``"deep_extraction"`` for forward-compat.

    The label vocabulary is bounded by ``PRE_PERSIST_BLOCK_SOURCES`` in
    ``infrastructure.metrics.prometheus`` to prevent Prometheus cardinality
    explosion.
    """
    if mention.provisional_queue_id is not None:
        return "novelty_backfill"
    if mention.resolution_outcome is not None:
        return "entity_resolution"
    if mention.ner_model_id is not None:
        return "ner"
    return "unknown"


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


class _PartitionCommitLedger:
    """Stream-spanning, per-partition contiguous-offset commit tracker.

    THROUGHPUT FIX (fix/nlp-throughput, 2026-07-19)
    ----------------------------------------------------------------
    The previous dispatch path (:meth:`ArticleProcessingConsumer._dispatch_batch`)
    processed a *whole* poll batch of up to ``article_consumer_concurrency``
    messages and BLOCKED on ``asyncio.gather`` until every one settled before
    polling the next batch — a batch barrier.  Because ~40% of live articles
    route to the DEEP tier (Qwen3-235B, p50 161s / p95 179s) a 16-message batch
    has a ~97% chance of containing at least one DEEP article, so nearly every
    batch was gated by ~170s while the 15 fast LIGHT/MEDIUM slots sat idle.
    Measured effect: ~16 / ~170s ≈ 5.6 articles/min/replica (~11/min platform),
    which matched prod exactly and defeated the value-gate's predicted speed-up
    (reducing DEEP *volume* does not help while a single DEEP article per batch
    still gates the barrier).

    The continuously-refilled loop admits a replacement message the instant any
    handler completes, so a fast LIGHT article never waits behind a slow DEEP
    one.  That requires committing offsets across the WHOLE stream rather than
    per batch, which this ledger does while preserving at-least-once:

      * :meth:`register` — called when a message is ADMITTED (Kafka guarantees
        per-partition offset order, so the first offset seen sets the cursor).
      * :meth:`settle` — called when its handler returns ``handled`` (True once
        the message succeeded OR durably dead-lettered; see ``_settle_message``).
      * :meth:`drain` — returns, per partition, the message at the top of the
        unbroken run of *settled-and-handled* offsets starting just after the
        last committed offset, and forgets those offsets.  A partition whose
        head offset is still in flight (registered, not settled) or settled
        ``False`` (barrier) yields nothing — the head-of-line guard that stops
        us ever committing past an un-settled offset (no silent-drop hole).
    """

    def __init__(self) -> None:
        # per (topic, partition): offset -> (msg, handled) where handled is
        # None while the offset is in flight, else the bool from ``_settle_message``.
        self._slots: dict[tuple[str, int], dict[int, tuple[Any, bool | None]]] = defaultdict(dict)
        # per (topic, partition): the next offset eligible to commit (the cursor
        # walks forward as the contiguous settled prefix fills in).
        self._cursor: dict[tuple[str, int], int] = {}

    def register(self, msg: Any) -> None:
        tp = (msg.topic(), msg.partition())
        offset = msg.offset()
        slots = self._slots[tp]
        if offset not in slots:
            slots[offset] = (msg, None)  # in flight
        # The first offset ever seen on a partition anchors the commit cursor to
        # exactly where our fetch position began — we never ack anything below it.
        if tp not in self._cursor:
            self._cursor[tp] = offset

    def settle(self, msg: Any, handled: bool) -> None:
        tp = (msg.topic(), msg.partition())
        self._slots[tp][msg.offset()] = (msg, bool(handled))

    def drain(self) -> list[Any]:
        """Advance every partition's contiguous settled prefix; return commit targets."""
        targets: list[Any] = []
        for tp, slots in self._slots.items():
            cursor = self._cursor.get(tp)
            if cursor is None:
                continue
            high_water: Any = None
            while cursor in slots:
                msg, handled = slots[cursor]
                if handled is not True:
                    # None  → head still in flight (stop; do not ack past it).
                    # False → settle asked for a commit barrier (retry on restart).
                    break
                high_water = msg
                del slots[cursor]  # committed prefix → forget to bound memory
                cursor += 1
            self._cursor[tp] = cursor
            if high_water is not None:
                targets.append(high_water)
        return targets


class ArticleProcessingConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Orchestrates S6 Blocks 3-10.  Processing logic is in ``blocks/`` modules.

    Idempotency (PLAN-0084 B-3): ValkeyDedupMixin + deterministic IDs everywhere.
    """

    _dedup_prefix: str = "nlp:dedup:article_consumer"
    _dedup_ttl_seconds: ClassVar[int] = 86400

    # ------------------------------------------------------------------
    # Persistent-retry attempt counter (transient-failure resilience).
    #
    # With ``enable_persistent_retry=True`` the base retry path needs a DURABLE
    # attempt count keyed by (group_id, event_id).  We reuse the Valkey dedup
    # client (``_dedup_client``) as the durable store: an INCR per failure plus a
    # TTL so the key self-expires once the doc recovers or dead-letters.  Without
    # this, the count resets to 0 on every redelivery and a transiently-failing
    # doc loops until ``dead_letter_cap`` crashes the consumer instead of
    # dead-lettering cleanly at ``max_retries``.
    # ------------------------------------------------------------------
    _RETRY_ATTEMPT_PREFIX: ClassVar[str] = "nlp:retry:article_consumer"
    # TTL long enough to outlive a redelivery backoff cycle but short enough that
    # the counter does not linger forever after the doc succeeds / dead-letters.
    _RETRY_ATTEMPT_TTL_SECONDS: ClassVar[int] = 86400

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
        learned_router: LearnedRouter | None = None,
        entailment_client: ExtractionClient | None = None,
        entailment_config: Any = None,
        evidence_grounding_config: Any = None,
        claim_entailment_client: ExtractionClient | None = None,
        claim_entailment_config: Any = None,
    ) -> None:
        super().__init__(config)
        self._dedup_client = valkey_client
        # PLAN-0111 C-6: optional learned router. None when mode == "off" (the
        # main entry point only constructs it for shadow/live). The consumer
        # treats None as "no shadow proposal", so behaviour is identical to the
        # pre-PLAN-0111 pipeline when the feature is off.
        self._learned_router = learned_router
        self._settings = settings
        self._nlp_sf = nlp_session_factory
        self._intel_sf = intelligence_session_factory
        self._storage = storage
        self._watchlist = watchlist_cache
        self._ner = ner_client
        self._emb = embedding_client
        self._ext = extraction_client
        # ENHANCEMENT #6: cheap co-mention entailment client (Qwen3-235B) + config.
        # None when the feature is off → run_ml_phase forwards None and the check no-ops.
        self._entailment_client = entailment_client
        self._entailment_config = entailment_config
        # 2026-07-16 fabrication filter: deterministic evidence-span grounding gate.
        # Never None in the main entry point (built unconditionally from settings); a
        # None here (e.g. a test) makes run_deep_extraction_block apply its own default
        # (present_only), so the gate is active by default.
        self._evidence_grounding_config = evidence_grounding_config
        # 2026-07-16 claim entailment pass: cheap verifier client (DeepSeek-V4-Flash) +
        # config. None when the feature is off → run_ml_phase forwards None and the pass
        # no-ops (unchanged behaviour).
        self._claim_entailment_client = claim_entailment_client
        self._claim_entailment_config = claim_entailment_config
        self._bp = backpressure
        self._chunk_text_store = chunk_text_store
        self._usage_logger = usage_logger

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    def _retry_attempt_key(self, event_id: str) -> str:
        """Build the Valkey key for *event_id*'s persistent attempt counter.

        Namespaced by the consumer group so two consumer groups replaying the
        same event id never share (and corrupt) each other's count.
        """
        return f"{self._RETRY_ATTEMPT_PREFIX}:{self._config.group_id}:{event_id}"

    async def _get_attempt_count(self, event_id: str) -> int:
        """Return the number of FAILED attempts already recorded for *event_id*.

        Reads the durable count from Valkey.  ``0`` means no prior failure.

        Fail-closed semantics: if there is NO Valkey client, or the read raises
        (Valkey down), we cannot trust the in-memory count — which would reset to
        0 on every redelivery and loop the doc forever.  Returning
        ``max_retries`` instead forces the base retry path to treat the doc as
        exhausted and route it to the DLQ rather than retry indefinitely.
        """
        if self._dedup_client is None:
            return self._config.max_retries
        key = self._retry_attempt_key(event_id)
        try:
            raw = await self._dedup_client.get(key)
        except Exception:
            # Valkey unreachable: fail closed toward the DLQ (see docstring).
            logger.warning(
                "article_consumer.retry_count_read_failed",
                event_id=event_id,
                key=key,
                exc_info=True,
            )
            return self._config.max_retries
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            # Corrupt value — treat as exhausted rather than risk an infinite loop.
            logger.warning(
                "article_consumer.retry_count_corrupt",
                event_id=event_id,
                key=key,
                raw=raw,
            )
            return self._config.max_retries

    async def _record_attempt(self, event_id: str, attempt: int, error: BaseException) -> None:
        """Persist the incremented attempt count for *event_id* (best-effort).

        Uses an atomic INCR plus a refreshed TTL so the counter survives
        redelivery but self-expires after recovery / DLQ.  Write failures are
        swallowed (logged only): a crash here would take down the consumer, and
        the base retry path already records the in-memory attempt number.
        """
        if self._dedup_client is None:
            return
        key = self._retry_attempt_key(event_id)
        try:
            await self._dedup_client.incr(key)
            await self._dedup_client.expire(key, self._RETRY_ATTEMPT_TTL_SECONDS)
        except Exception:
            logger.warning(
                "article_consumer.retry_count_write_failed",
                event_id=event_id,
                attempt=attempt,
                key=key,
                exc_info=True,
            )

    # ── Task #14: bounded-concurrency poll loop ─────────────────────────────────
    #
    # WHY OVERRIDE ``run`` HERE (not in libs/messaging.BaseKafkaConsumer):
    # The base loop is strictly serial — poll one message, ``await`` the full
    # pipeline (which includes a 12-22s DeepInfra deep-extraction round-trip),
    # commit that single offset, then poll the next.  A replica therefore spends
    # ~20s idle on network wait per article, so 3 replicas process only ~3
    # articles at a time (~500/hr).  Deep extraction is I/O-bound, not CPU-bound,
    # so a single replica can overlap many DeepInfra waits.  The base loop is
    # shared by ~30 consumers across the platform, so we do NOT touch it; instead
    # the article consumer overrides ``run`` to dispatch up to
    # ``article_consumer_concurrency`` message handlers concurrently per poll
    # batch.  K=16 x 3 replicas reaches ~48 articles in flight platform-wide.
    #
    # OFFSET-COMMIT CORRECTNESS (at-least-once + per-partition ordering):
    # confluent-kafka's ``commit(message=msg)`` commits ``msg.offset()+1`` for
    # that message's partition, which *implicitly* acks every lower offset on the
    # partition.  Under concurrency a later offset may finish before an earlier
    # one on the same partition, so committing it eagerly would skip the unfinished
    # earlier message on a crash (data loss).  To preserve at-least-once we:
    #   1. Group the poll batch by (topic, partition).
    #   2. Dispatch every message as a task, bounded by a shared semaphore.
    #   3. After the whole batch settles, for each partition commit ONLY the
    #      highest *contiguous* successfully-handled offset starting from the
    #      lowest offset in the batch.  A message that hit an un-handled exception
    #      breaks the contiguous run, so its offset (and everything after it on
    #      that partition) is re-polled on the next cycle / after rebalance.
    #
    # POISON / FAILURE HANDLING (see ``_settle_message``): a failing message is
    # settled WITHOUT a consumer ``seek()`` — it is retried in place (async
    # backoff) up to ``max_retries`` and then durably dead-lettered, at which
    # point it counts as "handled" so the partition DRAINS past it.  This is the
    # nlp-consumer-commit-stall fix: the old path called the base
    # ``_handle_failure`` whose seek-back re-pinned the partition head under
    # concurrency and froze the committed offset forever.  Idempotency
    # (ValkeyDedupMixin + deterministic UUID5 IDs + idempotent upserts + the
    # routing_decisions already-processed guard in ``process_message``) makes the
    # in-place retries and any re-delivery safe.  The offset is committed
    # SYNCHRONOUSLY (see ``_commit_sync``) so a rejected commit is logged, not
    # silently dropped by confluent's default fire-and-forget async commit.
    #
    # Messages are keyed by ``doc_id`` upstream (S5), so two events for the same
    # document land on the same partition and are dispatched in offset order;
    # concurrency across partitions never races two events for one document.
    async def run(self) -> None:  # type: ignore[override]
        """Bounded-concurrency poll loop (see class-level Task #14 docstring)."""
        self._init_kafka()
        retry_task = asyncio.create_task(self._retry_loop())
        probe_task = asyncio.create_task(self._connectivity_probe_loop())

        def _on_task_done(task: asyncio.Task[None]) -> None:  # type: ignore[type-arg]
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.critical("article_consumer_bg_task_crashed", exc_info=exc)  # type: ignore[no-any-return]
                sys.exit(1)

        retry_task.add_done_callback(_on_task_done)
        probe_task.add_done_callback(_on_task_done)

        concurrency = max(1, int(getattr(self._settings, "article_consumer_concurrency", 16)))
        logger.info(  # type: ignore[no-any-return]
            "article_consumer_concurrency_enabled",
            concurrency=concurrency,
            mode="pipelined",  # continuously-refilled window (fix/nlp-throughput)
            group_id=self._config.group_id,
        )

        # THROUGHPUT FIX (fix/nlp-throughput): a CONTINUOUSLY-REFILLED window
        # instead of the old poll-a-batch → gather-whole-batch → poll-next barrier.
        # ``inflight`` holds at most ``concurrency`` handler tasks; the instant one
        # finishes we poll+admit a replacement, so a fast LIGHT article never idles
        # behind a slow DEEP (Qwen3-235B ~170s) article that happened to share its
        # poll batch.  ``ledger`` commits offsets across the whole stream (not per
        # batch) while preserving the SAME at-least-once contract: an offset is
        # acked only once every lower offset on its partition has settled.
        ledger = _PartitionCommitLedger()
        inflight: set[asyncio.Task[None]] = set()
        loop = asyncio.get_event_loop()

        async def _worker(message: Any) -> None:
            # ``_settle_message`` is contractually non-raising (it succeeds,
            # retries in place, or durably dead-letters), but guard anyway: an
            # unexpected escape must NOT leave the offset un-settled forever and
            # pin its partition's commit cursor.  Recording ``False`` holds a
            # commit barrier so the message is re-read after a restart/rebalance
            # rather than silently acked (at-least-once preserved).
            try:
                handled = await self._settle_message(message)
            except Exception as settle_exc:
                logger.critical(  # type: ignore[no-any-return]
                    "article_consumer.settle_unexpected_error",
                    topic=message.topic(),
                    partition=message.partition(),
                    offset=message.offset(),
                    exc_info=settle_exc,
                )
                handled = False
            ledger.settle(message, handled)

        async def _commit_ready() -> None:
            for target in ledger.drain():
                if self._config.enable_auto_commit:
                    continue
                try:
                    # SYNCHRONOUS commit on the executor thread (see _commit_sync):
                    # a rejected offset commit is logged, never silently dropped.
                    await loop.run_in_executor(None, self._commit_sync, target)
                except Exception as commit_exc:
                    logger.warning(  # type: ignore[no-any-return]
                        "article_consumer.offset_commit_failed",
                        topic=target.topic(),
                        partition=target.partition(),
                        offset=target.offset(),
                        error=str(commit_exc),
                    )
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, self._record_consumer_lag)

        try:
            while not self._stop_event.is_set():
                # Honour the opt-in backpressure pause exactly like the base loop.
                self._maybe_apply_backpressure()

                if len(inflight) >= concurrency:
                    # Window full: park until a handler frees a slot (done tasks
                    # remove themselves via the add_done_callback below), then
                    # commit whatever newly-contiguous prefix completed and refill.
                    await asyncio.wait(inflight, return_when=asyncio.FIRST_COMPLETED)
                    # BP-704 liveness: a completed handler is real progress.
                    self._record_progress()
                    await _commit_ready()
                    continue

                # Poll only up to the free slots so ``inflight`` never exceeds the
                # concurrency bound.  ``_poll_batch`` blocks up to poll_timeout on
                # its first poll (idle topic → no busy-spin) then drains buffered.
                free = concurrency - len(inflight)
                batch = await self._poll_batch(loop, free)
                # BUG-1 (2026-06-22 e2e-coverage audit): heartbeat on EVERY poll
                # cycle (idle OR message) so ``seconds_since_progress`` never
                # stays None and /healthz does not falsely 503.
                self._record_progress()

                for message in batch:
                    ledger.register(message)  # register BEFORE dispatch: preserves
                    task = asyncio.create_task(_worker(message))  # per-partition
                    inflight.add(task)  # offset order for the commit cursor
                    task.add_done_callback(inflight.discard)

                await _commit_ready()

                if not batch and inflight:
                    # Nothing new to admit but slots are still draining: wait for a
                    # completion (bounded by poll_timeout) so we neither busy-spin
                    # nor delay committing offsets that finish during the lull.
                    await asyncio.wait(
                        inflight,
                        timeout=self._config.poll_timeout_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    await _commit_ready()
        finally:
            # Drain in-flight handlers so their offsets settle and commit before we
            # tear down Kafka — otherwise at-shutdown work would be re-read (and
            # re-paid to DeepInfra) on the next start.
            if inflight:
                await asyncio.gather(*inflight, return_exceptions=True)
                with contextlib.suppress(Exception):
                    await _commit_ready()
            retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry_task
            probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await probe_task
            self._shutdown_kafka()

    async def _poll_batch(self, loop: Any, max_records: int) -> list[Any]:
        """Drain up to ``max_records`` messages without blocking on an empty topic.

        The first ``poll`` blocks up to ``poll_timeout_seconds`` so an idle
        consumer does not busy-spin; subsequent polls use a 0s timeout to grab
        whatever is already buffered, then stop.  This bounds a batch to roughly
        one concurrency-window of in-flight work so memory stays predictable.
        """
        from confluent_kafka import KafkaError

        batch: list[Any] = []
        first = True
        while len(batch) < max_records and not self._stop_event.is_set():
            timeout = self._config.poll_timeout_seconds if first else 0.0
            first = False
            msg = await loop.run_in_executor(None, self._consumer.poll, timeout)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("kafka_poll_error", error=str(msg.error()))  # type: ignore[no-any-return]
                continue
            batch.append(msg)
        return batch

    async def _dispatch_batch(self, loop: Any, batch: list[Any], sem: asyncio.Semaphore) -> None:
        """Process a poll batch concurrently and commit contiguous offsets.

        Returns once every message in the batch has settled.  See the class-level
        Task #14 docstring for the at-least-once / ordering guarantees.
        """
        # outcomes[(topic, partition)] = {offset: handled_ok}
        outcomes: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)

        async def _process_one(msg: Any) -> None:
            tp = (msg.topic(), msg.partition())
            offset = msg.offset()
            async with sem:
                # ``_settle_message`` NEVER seeks and NEVER blocks the loop; it
                # returns True once the message is settled (succeeded OR durably
                # dead-lettered) so the contiguous commit can drain the partition
                # PAST a poison article instead of pinning its head forever.
                outcomes[tp][offset] = await self._settle_message(msg)

        await asyncio.gather(*(_process_one(m) for m in batch))

        # Commit the highest contiguous handled offset per partition.  We rebuild
        # one synthetic commit message per partition at that offset so confluent's
        # implicit "commit offset+1" semantics ack exactly the contiguous prefix.
        # ``_commit_to_offset`` finds, among each partition's batch messages, the
        # one whose offset equals the contiguous high-water mark and commits it.
        commit_targets = self._contiguous_commit_targets(batch, outcomes)
        for msg in commit_targets:
            if self._config.enable_auto_commit:
                continue
            try:
                # SYNCHRONOUS commit (asynchronous=False).  confluent's DEFAULT
                # ``commit(msg)`` is fire-and-forget (asynchronous=True): it never
                # raises and, with no ``on_commit`` callback registered, drops
                # every failure silently — so a rejected offset commit vanished
                # and the partition's committed offset froze with no signal
                # (the root cause of the nlp-consumer-commit-stall). Block on the
                # broker ack (on the executor thread, not the event loop) and LOG
                # failures so a stuck commit is observable instead of a silent
                # freeze.  The ack costs ~1 RTT and runs once per poll batch.
                await loop.run_in_executor(None, self._commit_sync, msg)
            except Exception as commit_exc:
                logger.warning(  # type: ignore[no-any-return]
                    "article_consumer.offset_commit_failed",
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                    error=str(commit_exc),
                )
        with contextlib.suppress(Exception):
            await loop.run_in_executor(None, self._record_consumer_lag)

    def _commit_sync(self, msg: Any) -> None:
        """Synchronously commit *msg*'s offset (blocks until the broker acks).

        Runs on the default executor thread — never the event loop.  Synchronous
        (``asynchronous=False``) so a commit rejection surfaces as an exception
        the caller LOGS, rather than confluent's default async commit that drops
        errors on the floor.  confluent commits ``msg.offset() + 1`` for the
        message's partition, implicitly acking every lower offset.
        """
        self._consumer.commit(message=msg, asynchronous=False)

    async def _safe_event_id(self, msg: Any) -> str:
        """Best-effort event_id for retry-counter keying / DLQ (never raises)."""
        try:
            value = self.deserialize_value(msg.value() or b"", self.get_schema_path(msg.topic()))
            return self.extract_event_id(value)
        except Exception:
            return f"{msg.topic()}/{msg.partition()}/{msg.offset()}"

    async def _settle_message(self, msg: Any) -> bool:
        """Process one message; return True once its offset MAY advance.

        HEAD-OF-LINE FIX (fix/nlp-consumer-commit-stall, 2026-07-17)
        ----------------------------------------------------------------
        The previous concurrent path routed failures through the base
        ``_handle_failure`` whose ``enable_persistent_retry`` branch calls
        ``consumer.seek()`` + a *blocking* ``time.sleep()``.  ``seek()`` is a
        GLOBAL operation on the shared librdkafka consumer; issuing it from one
        of up to ``article_consumer_concurrency`` CONCURRENT ``_process_one``
        tasks re-pins the partition's fetch position to the failing offset while
        other offsets on the same partition are still in flight.  A message that
        keeps failing (observed live: ``dlq-recover``-tagged SEC-filing events)
        therefore pinned its partition's committed offset FOREVER — a permanent
        head-of-line freeze — while the rest of the backlog was re-read and
        re-paid to DeepInfra on every cycle/restart.  ``_process_one`` also
        ignored ``_handle_failure``'s ``False`` "commit-barrier" return, so the
        contract was doubly broken.

        This method fixes it with a concurrency-safe settle policy that NEVER
        seeks and NEVER blocks the event loop:

          1. Run the pipeline; on success return True (advance).
          2. On a transient error, retry IN PLACE up to ``max_retries`` attempts
             with async exponential backoff.  The durable Valkey attempt counter
             (``_get_attempt_count`` / ``_record_attempt``) bounds retries ACROSS
             redeliveries/restarts too, so a poison cannot loop forever.
          3. On exhaustion (or a non-retryable ``FatalError`` such as a malformed
             payload) DEAD-LETTER the message durably (nlp_db.dlq) and return
             True so the contiguous commit drains the partition PAST the poison.

        At-least-once is preserved: an offset advances only after the message
        SUCCEEDS or is durably dead-lettered.  Idempotency (ValkeyDedupMixin +
        the routing_decisions already-processed guard + deterministic IDs) makes
        the in-place retries and any redelivery safe.
        """
        event_id = await self._safe_event_id(msg)
        offset = msg.offset()
        # Durable count survives redelivery/restart, so a message that fails, is
        # redelivered, and fails again ESCALATES toward the DLQ instead of getting
        # a fresh full retry budget every time.  ``_durable_attempt_count`` fails
        # OPEN (returns 0 on any Valkey unavailability): the in-place retry budget
        # below is bounded regardless, so an unreadable counter must NOT collapse
        # the budget to 0 and dead-letter good work on its first failure during a
        # Valkey blip (that would be a silent-drop at-least-once hole).
        base_attempts = await self._durable_attempt_count(event_id)
        max_retries = max(1, self._config.max_retries)

        for local_attempt in range(max_retries):
            attempt = base_attempts + local_attempt + 1
            try:
                try:
                    await self._handle_message(msg)
                except _ASYNCPG_CONN_ERRORS as conn_exc:
                    # Stale asyncpg pool after a Postgres restart: one quick retry
                    # gives the pool a chance to evict the dead connection.
                    logger.warning(  # type: ignore[no-any-return]
                        "consumer_db_connection_lost_retrying",
                        error=str(conn_exc),
                        topic=msg.topic(),
                        partition=msg.partition(),
                        offset=offset,
                    )
                    await asyncio.sleep(1.0)
                    await self._handle_message(msg)
                return True  # settled: success → offset may advance
            except FatalError as exc:
                # Non-retryable (malformed / schema / business-rule): dead-letter.
                # ADVANCE only if the DLQ write DURABLY persisted the message —
                # otherwise return False (barrier) so it is retried, never dropped.
                return await self._dead_letter_poison(msg, exc, event_id=event_id, reason="fatal")
            except Exception as exc:
                await self._record_attempt(event_id, attempt, exc)
                if attempt >= max_retries:
                    # Retries exhausted → dead-letter.  ADVANCE (drain the poison)
                    # ONLY if the DLQ write succeeded; if the DLQ store itself is
                    # down (e.g. Postgres outage) return False so the partition
                    # holds at this offset and the message is retried on the next
                    # rebalance/restart rather than SILENTLY DROPPED.
                    return await self._dead_letter_poison(msg, exc, event_id=event_id, reason="max_retries")
                logger.warning(  # type: ignore[no-any-return]
                    "article_consumer.transient_retry_in_place",
                    event_id=event_id,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(exc),
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=offset,
                )
                # Async backoff — does NOT block the event loop (contrast the base
                # ``_seek_back``'s ``time.sleep``) and does NOT seek the consumer.
                await asyncio.sleep(self._compute_backoff(attempt))

        # Defensive: the loop always returns above.  Advance rather than risk a
        # silent re-freeze.
        return True

    async def _durable_attempt_count(self, event_id: str) -> int:
        """Prior durable attempt count for *event_id*, failing OPEN on Valkey errors.

        Unlike the base ``_get_attempt_count`` (which fails CLOSED to
        ``max_retries`` so the SERIAL retry loop cannot spin forever), the
        concurrent settle path bounds retries IN PLACE regardless, so a Valkey
        outage must NOT immediately dead-letter a message on its first failure —
        that would drop good work during a transient Valkey blip.  We therefore
        treat an unreadable / absent / corrupt counter as ``0`` (no prior
        attempts) and let the bounded in-place retry budget run.
        """
        client = self._dedup_client
        if client is None:
            return 0
        try:
            raw = await client.get(self._retry_attempt_key(event_id))
        except Exception:
            return 0
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def _dead_letter_poison(
        self,
        msg: Any,
        exc: BaseException,
        *,
        event_id: str,
        reason: str,
    ) -> bool:
        """Durably dead-letter a poison message; return whether its offset may advance.

        Builds a :class:`FailureInfo` carrying the ORIGINAL ``msg.value()`` bytes
        (so the DLQ row is re-ingestable) and routes it through
        :meth:`dead_letter` (→ ``_dead_letter_impl`` → ``nlp_db.dlq``).

        Returns:
            ``True``  — the message was DURABLY dead-lettered, so the partition
                        may commit PAST it (drain the poison).
            ``False`` — the DLQ write itself FAILED (e.g. the ``nlp_db`` store is
                        down during a Postgres outage).  The offset must NOT
                        advance: returning False makes ``_settle_message`` leave
                        this offset as a commit barrier so the message is retried
                        on the next rebalance/restart rather than SILENTLY
                        DROPPED.  We accept a temporary head-of-line block on this
                        one partition until the DLQ store recovers — never a lost
                        article.  (The dead_letter-cap ``RuntimeError`` is
                        deliberately re-raised: it is an intentional poison-storm
                        crash signal handled by the run loop's supervisor.)
        """
        failure: FailureInfo[None] = FailureInfo(
            event_id=event_id,
            topic=msg.topic(),
            partition=msg.partition(),
            offset=msg.offset(),
            attempt=self._config.max_retries,
            last_error=exc,
            raw_payload=msg.value() or b"",
        )
        try:
            await self.dead_letter(failure, reason=reason)
        except RuntimeError:
            # dead_letter cap exceeded — intentional force-restart signal.
            raise
        except Exception:
            # DLQ WRITE FAILED → do NOT advance: better a temporary head-of-line
            # block than a silently-dropped article (at-least-once).
            logger.error(  # type: ignore[no-any-return]
                "article_consumer.dead_letter_write_failed_holding_offset",
                event_id=event_id,
                reason=reason,
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                error=str(exc)[:200],
                exc_info=True,
            )
            return False
        logger.error(  # type: ignore[no-any-return]
            "article_consumer.poison_dead_lettered_advanced",
            event_id=event_id,
            reason=reason,
            topic=msg.topic(),
            partition=msg.partition(),
            offset=msg.offset(),
            error=str(exc)[:200],
        )
        return True

    @staticmethod
    def _contiguous_commit_targets(batch: list[Any], outcomes: dict[tuple[str, int], dict[int, bool]]) -> list[Any]:
        """Return, per partition, the batch message at the highest contiguous handled offset.

        Sorts each partition's messages by offset and walks forward while each
        offset is present-and-handled, stopping at the first gap or failure.  The
        message at that high-water mark is committed (confluent acks offset+1,
        implicitly acking every lower offset).  If the *first* message of a
        partition was not handled, nothing is committed for it.
        """
        by_partition: dict[tuple[str, int], list[Any]] = defaultdict(list)
        for msg in batch:
            by_partition[(msg.topic(), msg.partition())].append(msg)

        targets: list[Any] = []
        for tp, msgs in by_partition.items():
            msgs.sort(key=lambda m: m.offset())
            handled = outcomes.get(tp, {})
            high_water: Any = None
            for msg in msgs:
                if handled.get(msg.offset()) is True:
                    high_water = msg
                else:
                    break  # gap / failure → stop the contiguous run here
            if high_water is not None:
                targets.append(high_water)
        return targets

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
        # PLAN-0056 Wave C2b: upstream market/source identity (e.g.
        # "polymarket:<condition_id>"), threaded verbatim from content.article.stored.v1
        # onto the enriched event so the KG can resolve prediction docs to a real
        # market.  Absent on legacy/non-prediction events → None (pure passthrough,
        # no NER/extraction change).
        external_id: str | None = value.get("external_id") or None

        # ── Tenant resolution with legacy-passthrough sentinel (PLAN-0096 W4) ──
        # Pre-PLAN-0086 Avro payloads have no ``tenant_id`` field.  Migration
        # 0020 added ``NOT NULL`` on ``entity_mentions.tenant_id``; without a
        # sentinel, every legacy message dies on the INSERT, the consumer's
        # exception handler treats it as retryable, offsets never commit,
        # and the topic stalls (BP-575).  Substitute ``PUBLIC_TENANT_ID``
        # for any missing / unparseable tenant so the row inserts cleanly
        # and the offset advances — the row is still identifiable in
        # forensics because the sentinel is the all-zero UUID.
        raw_tenant = headers.get("tenant_id") or value.get("tenant_id") or None
        tenant_id: uuid.UUID | None = None
        if raw_tenant:
            with contextlib.suppress(ValueError, AttributeError):
                tenant_id = uuid.UUID(str(raw_tenant))
        if tenant_id is None:
            tenant_id = PUBLIC_TENANT_ID
            logger.warning(  # type: ignore[no-any-return]
                "article_consumer.legacy_tenant_id_sentinel_applied",
                article_id=str(doc_id),
                topic=_TOPIC,
                partition=headers.get("__partition"),
                offset=headers.get("__offset"),
                raw_tenant=raw_tenant,
                sentinel=str(PUBLIC_TENANT_ID),
            )

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

        # BUG #35: sec_edgar/newsapi events carry no ``title`` → NULL
        # ``chunks.title_denorm`` → the learned router scores the doc near-floor
        # and dumps it to LIGHT (no deep extraction).  When the event has no
        # title, recover it from the silver envelope (NewsAPI's title lives in
        # the inner raw-news JSON re-encoded into ``body``; see BUG #34).  This
        # is best-effort — genuine title-less docs (most sec_edgar filings)
        # still fall through to the C-8 degenerate-input fallback in
        # ``_apply_live_learned_tier``.
        if not (doc_title or "").strip():
            recovered_title = await extract_title_from_silver(self._storage, self._settings.silver_bucket, minio_key)
            if recovered_title:
                doc_title = recovered_title
                logger.info(  # type: ignore[no-any-return]
                    "article_consumer.title_recovered_from_silver",
                    doc_id=str(doc_id),
                    source_type=source_type,
                )

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
                external_id=external_id,
                published_at=published_at,
                extracted_at=extracted_at,
                is_backfill=is_backfill,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                doc_title=doc_title,
                # PLAN-0056 Wave C3: carry the (recovered) document title onto the
                # enriched event as source_title.  For a Polymarket synthetic doc
                # this IS the market question — the KG needs it to title the
                # prediction temporal event and classify per-entity polarity.
                source_title=doc_title,
            )

        url = value.get("url") or await extract_url_from_silver(self._storage, self._settings.silver_bucket, minio_key)
        await self._write_source_metadata(
            doc_id=doc_id,
            # BUG #35: persist the recovered title (not the bare event field) so
            # document_source_metadata.title is populated for sec_edgar/newsapi too.
            title=doc_title or value.get("title"),
            url=url,
            published_at=published_at,
            source_name=source_name,
            source_type=source_type,
            word_count=value.get("word_count"),
        )

    async def _run_learned_router_shadow(
        self,
        *,
        routing_decision: RoutingDecision,
        doc_title: str | None,
        lede: str | None,
        source_type: str | None = None,
    ) -> None:
        """Compute the learned-router proposal; in LIVE mode let it control routing.

        PLAN-0111 C-6 (call site moved + lede wired in #33). This NEVER changes
        the processing path: it only

          1. calls ``LearnedRouter.propose`` (best-effort — returns None on
             failure) to get a calibrated P(yield) + proposed tier,
          2. stamps ``learned_tier`` / ``learned_p_yield`` / ``learned_router_mode``
             onto ``routing_decision`` so persist_artifacts writes them to
             routing_decisions,
          3. emits a ``learned_router_shadow`` structlog line comparing the actual
             (static) tier with the proposed tier, and
          4. increments the {actual_tier, proposed_tier} Prometheus counter.

        TRAIN/SERVE PARITY (PLAN-0111 #33 — fixes the skew diagnosed in
        ``docs/audits/2026-06-13-learned-router-shadow-analysis.md``):
        the model was trained on ``embed(title + "\\n" + subtitle)`` where
        ``subtitle`` is the article LEDE (the doc's first chunk text, run through
        ``subtitle_from_lede``). The original C-6 wiring ran this BEFORE chunking
        and so had no lede available — it passed ``subtitle=None`` and embedded
        the TITLE ALONE. That fed the model half its expected input and caused
        systematic over-suppression (24h shadow: 0% DEEP proposed, 80% LIGHT,
        5.3% agreement). We now run this AFTER ``run_embeddings_block`` produces
        chunks and pass the real first-chunk ``lede`` as the subtitle.

        WHY running post-chunking is safe: Sub-Plan B made chunk embedding
        UNIVERSAL (every non-SUPPRESS tier is embedded regardless of routing
        tier), so the routing gate no longer needs to run before embedding — it
        only needs to precede EXTRACTION (Block 8). Moving the call after Block 7
        is therefore behaviour-preserving for the static (deployed) router while
        finally giving the shadow router the lede it was trained on.

        ``lede`` is the RAW first-chunk text (caller picks chunk_index ascending,
        first non-null) — deliberately NOT cleaned, see ``subtitle_from_lede``.

        Everything is inside a broad try/except: the learned router is a passive
        observer and a failure here must not fail the article. The mode is always
        recorded (even on failure) so a NULL learned_tier with a non-NULL mode is
        distinguishable from "router was off entirely".
        """
        from nlp_pipeline.application.blocks.learned_routing import subtitle_from_lede

        mode = self._settings.learned_router_mode
        if mode == "off" or self._learned_router is None:
            return

        # Record the mode regardless of outcome (so rows are attributable).
        routing_decision.learned_router_mode = mode

        # The actual (deployed) tier that CONTROLS processing — unchanged below.
        actual_tier = routing_decision.routing_tier
        actual_tier_value = actual_tier.value if hasattr(actual_tier, "value") else str(actual_tier)

        try:
            # The 3 structured features the model was trained on are exactly the
            # values already computed by the static router (same source). We pass
            # the whole feature_scores dict; LearnedRouter picks the trained
            # subset (source_reliability, recency, document_type) in order.
            #
            # The subtitle is the article LEDE (first chunk text) put through the
            # SAME transform the training dataset used (subtitle_from_lede). This
            # closes the train/serve skew — see method docstring + the 2026-06-13
            # audit. ``lede`` is None only when the doc produced no chunks (e.g.
            # empty body); then subtitle_from_lede("") -> "" and propose falls
            # back to title-only, matching training rows with an empty lede.
            subtitle = subtitle_from_lede(lede)
            result = await self._learned_router.propose(
                title=doc_title,
                subtitle=subtitle,
                structured_features=routing_decision.feature_scores,
            )
            if result is None:
                # Propose already logged the failure cause. Leave learned_tier
                # NULL; mode is set so the row is still attributable to shadow.
                return

            routing_decision.learned_tier = result.proposed_tier
            routing_decision.learned_p_yield = result.p_yield

            proposed_tier_value = (
                result.proposed_tier.value if hasattr(result.proposed_tier, "value") else str(result.proposed_tier)
            )
            logger.info(  # type: ignore[no-any-return]
                "learned_router_shadow",
                doc_id=str(routing_decision.doc_id),
                actual_tier=actual_tier_value,
                proposed_tier=proposed_tier_value,
                p_yield=round(result.p_yield, 4),
                agreement=(actual_tier_value == proposed_tier_value),
                in_ambiguous_band=result.in_ambiguous_band,
                cascade_used=result.cascade_used,
                cascade_relevance=(
                    round(result.cascade_relevance, 4) if result.cascade_relevance is not None else None
                ),
                mode=mode,
            )
            record_learned_router_shadow(actual_tier_value, proposed_tier_value)

            # ── PLAN-0111 C-8: LIVE control ───────────────────────────────────
            # In LIVE mode the (post-cascade) learned tier CONTROLS processing.
            # We achieve this by writing the EFFECTIVE tier onto
            # ``final_routing_tier`` — the field ``apply_suppression_gate`` and
            # every downstream gate already read first (``final_routing_tier or
            # routing_tier``). The STATIC tier stays in ``routing_tier`` so the
            # two are persisted side-by-side for ongoing comparison.
            #
            # In SHADOW / off the learned tier is observational only — we never
            # touch ``final_routing_tier`` (that is the shadow invariant).
            if mode == "live":
                self._apply_live_learned_tier(
                    routing_decision=routing_decision,
                    learned_tier=result.proposed_tier,
                    doc_title=doc_title,
                    source_type=source_type,
                )
        except Exception:  # — observer/live-control must never fail the article
            logger.warning(  # type: ignore[no-any-return]
                "learned_router_shadow_failed",
                doc_id=str(routing_decision.doc_id),
                exc_info=True,
            )

    def _apply_live_learned_tier(
        self,
        *,
        routing_decision: RoutingDecision,
        learned_tier: RoutingTier,
        doc_title: str | None,
        source_type: str | None,
    ) -> None:
        """LIVE mode (PLAN-0111 C-8): make the learned tier control processing.

        Writes the EFFECTIVE tier onto ``routing_decision.final_routing_tier``
        (the field every downstream gate reads first). The STATIC tier remains
        in ``routing_tier`` for side-by-side comparison.

        Three INVARIANTS are preserved — the learned gate must NOT silently
        discard high-value documents:

        1. DEGENERATE-INPUT FALLBACK (title-less docs). The learned classifier
           reads ``title + lede`` and is effectively BLIND without a title:
           title-less docs (NULL/empty ``title_denorm``) score a near-floor
           ``p_yield`` (~0.18) and would be dumped to LIGHT. ~111 such docs
           exist (86 sec_edgar + 25 newsapi); sec_edgar is the corpus's
           highest-value source. So when the title is missing/blank we DO NOT
           let the learned tier control — we keep the STATIC tier for that doc
           (i.e. leave ``final_routing_tier`` unset) and log
           ``learned_router_titleless_fallback`` so the rate is measurable.

        2. SUPPRESS preservation. The learned classifier never PRODUCES SUPPRESS
           (``map_p_yield_to_tier`` emits DEEP/MEDIUM/LIGHT only). If the STATIC
           router suppressed a doc (``routing_tier == SUPPRESS``), live mode does
           NOT resurrect it — SUPPRESS must still HALT. We leave the static
           SUPPRESS in place rather than overriding with a learned LIGHT/MEDIUM.

        3. REGULATORY-FILING / AUTHENTICATED-UPLOAD override. Authoritative
           filings (sec_edgar, sec_8k/10k/10q/def14a, tenant_upload) are forced
           to at least MEDIUM regardless of the learned score — their value is
           not captured by the headline the classifier sees. Belt-and-suspenders
           with #1 for the sec_edgar title-less case.
        """
        static_tier = routing_decision.routing_tier

        # INVARIANT 2 — never resurrect a statically-SUPPRESSED doc.
        if static_tier == RoutingTier.SUPPRESS:
            logger.info(  # type: ignore[no-any-return]
                "learned_router_live_suppress_preserved",
                doc_id=str(routing_decision.doc_id),
            )
            return  # leave final_routing_tier unset → suppression gate HALTs

        # INVARIANT 1 — title-less docs: the blind gate must NOT decide. Fall
        # back to the static tier (leave final_routing_tier unset).
        if not (doc_title or "").strip():
            logger.info(  # type: ignore[no-any-return]
                "learned_router_titleless_fallback",
                doc_id=str(routing_decision.doc_id),
                source_type=source_type,
                static_tier=static_tier.value,
                learned_tier=learned_tier.value,
            )
            return

        effective_tier = learned_tier

        # INVARIANT 3 — regulatory / authenticated-upload override forces >=MEDIUM.
        if effective_tier == RoutingTier.LIGHT and source_type in _AUTHORITATIVE_FILING_SOURCES:
            logger.info(  # type: ignore[no-any-return]
                "learned_router_live_regulatory_override",
                doc_id=str(routing_decision.doc_id),
                source_type=source_type,
                learned_tier=learned_tier.value,
            )
            effective_tier = RoutingTier.MEDIUM

        # The learned tier (post-overrides) now CONTROLS processing.
        routing_decision.final_routing_tier = effective_tier
        logger.info(  # type: ignore[no-any-return]
            "learned_router_live_control",
            doc_id=str(routing_decision.doc_id),
            static_tier=static_tier.value,
            effective_tier=effective_tier.value,
        )

    async def _run_pipeline(
        self,
        *,
        doc_id: uuid.UUID,
        minio_key: str,
        source_type: str,
        source_name: str | None = None,
        # PLAN-0056 Wave C2b: upstream market/source identity, threaded verbatim to
        # the enriched event (default None keeps existing direct-call unit tests green).
        external_id: str | None = None,
        published_at: datetime | None,
        extracted_at: datetime,
        is_backfill: bool,
        correlation_id: str | None,
        tenant_id: uuid.UUID | None = None,
        doc_title: str | None = None,
        # PLAN-0056 Wave C3: document title threaded verbatim onto the enriched
        # event's source_title (default None keeps existing direct-call unit tests green).
        source_title: str | None = None,
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
        if word_count < self._settings.min_word_count:  # type: ignore[attr-defined]
            logger.info(  # type: ignore[no-any-return]
                "article_consumer.stub_filtered",
                doc_id=str(doc_id),
                word_count=word_count,
                min_word_count=self._settings.min_word_count,  # type: ignore[attr-defined]
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
        # BP-718 (SEC-filings corpus-coverage gap): NER is NON-FATAL.
        # ROOT CAUSE — the article consumer persists chunk_text + chunk_embeddings
        # only at the very END of the pipeline (``persist_artifacts``), AFTER NER
        # (this block) and the LLM deep-extraction ML phase. A GLiNER outage
        # (``connection error`` / ``Server disconnected`` / ``Name or service not
        # known``) therefore aborted the WHOLE message → DLQ, so the document's
        # SEARCHABLE chunks + embeddings were never written — even though chat
        # retrieval does not need entity mentions at all. During the 2026-07-05 bulk
        # SEC backfill (2,265 filings) GLiNER was flaky and thousands of large
        # 10-Q/10-K filings were DLQ'd whole: content_store held them, but the chat
        # corpus (nlp_db chunks) never received them, so NVIDIA/Microsoft/Amazon
        # revenue could not be answered from the filings corpus (only Apple's one
        # 10-Q, ingested earlier when the pipeline was healthy, worked).
        #
        # FIX — treat a GLiNER failure as "zero mentions" rather than a hard error.
        # The Block-4 contract already guarantees "zero mentions NEVER suppresses a
        # document", so downstream routing/embedding/persist all tolerate an empty
        # mention list. The document still gets chunked + embedded + indexed and is
        # immediately answerable in chat; entity mentions can be backfilled later by
        # ``workers/backfill_entity_mentions.py`` once GLiNER recovers. This trades a
        # transient loss of KG enrichment for durable retrieval coverage — the right
        # tradeoff for a filings corpus whose primary value is its numeric text.
        try:
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
        except Exception:
            # GLiNER unavailable/slow — do NOT drop the document. Proceed with no
            # mentions so chunk_text + chunk_embeddings still persist and the filing
            # becomes searchable. Logged at WARNING (not raised) so the message is
            # NOT routed to the DLQ for a purely-enrichment failure.
            from nlp_pipeline.domain.models import DocumentEntityStats

            logger.warning(
                "article_consumer.ner_block_failed_nonfatal",
                doc_id=str(doc_id),
                source_type=source_type,
                exc_info=True,
            )
            mentions = []
            stats = DocumentEntityStats(doc_id=doc_id)
        for _i, m in enumerate(mentions):
            m.mention_id = uuid.UUID(uuid5_from_parts(str(doc_id), str(_i), m.mention_text.lower().strip()))
        # PLAN-0098 W2 T-W2-01 (BP-586): unconditional stamp.  ``tenant_id`` is
        # guaranteed non-None at this point (sentinel ``PUBLIC_TENANT_ID`` is
        # substituted for legacy/missing tenants in ``process_message``).  The
        # previous ``if tenant_id is not None`` guard was redundant; removing
        # it makes the intent obvious and prevents any future regression where
        # an upstream block constructs a mention with ``tenant_id=None``.
        #
        # PLAN-0099 W4 T-W4-02 (audit §13.6): defence-in-depth — even though
        # the envelope-level sentinel substitution earlier in
        # ``process_message`` guarantees ``tenant_id`` is non-None here, an
        # upstream refactor could silently break that precondition. Falling
        # back to ``PUBLIC_TENANT_ID`` at the stamp site preserves the
        # NOT-NULL invariant on ``entity_mentions.tenant_id`` (migration
        # 0020) without any reliance on the upstream guard. Cost: zero —
        # the substitution only fires in the regression case.
        _stamp_tenant = tenant_id or PUBLIC_TENANT_ID
        for m in mentions:
            m.tenant_id = _stamp_tenant
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

        # NOTE (PLAN-0111 #33): the learned-router SHADOW comparison USED to run
        # here (before chunking) but with no lede available, which fed the model
        # title-only input and caused train/serve skew. It now runs AFTER
        # run_embeddings_block so it can pass the real first-chunk lede as the
        # subtitle the model was trained on. The static router below still
        # controls processing; the shadow only needs to precede extraction.

        initial_path = apply_suppression_gate(routing_decision)
        # Backlog-drain lever (docs/audits/2026-07-17-article-backlog-lever.md):
        # gate genuinely low-value MEDIUM/DEEP docs OUT of the expensive deep-extraction
        # chain, dropping them to the LIGHT path (chunk embeddings only → still fully
        # searchable). Applied here so the embeddings block below ALSO skips the (unused)
        # section embeddings for gated docs; ml_phase re-applies it post-novelty as the
        # authoritative gate for entity resolution + deep extraction. Filings and any doc
        # scoring >= the floor are never gated.
        initial_path = apply_deep_extraction_value_gate(
            initial_path,
            routing_decision,
            source_type,
            enabled=self._settings.deep_extraction_value_gate_enabled,
            score_floor=self._settings.deep_extraction_score_floor,
            filing_sources=_AUTHORITATIVE_FILING_SOURCES,
        )

        # Block 7: Embeddings + denorm fields (PLAN-0063 W5-2)
        chunks, chunk_embs, section_embs, pending = await run_embeddings_block(
            sections=sections,
            embedding_client=self._emb,
            model_id=self._settings.embedding_model_id,
            instruction_prefix=self._settings.embedding_instruction_prefix,
            generate_chunk_embeddings=should_generate_chunk_embeddings(initial_path),
            # PLAN-0111 B-2: LIGHT no longer emits section embeddings (dead weight
            # once its chunks are embedded; chat only queries chunk granularity).
            generate_section_embeddings=should_generate_section_embeddings(initial_path),
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

        # ── PLAN-0111 C-6 / #33: learned-router SHADOW comparison ────────────
        # MOVED here (post-chunking) so the shadow router can be fed the SAME
        # lede the C-3 dataset trained on, closing the train/serve skew. The
        # static weighted-sum tier (computed above) still CONTROLS processing;
        # the shadow only attaches a *proposed* tier (+ p_yield + mode) onto the
        # routing_decision for persist_artifacts to write. Strictly observational
        # in shadow mode and wrapped so any failure is non-fatal to the article.
        #
        # LEDE SELECTION — must mirror the dataset SQL exactly:
        #   SELECT chunk_text FROM chunks
        #   WHERE doc_id=... AND chunk_text IS NOT NULL
        #   ORDER BY chunk_index LIMIT 1
        # The in-memory `chunks` returned by run_embeddings_block are domain
        # `Chunk` objects whose `.text` maps to the persisted `chunk_text` column
        # and whose `.chunk_index` maps to `chunk_index`. They are produced in
        # section order, so the first chunk with the minimum chunk_index AND
        # non-empty text is the same row the DB query would return (in the normal
        # single-leading-chunk case this is simply chunks[0]). We pick it with a
        # stable min() over (chunk_index) restricted to non-empty text so we
        # never accidentally hand the model an empty lede.
        _lede_chunks = [c for c in chunks if c.text and c.text.strip()]
        _lede = min(_lede_chunks, key=lambda c: c.chunk_index).text if _lede_chunks else None
        await self._run_learned_router_shadow(
            routing_decision=routing_decision,
            doc_title=doc_title,
            lede=_lede,
            source_type=source_type,
        )

        # ── PHASE 1 (BP-719 Mode B): persist the SEARCHABLE artefacts in their OWN
        # committed nlp_db transaction BEFORE the ML enrichment phase. ────────────
        # ROOT CAUSE — the pipeline used to write chunk_text + chunk_embeddings (the
        # artefacts chat's get_filings retrieves) only at the very END, inside the
        # same trailing transaction as Blocks 8-10. On a large 10-Q the per-chunk
        # deep-extraction (Block 10) blew past the 900s Kafka message watchdog; the
        # watchdog cancelled the WHOLE message → the transaction rolled back → the
        # chunks were NEVER written and the doc dead-lettered (~500+ DLQ rows,
        # ~3,150 content_store docs incl. NVIDIA/MSFT 10-Qs missing from nlp_db, so
        # chat could not answer their revenue).
        #
        # FIX — commit sections + chunks + embeddings first, in a standalone
        # transaction. Enrichment (Blocks 8-10 + entity_mentions) then runs
        # best-effort in the second transaction below; if it fails / times out /
        # dead-letters, the searchable doc SURVIVES and mentions are backfillable
        # (workers/backfill_entity_mentions.py). Skipped entirely when the doc
        # produced no sections/chunks (e.g. SUPPRESS/HALT with empty output) so a
        # no-op article does not open a needless transaction. Idempotent: chunk /
        # section / embedding writes all use ON CONFLICT DO NOTHING with
        # deterministic ids, so a redelivery of the same message never duplicates.
        if sections or chunks:
            async with self._nlp_sf() as searchable_s:
                chunks = await persist_searchable_artifacts(
                    nlp_session=searchable_s,
                    section_repo=SectionRepository(searchable_s),
                    chunk_repo=ChunkRepository(searchable_s),
                    doc_id=doc_id,
                    sections=sections,
                    chunks=chunks,
                    chunk_embs=chunk_embs,
                    section_embs=section_embs,
                    pending=pending,
                    gliner_mention_floor=self._settings.gliner_mention_floor,
                    settings=self._settings,
                    # Pre-resolution GLiNER mentions — the best entity metadata
                    # available before Block 9. persist_artifacts later refreshes the
                    # JSONB with the resolved mentions on the happy path.
                    ner_mentions=mentions,
                )
                await searchable_s.commit()

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
                source_type=source_type,
                published_at=published_at,
                extracted_at=extracted_at,
                settings=self._settings,
                emb=self._emb,
                ext=self._ext,
                watchlist_client=self._watchlist._client,  # type: ignore[attr-defined]
                usage_logger=self._usage_logger,
                entailment_client=self._entailment_client,
                entailment_config=self._entailment_config,
                evidence_grounding_config=self._evidence_grounding_config,
                claim_entailment_client=self._claim_entailment_client,
                claim_entailment_config=self._claim_entailment_config,
                _deep_extraction_fn=run_deep_extraction_block,
                # P0-A poison-pill fix (prod review 2026-07-15): thread the base
                # consumer's liveness heartbeat down into the sequential window
                # loop so each completed extraction window refreshes the progress
                # gauge. Without this, a single heavy article's many-window handler
                # never returns to the batch poll loop where _record_progress()
                # normally fires → seconds_since_progress crosses stale_after_s →
                # /healthz 503 → kubelet SIGTERM → same article reprocessed →
                # CrashLoopBackOff. A genuinely hung window still trips the probe
                # (no window completes) — only slow-but-progressing docs survive.
                on_window_done=self._record_progress,
                _alias_repo=entity_alias_repo,
                _profile_emb_repo=entity_profile_emb_repo,
                _canonical_repo=canonical_entity_repo,
                _mention_resolution_repo=mention_resolution_repo,
            )
            # ── Pre-persist tenant_id safety net (PLAN-0098 W2 T-W2-01) ──
            # Defence-in-depth against any current or future code path that
            # constructs an ``EntityMention`` without propagating ``tenant_id``
            # (e.g. entity resolution, deep extraction, novelty backfill).  The
            # ``entity_mentions.tenant_id`` column is ``NOT NULL`` (migration
            # 0020); a single mention with ``tenant_id=None`` fails the INSERT,
            # the exception is treated as retryable, and the topic stalls
            # forever (BP-575/BP-586).  We substitute ``PUBLIC_TENANT_ID`` so
            # the row writes cleanly and emit a WARN with the mention metadata
            # so a forensic analyst can identify the offending upstream block.
            _missing_mentions = [m for m in ml.final_mentions if m.tenant_id is None]
            _missing_tenant: list[uuid.UUID] = [m.mention_id for m in _missing_mentions]
            if _missing_tenant:
                logger.warning(  # type: ignore[no-any-return]
                    "article_consumer.pre_persist_tenant_id_substituted",
                    doc_id=str(doc_id),
                    missing_count=len(_missing_tenant),
                    total_mentions=len(ml.final_mentions),
                    sample_mention_ids=[str(mid) for mid in _missing_tenant[:5]],
                    sentinel=str(PUBLIC_TENANT_ID),
                    fallback_tenant_id=str(tenant_id) if tenant_id is not None else str(PUBLIC_TENANT_ID),
                )
                # PLAN-0099 W2 T-W2-04: attribute each substitution to the
                # upstream block that produced the offending mention so
                # operators can query Prometheus and identify the dominant
                # source of null tenant_ids (feeds PLAN-0100 §13.4 root-cause).
                # Cardinality is bounded by the fixed enum in
                # ``metrics.prometheus.PRE_PERSIST_BLOCK_SOURCES``.
                for _m in _missing_mentions:
                    record_pre_persist_tenant_substituted(_infer_block_source(_m))
                _fallback_tenant = tenant_id if tenant_id is not None else PUBLIC_TENANT_ID
                for m in ml.final_mentions:
                    if m.tenant_id is None:
                        m.tenant_id = _fallback_tenant

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
                    external_id=external_id,
                    # PLAN-0056 Wave C3: carry the document title (market question
                    # for Polymarket synthetic docs) onto the enriched event.
                    source_title=source_title,
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
                    # BUG-3 / BP-698: wire the canonical-alias repo + open intel
                    # session so _enqueue_enriched runs endpoint recovery (M1
                    # canonical fall-back + M2 provisional mint) before the
                    # _build_raw_* helpers drop non-mention endpoints. Both are
                    # already constructed above for the ML phase; reusing the
                    # SAME open intel_s keeps the provisional mints inside the
                    # D-004 dual-DB transaction (they commit atomically with the
                    # enriched event via the intel_s.commit() below).
                    alias_repo=entity_alias_repo,
                    intelligence_session=intel_s,
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
        """Persist a dead-letter row with the ORIGINAL payload; RAISE on write failure.

        Two correctness properties:

        * RE-INGESTABLE PAYLOAD — persist ``failure.raw_payload`` (the original
          ``content.article.stored.v1`` message bytes) as ``payload_avro`` so a
          dead-lettered article can be replayed later.  Previously only the
          ``event_id`` bytes were stored, so DLQ rows were NOT recoverable.  Fall
          back to the event_id bytes only when raw_payload is absent.
        * NO SILENT SWALLOW — a DLQ-write failure RE-RAISES so the caller
          (``_dead_letter_poison``) learns the message was NOT durably stored and
          holds the offset for retry instead of advancing past a lost article.
        """
        logger.error("article_consumer_dead_lettered", event_id=failure.event_id, error=str(failure.last_error))  # type: ignore[no-any-return]
        event_uuid = uuid.UUID(failure.event_id) if _is_valid_uuid(failure.event_id) else common.ids.new_uuid7()
        # Persist the real message bytes so the row can be re-ingested; only fall
        # back to a diagnostic event_id blob when the original payload is missing.
        payload_bytes = failure.raw_payload if failure.raw_payload else failure.event_id.encode("utf-8")
        async with self._nlp_sf() as session:
            await DLQRepository(session).move_to_dlq(
                original_event_id=event_uuid,
                topic=failure.topic or _TOPIC,
                payload_avro=payload_bytes,
                error_detail=str(failure.last_error)[:1024],
            )
            await session.commit()

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
