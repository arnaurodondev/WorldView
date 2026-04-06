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
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Minimal no-op UoW — the consumer manages its own session in process_message
# ---------------------------------------------------------------------------


class _NoOpUoW:
    """Minimal UoW satisfying BaseKafkaConsumer's context manager contract."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
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

        raw_relations_data: list[dict[str, Any]] = value.get("raw_relations", [])
        raw_events_data: list[dict[str, Any]] = value.get("raw_events", [])
        raw_claims_data: list[dict[str, Any]] = value.get("raw_claims", [])

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
                direct_producer=self._direct_producer,
                entity_dirtied_topic=self._entity_dirtied_topic,
                correlation_id=correlation_id,
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
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "enriched_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
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
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
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
                    polarity=d.get("polarity", "positive"),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    source_trust_weight=float(d.get("source_trust_weight", 1.0)),
                    evidence_date=_parse_dt(d.get("evidence_date")),
                    is_backfill=bool(d.get("is_backfill", False)),
                    entity_provisional=bool(d.get("entity_provisional", False)),
                    provisional_queue_id=(UUID(d["provisional_queue_id"]) if d.get("provisional_queue_id") else None),
                    claim_id=UUID(d["claim_id"]) if d.get("claim_id") else None,
                    chunk_id=UUID(d["chunk_id"]) if d.get("chunk_id") else None,
                    evidence_text=d.get("evidence_text"),
                )
            )
        except (KeyError, ValueError):
            logger.warning("enriched_consumer_bad_relation", data=str(d)[:200])  # type: ignore[no-any-return]
    return results


def _parse_raw_events(data: list[dict[str, Any]]) -> list[RawEvent]:
    results: list[RawEvent] = []
    for d in data:
        try:
            results.append(
                RawEvent(
                    subject_entity_id=UUID(d["subject_entity_id"]),
                    event_type=d["event_type"],
                    event_text=d.get("event_text", ""),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    event_date=_parse_dt(d.get("event_date")),
                    participant_entity_ids=tuple(UUID(eid) for eid in d.get("participant_entity_ids", [])),
                )
            )
        except (KeyError, ValueError):
            logger.warning("enriched_consumer_bad_event", data=str(d)[:200])  # type: ignore[no-any-return]
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
                    polarity=d.get("polarity", "neutral"),
                    claim_text=d.get("claim_text", ""),
                    extraction_confidence=float(d.get("extraction_confidence", 0.5)),
                    claimer_entity_id=(UUID(d["claimer_entity_id"]) if d.get("claimer_entity_id") else None),
                    chunk_id=UUID(d["chunk_id"]) if d.get("chunk_id") else None,
                    is_backfill=is_backfill,
                )
            )
        except (KeyError, ValueError):
            logger.warning("enriched_consumer_bad_claim", data=str(d)[:200])  # type: ignore[no-any-return]
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
