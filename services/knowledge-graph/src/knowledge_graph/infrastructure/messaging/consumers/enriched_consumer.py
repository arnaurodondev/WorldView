"""Enriched article consumer — orchestrates hot-path Blocks 11 → 12a → 12b.

Consumes ``nlp.article.enriched.v1`` from S6 NLP Pipeline.

Message format (JSON):
  Required: event_id, doc_id, resolved_entity_ids, is_backfill
  Optional: raw_relations (list of relation dicts), raw_events (list),
            raw_claims (list).  S6 currently omits these arrays; the
            consumer handles their absence gracefully (empty lists).

Processing pipeline:
  1. Parse raw_relations from message payload.
  2. Block 11: Canonicalize each relation type.
  3. Block 12a: Materialize graph (advisory lock, evidence, events, claims).
  4. Block 12b: Detect contradictions for each inserted claim.
  5. Commit intelligence_db transaction.
  6. Mark event as processed (Valkey dedup).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from contracts.events.nlp.article_enriched import decode_raw_array  # type: ignore[import-untyped]
from knowledge_graph.application.blocks.canonicalization import (
    CanonicalizationResult,
    EmbeddingClientProtocol,
    canonicalize_relation_type,
)
from knowledge_graph.application.blocks.graph_write import (
    DirectKafkaProducerProtocol,
    RawClaim,
    RawEvent,
    RawRelation,
    _build_entity_dirtied_payload,
    materialize_graph,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
    OutboxRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
    RelationRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
    RelationEvidenceRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_type_registry import (
    RelationTypeRegistryRepository,
)
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


_ARTICLE_ENRICHED_TOPIC = "nlp.article.enriched.v1"
_ARTICLE_ENRICHED_SCHEMA_PATH = get_schema_path("nlp.article.enriched.v1.avsc")

# PLAN-0062 F-018: defence-in-depth bound on the unbounded ``json.loads`` read.
# Mirrors libs/contracts decode_raw_array's _MAX_RAW_ARRAY_BYTES — caps the
# JSON-fallback path at 16 MiB so a poisoned legacy producer cannot OOM the
# consumer.  Avro path is already bounded by the schema; this only covers the
# ``raw[:1] != b"\x00"`` JSON branch.
_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024

# PLAN-0062 F-019: cap free-text fields and constrain polarity values.
# The Avro schema permits arbitrarily long strings; this hard cap protects
# downstream Postgres TEXT columns and Cypher queries from pathological
# inputs.  Polarity values outside the allow-list collapse to ``"neutral"``
# with a structured warning so the upstream extractor's mistake is visible.
_MAX_TEXT_FIELD_LEN = 8192  # 8 KiB hard cap
_VALID_POLARITIES = frozenset({"positive", "negative", "neutral"})


def _truncate_text_field(value: Any, *, field_name: str) -> Any:
    """Truncate string values exceeding _MAX_TEXT_FIELD_LEN; emit a warning on truncation."""
    if isinstance(value, str) and len(value) > _MAX_TEXT_FIELD_LEN:
        logger.warning(  # type: ignore[no-any-return]
            "enriched_consumer_text_field_truncated",
            field_name=field_name,
            original_len=len(value),
            cap=_MAX_TEXT_FIELD_LEN,
        )
        return value[:_MAX_TEXT_FIELD_LEN]
    return value


def _normalize_polarity(value: Any, *, default: str) -> str:
    """Coerce unknown polarity values to ``"neutral"`` with a warning; ``None`` falls back to *default*."""
    if value is None:
        return default
    if value in _VALID_POLARITIES:
        return str(value)
    logger.warning(  # type: ignore[no-any-return]
        "enriched_consumer_polarity_normalized",
        invalid_value=str(value)[:64],
    )
    return "neutral"


# ---------------------------------------------------------------------------
# Minimal no-op UoW — the consumer manages its own session in process_message
# ---------------------------------------------------------------------------


class _NoOpUoW:
    """Minimal UoW satisfying BaseKafkaConsumer's context manager contract."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class EnrichedArticleConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    # DP-005 fix: class-level constant so key prefix is stable across config changes.
    _dedup_prefix: str = "kg:dedup:enriched_article_consumer"

    """Consumes ``nlp.article.enriched.v1`` and materializes the knowledge graph.

    Args:
    ----
        config: Consumer configuration.
        session_factory: async_sessionmaker for intelligence_db.
        embedding_client: Client satisfying EmbeddingClientProtocol.
        direct_producer: Client satisfying DirectKafkaProducerProtocol.
        entity_dirtied_topic: Kafka topic name for entity.dirtied.v1.
        canonicalization_threshold: ANN distance threshold (default 0.35).
        dedup_client: Optional dedup client (Valkey); if None, dedup is skipped.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_client: EmbeddingClientProtocol,
        direct_producer: DirectKafkaProducerProtocol,
        entity_dirtied_topic: str,
        *,
        canonicalization_threshold: float = 0.35,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._embedding_client = embedding_client
        self._direct_producer = direct_producer
        self._entity_dirtied_topic = entity_dirtied_topic
        self._canon_threshold = canonicalization_threshold
        self._dedup_client = dedup_client

    # ------------------------------------------------------------------
    # Resilient message handling
    # ------------------------------------------------------------------

    async def _handle_message(self, msg: Any) -> None:
        """Deserialize + dispatch one message, SKIPPING un-decodable records.

        Prod-readiness fix (BP-720): commit ``66b0b6416`` appended nullable
        ``external_id``/``source_title`` to ``nlp.article.enriched.v1.avsc``. The
        platform decodes with ``fastavro.schemaless_reader`` (positional, NO schema
        registry, writer==reader assumed), so every pre-2026-07-09 backlog record —
        written WITHOUT the trailing fields — under-runs the new reader schema and
        raises ``EOFError`` inside ``deserialize_confluent_avro``. The base
        ``_handle_message`` wraps that (and any other decode/struct error) into
        ``MalformedDataError`` (a ``FatalError``), which dead-letters INLINE; a run of
        ~10.7k old-schema records trips ``dead_letter_cap`` (5000) → the consumer is
        force-restarted BEFORE committing → it re-reads the same 5000 forever and can
        NEVER reach today's new-schema NEWS messages at the tail. news→KG enrichment
        halts 100%.

        Unlike the forward-only PredictionEnrichedConsumer, this consumer must NOT
        start-at-latest — it still has un-processed NEW-schema NEWS backlog to reach.
        The correct behaviour is to SKIP only the un-decodable OLD records while
        processing the good ones: catch the deserialize failure BROADLY (the
        base-wrapped ``MalformedDataError`` plus raw ``EOFError``/``struct.error`` as
        defence-in-depth for any path that surfaces the decode error un-wrapped), log
        it WITH topic/partition/offset, and return normally. The run loop then commits
        the offset and advances past the poison record. Crucially, ``dead_letter`` is
        never called on a skip, so the ``dead_letter_cap`` crash-loop can never trip on
        old-schema records. All OTHER exceptions (genuine processing/DB failures)
        propagate unchanged into the retry/dead-letter path.
        """
        import struct

        try:
            await super()._handle_message(msg)
        except (MalformedDataError, EOFError, struct.error) as exc:
            # Un-decodable record (old-schema/poison). Skip + advance the offset.
            # The ``nlp.article.enriched.v1.dlq`` topic exists but this consumer's
            # ``_dead_letter_impl`` is log-only, so a structured skip log IS the
            # observability signal (dead-letter emission would re-arm the cap crash).
            logger.warning(
                "enriched_consumer_deserialize_skipped",
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Orchestrate Blocks 11 → 12a → 12b for one enriched article."""
        doc_id = UUID(value["doc_id"])
        is_backfill: bool = value.get("is_backfill", False)
        correlation_id: str | None = value.get("correlation_id")
        # PLAN-0031 B-2: extraction_model_id from S6 enriched event payload
        extraction_model_id: str | None = value.get("extraction_model_id")

        # PLAN-0062 Wave B: Avro envelope transports raw arrays as JSON strings
        # (raw_relations_json/raw_events_json/raw_claims_json).  Legacy JSON
        # producers used direct list fields (raw_relations / raw_events /
        # raw_claims) — fall back to those when the new fields are absent so
        # in-flight legacy messages still materialise correctly.
        raw_relations_data: list[dict[str, Any]] = (
            decode_raw_array(value.get("raw_relations_json"))
            if value.get("raw_relations_json") is not None
            else value.get("raw_relations", [])
        )
        raw_events_data: list[dict[str, Any]] = (
            decode_raw_array(value.get("raw_events_json"))
            if value.get("raw_events_json") is not None
            else value.get("raw_events", [])
        )
        raw_claims_data: list[dict[str, Any]] = (
            decode_raw_array(value.get("raw_claims_json"))
            if value.get("raw_claims_json") is not None
            else value.get("raw_claims", [])
        )

        # Parse incoming relation dicts into typed objects
        raw_relations = _parse_raw_relations(raw_relations_data)
        raw_events = _parse_raw_events(raw_events_data)
        raw_claims = _parse_raw_claims(raw_claims_data, is_backfill=is_backfill)

        # Data quality signal: track how many incoming relations lack evidence_text.
        # This indicates NLP pipeline extraction gaps that will cause downstream
        # SummaryWorker to fall back to raw tables or skip the relation entirely.
        if raw_relations:
            null_evidence_count = sum(1 for r in raw_relations if not r.evidence_text)
            if null_evidence_count > 0:
                logger.warning(  # type: ignore[no-any-return]
                    "enriched_consumer_null_evidence_text",
                    doc_id=str(doc_id),
                    null_evidence_count=null_evidence_count,
                    total_relations=len(raw_relations),
                    message="incoming relations missing evidence_text — NLP extraction gap",
                )

        # D-INIT-6 (2026-05-09): resolve source_name + source_type for evidence
        # row provenance directly from the event payload.
        #
        # The previous T-B-03 implementation fell back to a query against
        # ``document_source_metadata`` whenever ``source_name`` was None — but
        # that table lives in ``nlp_db`` while this consumer runs on
        # ``intelligence_db``. Every fallback hit asyncpg ``UndefinedTableError``
        # and silently dropped provenance, leaving the intelligence layer
        # generating zero narratives. The producer side now emits
        # ``source_name`` in the Avro envelope (see PLAN-0087 D-INIT-6 fix).
        #
        # When source_name is None we log once and continue with NULL provenance
        # — downstream evidence-row writes already accept None for these columns.
        # We do NOT re-query nlp_db (R7 cross-service-DB violation).
        source_name: str | None = value.get("source_name")
        source_type_str: str | None = value.get("source_type")

        if source_name is None:
            logger.warning(  # type: ignore[no-any-return]
                "evidence_source_metadata_missing",
                doc_id=str(doc_id),
                source_type=source_type_str,
                message=(
                    "enriched event payload has no source_name; evidence rows for this doc will have NULL source_name"
                ),
            )

        async with self._sf() as session:
            registry_repo = RelationTypeRegistryRepository(session)
            outbox_repo = OutboxRepository(session)
            relation_repo = RelationRepository(session)
            evidence_repo = RelationEvidenceRepository(session)
            # 2026-06-11 relations-FK-crash fix: entity-existence gate needs the
            # canonical-entity repo so materialize_graph can defer (not crash on)
            # relations whose subject/object entity has not yet landed.
            entity_repo = CanonicalEntityRepository(session)

            # ----------------------------------------------------------
            # Block 11: Canonicalize all relation types
            # ----------------------------------------------------------
            canon_results: list[CanonicalizationResult] = []
            for rel in raw_relations:
                result = await canonicalize_relation_type(
                    raw_type=rel.raw_type,
                    semantic_mode_hint="RELATION_STATE",
                    subject_entity_id=rel.subject_entity_id,
                    object_entity_id=rel.object_entity_id,
                    source_doc_id=doc_id,
                    registry_repo=registry_repo,  # type: ignore[arg-type]
                    outbox_repo=outbox_repo,  # type: ignore[arg-type]
                    embedding_client=self._embedding_client,
                    distance_threshold=self._canon_threshold,
                    correlation_id=correlation_id,
                )
                canon_results.append(result)

            canonical_types = [r.canonical_type for r in canon_results]
            canonical_semantic_modes = [r.semantic_mode for r in canon_results]
            canonical_decay_classes = [r.decay_class for r in canon_results]
            canonical_decay_alphas = [r.decay_alpha for r in canon_results]
            canonical_base_confidences = [r.base_confidence for r in canon_results]

            # Log canonicalization quality: how many raw_types resolved vs stayed unknown.
            if canon_results:
                resolved_count = sum(1 for ct in canonical_types if ct is not None)
                unknown_count = len(canonical_types) - resolved_count
                logger.debug(  # type: ignore[no-any-return]
                    "enriched_consumer_canonicalization_summary",
                    doc_id=str(doc_id),
                    total_relations=len(canon_results),
                    resolved=resolved_count,
                    unknown=unknown_count,
                )
                if unknown_count > 0:
                    unknown_raw_types = [
                        r.raw_type for r, ct in zip(raw_relations, canonical_types, strict=True) if ct is None
                    ]
                    logger.warning(  # type: ignore[no-any-return]
                        "enriched_consumer_unresolved_relation_types",
                        doc_id=str(doc_id),
                        unknown_count=unknown_count,
                        unknown_raw_types=unknown_raw_types[:10],  # cap to avoid log bloat
                    )

            # ----------------------------------------------------------
            # Block 12a: Graph materialization
            # ----------------------------------------------------------
            summary = await materialize_graph(
                doc_id=doc_id,
                source_type=value.get("source_type", "unknown"),
                is_backfill=is_backfill,
                relations=raw_relations,
                canonical_types=canonical_types,
                canonical_semantic_modes=canonical_semantic_modes,
                canonical_decay_classes=canonical_decay_classes,
                canonical_decay_alphas=canonical_decay_alphas,
                canonical_base_confidences=canonical_base_confidences,
                events=raw_events,
                claims=raw_claims,
                session=session,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                outbox_repo=outbox_repo,
                correlation_id=correlation_id,
                extraction_model_id=extraction_model_id,
                # T-B-03: propagate resolved source metadata into evidence rows.
                source_name=source_name,
                source_type_metadata=source_type_str,
                # 2026-06-11: entity-existence gate (prevents relations FK crash).
                entity_repo=entity_repo,
            )

            # ----------------------------------------------------------
            # Block 12b: Contradiction detection for each new claim
            # ----------------------------------------------------------
            # F-006: detect_and_record_contradictions requires real claim_id from materialize_graph
            # which does not yet return per-claim IDs. Contradiction detection is deferred to
            # ContradictionBatchWorker which processes evidence in batch with correct IDs.
            # See QA-2026-05-04 F-006 for the full fix plan.
            for raw_claim in raw_claims:
                if raw_claim.polarity == "neutral":
                    continue
                logger.debug(  # type: ignore[no-any-return]
                    "hot_path_contradiction_detection_deferred",
                    subject_entity_id=str(raw_claim.subject_entity_id),
                    message="Contradiction detection deferred to batch worker — hot path lacks real claim_id",
                )

            await session.commit()

        # ----------------------------------------------------------
        # PLAN-0031 C-1: Produce entity.dirtied.v1 AFTER session.commit()
        # so that Kafka messages are never emitted for rolled-back writes.
        # On rare Kafka unavailability the dirty signal is lost — acceptable
        # because the compacted topic is superseded by the next write for
        # the same entity_id.
        # ----------------------------------------------------------
        for entity_id in summary.entity_ids_to_dirty:
            try:
                payload_bytes = _build_entity_dirtied_payload(
                    entity_id,
                    doc_id,
                    correlation_id,
                )
                self._direct_producer.produce_bytes(
                    topic=self._entity_dirtied_topic,
                    key=str(entity_id).encode(),
                    value=payload_bytes,
                )
            except Exception:
                logger.warning(
                    "entity_dirtied_produce_failed",
                    entity_id=str(entity_id),
                    doc_id=str(doc_id),
                    exc_info=True,
                )

        logger.info(  # type: ignore[no-any-return]
            "enriched_article_processed",
            doc_id=str(doc_id),
            relations=summary.relations_upserted,
            evidence=summary.evidence_rows_inserted,
            events=summary.events_inserted,
            claims=summary.claims_inserted,
            entities_dirtied=summary.entities_dirtied,
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "enriched_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ------------------------------------------------------------------
    # Failure tracking (log-only for Wave D-2)
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "enriched_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "enriched_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "enriched_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ------------------------------------------------------------------
    # UoW (no-op — process_message manages its own session)
    # ------------------------------------------------------------------

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode nlp.article.enriched.v1 events.

        PLAN-0062 Wave B: Confluent-Avro on the wire (5-byte magic header +
        Avro body), with JSON fallback for legacy messages produced before
        the cutover.  The fallback path emits a warning so we can quantify
        residual JSON traffic and remove the branch once it decays to zero.
        """
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _ARTICLE_ENRICHED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00":
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        logger.warning(  # type: ignore[no-any-return]
            "enriched_consumer_legacy_json_payload",
            message="nlp.article.enriched.v1 message lacks Confluent magic byte; using JSON fallback",
        )
        # PLAN-0062 F-018: cap the JSON-fallback branch to defend against
        # an oversized poison message before ``json.loads`` allocates the
        # entire payload as a Python object graph.
        from messaging.kafka.consumer.errors import (  # type: ignore[import-untyped]
            MalformedDataError,
        )

        if len(raw) > _MAX_JSON_FALLBACK_BYTES:
            raise MalformedDataError(
                f"JSON fallback payload exceeds cap ({len(raw)} > {_MAX_JSON_FALLBACK_BYTES})",
            )
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _ARTICLE_ENRICHED_TOPIC:
            return _ARTICLE_ENRICHED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_raw_relations(data: list[dict[str, Any]]) -> list[RawRelation]:
    results: list[RawRelation] = []
    for d in data:
        try:
            results.append(
                RawRelation(
                    subject_entity_id=UUID(d["subject_entity_id"]),
                    object_entity_id=UUID(d["object_entity_id"]),
                    raw_type=d["raw_type"],
                    # PLAN-0062 F-019: collapse out-of-vocabulary polarities.
                    polarity=_normalize_polarity(d.get("polarity"), default="positive"),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    source_trust_weight=float(d.get("source_trust_weight", 1.0)),
                    evidence_date=_parse_dt(d.get("evidence_date")),
                    is_backfill=bool(d.get("is_backfill", False)),
                    entity_provisional=bool(d.get("entity_provisional", False)),
                    provisional_queue_id=(UUID(d["provisional_queue_id"]) if d.get("provisional_queue_id") else None),
                    claim_id=UUID(d["claim_id"]) if d.get("claim_id") else None,
                    chunk_id=UUID(d["chunk_id"]) if d.get("chunk_id") else None,
                    # PLAN-0062 F-019: cap pathological evidence text length.
                    evidence_text=_truncate_text_field(d.get("evidence_text"), field_name="evidence_text"),
                    # PLAN-0109 W5: per-fact end-of-validity date (None when not stated).
                    valid_to=_parse_dt_optional(d.get("valid_to")),
                ),
            )
        # PLAN-0062 F-021: split into typed handlers — drop the ``data=`` echo
        # that could leak PII / oversized payloads into log aggregation.
        except KeyError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_relation_missing_field",
                missing=str(exc).strip("'\""),
            )
        except ValueError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_relation_value_error",
                error_class=type(exc).__name__,
            )
    return results


def _parse_raw_events(data: list[dict[str, Any]]) -> list[RawEvent]:
    results: list[RawEvent] = []
    for d in data:
        try:
            results.append(
                RawEvent(
                    subject_entity_id=UUID(d["subject_entity_id"]),
                    event_type=d["event_type"],
                    # PLAN-0062 F-019: cap pathological event text length.
                    event_text=_truncate_text_field(d.get("event_text", ""), field_name="event_text"),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    event_date=_parse_dt(d.get("event_date")),
                    participant_entity_ids=tuple(UUID(eid) for eid in d.get("participant_entity_ids", [])),
                ),
            )
        except KeyError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_event_missing_field",
                missing=str(exc).strip("'\""),
            )
        except ValueError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_event_value_error",
                error_class=type(exc).__name__,
            )
    return results


def _parse_raw_claims(
    data: list[dict[str, Any]],
    *,
    is_backfill: bool,
) -> list[RawClaim]:
    results: list[RawClaim] = []
    for d in data:
        try:
            results.append(
                RawClaim(
                    subject_entity_id=UUID(d["subject_entity_id"]),
                    claim_type=d["claim_type"],
                    # PLAN-0062 F-019: collapse out-of-vocabulary polarities.
                    polarity=_normalize_polarity(d.get("polarity"), default="neutral"),
                    # PLAN-0062 F-019: cap pathological claim text length.
                    claim_text=_truncate_text_field(d.get("claim_text", ""), field_name="claim_text"),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    claimer_entity_id=(UUID(d["claimer_entity_id"]) if d.get("claimer_entity_id") else None),
                    chunk_id=UUID(d["chunk_id"]) if d.get("chunk_id") else None,
                    is_backfill=is_backfill,
                ),
            )
        except KeyError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_claim_missing_field",
                missing=str(exc).strip("'\""),
            )
        except ValueError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer_bad_claim_value_error",
                error_class=type(exc).__name__,
            )
    return results


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO datetime string or return UTC now as fallback."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def _parse_dt_optional(value: Any) -> datetime | None:
    """Parse an ISO date/datetime string → tz-aware datetime, or ``None``.

    PLAN-0109 W5: unlike :func:`_parse_dt`, returns ``None`` (NOT now) when the
    value is absent or unparseable — used for ``valid_to``, where absence means
    "no known end" and must never be coerced to the current time (which would
    expire the fact immediately under bitemporal step-decay).
    """
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).replace(tzinfo=UTC)
        except ValueError:
            return None
    return None
