"""PredictionEnrichedConsumer — turn Polymarket synthetic docs into temporal events.

Consumer group: ``kg-prediction-enriched-group`` (own group — sees the same
``nlp.article.enriched.v1`` topic independently of ``EnrichedArticleConsumer``).

PLAN-0056 Wave C2 (PRD-0033). THE KEYSTONE entity↔market linkage that Sub-Plan D
signals and the Wave C4 entity-predictions API depend on.

Pipeline (per enriched doc where ``source_type == 'polymarket'``):
  1. Filter: only ``source_type == ContentSourceType.POLYMARKET`` ("polymarket")
     is processed. Every other enriched doc (eodhd news, filings, …) is skipped
     silently — this consumer shares the topic with EnrichedArticleConsumer.
  2. Upsert ONE ``temporal_events`` row (event_type='prediction', scope=LOCAL).
  3. Upsert ONE ``entity_event_exposures`` row per resolved entity id
     (exposure_type='directly_affected', polarity NULL for now — the Wave C3
     classifier fills it in later).
  4. Commit (R26 — the consumer OWNS the commit; a prior KG bug shipped
     HTTP200-but-rollback writes, so the explicit ``session.commit()`` is load-bearing).

Idempotency (BP-034/035):
  - Valkey dedup on ``event_id`` (ValkeyDedupMixin) skips exact re-deliveries.
  - Natural-key upsert ``(event_type, region, title, active_from::day)`` makes the
    temporal-event write idempotent even without Valkey; the exposure upsert is
    ``ON CONFLICT (event_id, entity_id, exposure_type) DO NOTHING``.

WHY doc_id in the title, region='prediction':
  The ``nlp.article.enriched.v1`` event carries NO title, NO source_url and NO
  condition_id (verified against the S6 producer + Avro schema — it only carries
  doc_id, source_type, resolved_entity_ids, published_at, occurred_at). So the
  question text and Polymarket condition_id are NOT recoverable here without an
  R7 cross-service DB read of nlp_db (forbidden). ``doc_id`` is the only stable,
  per-market identifier available (Wave B2 emits one synthetic doc per market),
  so it anchors the natural key: region is the constant category ``'prediction'``
  and the title is ``f"Prediction market {doc_id}"`` — unique per market doc and
  stable across re-delivery. Wave C4's read API surfaces these rows; a later wave
  can enrich the title/region if S6 starts carrying the question through.

R9: writes only to its own DB (intelligence_db) + reads Kafka. R10/R11 via
``new_uuid7`` / ``utc_now``. structlog only.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

import common.time as ct  # type: ignore[import-untyped]
from common.ids import new_uuid7  # type: ignore[import-untyped]
from contracts.enums import ContentSourceType  # type: ignore[import-untyped]
from knowledge_graph.domain.enums import EventScope, EventType, ExposureType
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


_ARTICLE_ENRICHED_TOPIC = "nlp.article.enriched.v1"
_ARTICLE_ENRICHED_SCHEMA_PATH = get_schema_path("nlp.article.enriched.v1.avsc")

# The exact source_type value Wave B2 stamps on the synthetic document
# (ContentSourceType.POLYMARKET == "polymarket"). S6 passes source_type through
# verbatim onto the enriched event, so this is the value we filter on. NOTE: the
# plan prose says 'prediction_market' but that value is never emitted — B2 uses
# ContentSourceType.POLYMARKET. Using the enum keeps input and lookup aligned
# (prompt-input-vs-lookup-mismatch guardrail).
_POLYMARKET_SOURCE_TYPE = ContentSourceType.POLYMARKET.value

# Category tag stored in temporal_events.region. condition_id is NOT recoverable
# from the enriched event (see module docstring), so region is this constant.
_PREDICTION_REGION = "prediction"

# Prediction markets influence linked entities for a bounded window after the
# market resolves/moves; 30 days mirrors the TEMPORAL decay half-life default.
_RESIDUAL_IMPACT_DAYS = 30

# Default confidence for a prediction temporal event. The enriched event carries
# no implied-probability, so we use a neutral prior; the Wave C3 classifier adds
# per-entity polarity confidence on the exposure rows.
_DEFAULT_EVENT_CONFIDENCE = 0.5

# Default confidence for each entity↔market exposure link.
_DEFAULT_EXPOSURE_CONFIDENCE = 0.5


def _parse_iso_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string to a UTC-aware datetime, or None when absent/bad."""
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        # Normalise to UTC-aware (published_at/occurred_at are already UTC ISO).
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ct.utc_now().tzinfo)
        return dt
    return None


class _NoOpUoW:
    """Minimal UoW satisfying BaseKafkaConsumer's context-manager contract.

    The consumer manages its own AsyncSession inside process_message (mirrors
    EnrichedArticleConsumer / EarningsCalendarDatasetConsumer), so the base
    UoW is a no-op.
    """

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class PredictionEnrichedConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Consume ``nlp.article.enriched.v1`` and materialise prediction temporal events.

    Own consumer group (``kg-prediction-enriched-group``) so it sees the enriched
    topic independently of EnrichedArticleConsumer. Only Polymarket synthetic docs
    (``source_type == 'polymarket'``) produce writes.

    Args:
    ----
        config:            Consumer configuration (bootstrap servers, group, topics).
        session_factory:   async_sessionmaker for intelligence_db (read/write).
        dedup_client:      Optional Valkey dedup client (idempotency across restarts).
        polarity_classifier: Optional collaborator injected by Wave C3. When None
            (the default, and the only wiring today) exposures are written with
            NULL polarity. When present it is consulted per (event, entity) to
            derive ('bullish'|'bearish'|'neutral', confidence). This seam keeps
            C2 free of the LLM classifier while letting C3 drop it in without
            touching the write path.
    """

    # 7-day TTL comfortably spans re-delivery windows for the low-volume
    # (one/two docs per market) synthetic-document stream.
    _dedup_prefix: str = "kg:dedup:prediction_enriched_consumer"
    _dedup_ttl_seconds: ClassVar[int] = 7 * 86400

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dedup_client: Any | None = None,
        polarity_classifier: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._dedup_client = dedup_client
        self._polarity_classifier = polarity_classifier

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Materialise one prediction temporal event (+ exposures) from an enriched doc."""
        source_type = str(value.get("source_type", ""))
        if source_type != _POLYMARKET_SOURCE_TYPE:
            # Not a Polymarket synthetic document — skip silently. This consumer
            # shares nlp.article.enriched.v1 with EnrichedArticleConsumer, so the
            # vast majority of messages are not for us.
            return

        raw_doc_id = value.get("doc_id")
        if not raw_doc_id:
            logger.warning("prediction_enriched_consumer_missing_doc_id")
            return
        try:
            doc_id = UUID(str(raw_doc_id))
        except ValueError:
            logger.warning("prediction_enriched_consumer_bad_doc_id", doc_id=str(raw_doc_id))
            return

        # active_from: prefer the market's published_at, fall back to the event's
        # occurred_at, finally to now — the natural key truncates to the day.
        active_from = (
            _parse_iso_dt(value.get("published_at")) or _parse_iso_dt(value.get("occurred_at")) or ct.utc_now()
        )

        # Resolved entity ids the market question mentions (may be empty).
        raw_entity_ids: list[Any] = list(value.get("resolved_entity_ids") or [])

        title = f"Prediction market {doc_id}"

        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
            TemporalEventRepository,
        )

        exposures_written = 0
        async with self._sf() as session:
            event_repo = TemporalEventRepository(session)
            exposure_repo = EntityEventExposureRepository(session)

            # (a) ONE prediction temporal event, idempotent on the natural key.
            db_event_id: UUID = await event_repo.upsert_by_natural_key(
                event_id=new_uuid7(),
                event_type=EventType.PREDICTION,
                scope=EventScope.LOCAL,
                region=_PREDICTION_REGION,
                title=title,
                active_from=active_from,
                active_until=None,  # market close_time not recoverable from enriched event
                residual_impact_days=_RESIDUAL_IMPACT_DAYS,
                confidence=_DEFAULT_EVENT_CONFIDENCE,
            )

            # (b) ONE exposure per resolved entity (DIRECTLY_AFFECTED).
            seen: set[UUID] = set()
            for raw_entity_id in raw_entity_ids:
                try:
                    entity_id = UUID(str(raw_entity_id))
                except ValueError:
                    logger.warning(
                        "prediction_enriched_consumer_bad_entity_id",
                        doc_id=str(doc_id),
                        entity_id=str(raw_entity_id),
                    )
                    continue
                if entity_id in seen:
                    continue  # de-dupe repeated ids within the same payload
                seen.add(entity_id)

                polarity, polarity_confidence = self._resolve_polarity(
                    event_id=db_event_id,
                    entity_id=entity_id,
                    title=title,
                )
                await exposure_repo.upsert(
                    exposure_id=new_uuid7(),
                    event_id=db_event_id,
                    entity_id=entity_id,
                    exposure_type=ExposureType.DIRECTLY_AFFECTED,
                    confidence=_DEFAULT_EXPOSURE_CONFIDENCE,
                    polarity=polarity,
                    polarity_confidence=polarity_confidence,
                )
                exposures_written += 1

            # R26: the consumer OWNS the commit — without this the writes roll back
            # on session close (the HTTP200-but-rollback class of KG bug).
            await session.commit()

        logger.info(
            "prediction_enriched_consumer_processed",
            doc_id=str(doc_id),
            event_id=str(db_event_id),
            exposures=exposures_written,
            entities_seen=len(raw_entity_ids),
        )

    def _resolve_polarity(
        self,
        *,
        event_id: UUID,
        entity_id: UUID,
        title: str,
    ) -> tuple[str | None, float | None]:
        """Return (polarity, polarity_confidence) for one exposure.

        Wave C2 has no classifier wired, so this returns (None, None) → NULL
        polarity. Wave C3 injects a ``polarity_classifier`` collaborator; this
        seam lets that wave slot the LLM call in without touching the write path.
        """
        if self._polarity_classifier is None:
            return (None, None)
        # Wave C3 wires the classifier; kept defensive so a partial C3 rollout
        # never blocks ingestion (PRD §13 — default neutral, never block).
        try:
            result: tuple[str | None, float | None] = self._polarity_classifier.classify(
                event_id=event_id,
                entity_id=entity_id,
                title=title,
            )
            return result
        except Exception:
            logger.warning(
                "prediction_enriched_consumer_polarity_classify_failed",
                event_id=str(event_id),
                entity_id=str(entity_id),
                exc_info=True,
            )
            return (None, None)

    # ------------------------------------------------------------------
    # Failure tracking (log-only — mirrors the other KG consumers)
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(
            "prediction_enriched_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(
            "prediction_enriched_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(
            "prediction_enriched_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(
            "prediction_enriched_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode nlp.article.enriched.v1 (Confluent-Avro wire format, JSON fallback)."""
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _ARTICLE_ENRICHED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00" and path:
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _ARTICLE_ENRICHED_TOPIC:
            return _ARTICLE_ENRICHED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
