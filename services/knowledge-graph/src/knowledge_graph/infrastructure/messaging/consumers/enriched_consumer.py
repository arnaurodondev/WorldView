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

from knowledge_graph.application.blocks.canonicalization import (
    CanonicalizationResult,
    EmbeddingClientProtocol,
    canonicalize_relation_type,
)
from knowledge_graph.application.blocks.contradiction import (
    detect_and_record_contradictions,
)
from knowledge_graph.application.blocks.graph_write import (
    DirectKafkaProducerProtocol,
    RawClaim,
    RawEvent,
    RawRelation,
    _build_entity_dirtied_payload,
    materialize_graph,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
    ContradictionRepository,
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


class EnrichedArticleConsumer(BaseKafkaConsumer[None]):
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
        self._dedup_prefix = f"kg:dedup:{config.group_id}"

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
        from contracts.events.nlp.article_enriched import decode_raw_array  # type: ignore[import-untyped]

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

        async with self._sf() as session:
            registry_repo = RelationTypeRegistryRepository(session)
            outbox_repo = OutboxRepository(session)
            relation_repo = RelationRepository(session)
            evidence_repo = RelationEvidenceRepository(session)
            contradiction_repo = ContradictionRepository(session)

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
            )

            # ----------------------------------------------------------
            # Block 12b: Contradiction detection for each new claim
            # ----------------------------------------------------------
            # Detect against claims materialized in this batch
            for raw_claim in raw_claims:
                if raw_claim.polarity == "neutral":
                    continue
                # Use a placeholder claim_id and raw_evidence_id (in
                # production these come from the materialize_graph return)
                await detect_and_record_contradictions(
                    raw_evidence_id=_sentinel_uuid(),
                    claim_id=_sentinel_uuid(),
                    subject_entity_id=raw_claim.subject_entity_id,
                    claim_type=raw_claim.claim_type,
                    polarity=raw_claim.polarity,
                    new_claim_confidence=raw_claim.extraction_confidence,
                    is_backfill=raw_claim.is_backfill,
                    contradiction_repo=contradiction_repo,  # type: ignore[arg-type]
                    outbox_repo=outbox_repo,  # type: ignore[arg-type]
                    correlation_id=correlation_id,
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
    # Idempotency (Valkey-based with fallback no-op)
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            return bool(await self._dedup_client.exists(key))
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer.valkey_check_failed",
                event_id=event_id,
                exc_info=True,
            )
            return False  # prefer at-least-once over skipping

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=86400)  # 24h TTL
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "enriched_consumer.valkey_mark_failed",
                event_id=event_id,
                exc_info=True,
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


def _sentinel_uuid() -> UUID:
    """Return a new UUIDv7 as a sentinel for claim/evidence IDs in contradiction detection."""
    from common.ids import new_uuid7  # type: ignore[import-untyped]

    return new_uuid7()  # type: ignore[return-value]
