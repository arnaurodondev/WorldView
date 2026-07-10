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

Market identity (PLAN-0056 Wave C2b):
  The ``nlp.article.enriched.v1`` event now carries an ``external_id`` field
  ("polymarket:<condition_id>") threaded verbatim S4→S5→S6, so the real market
  identity IS recoverable here without any R7 cross-service DB read. The normal
  path stores the bare ``condition_id`` in ``temporal_events.region`` and titles
  the event ``f"Prediction market {condition_id}"`` — this makes the natural key
  ``(event_type, region, title, active_from::day)`` unique *per market* rather than
  per synthetic doc, so the first-sight and resolution docs of the same market
  (distinct doc_ids) collapse to ONE row (idempotent per condition_id), and Wave C4
  / Sub-Plan D can join exposures back to a real Polymarket market.

  Fallback: legacy/pre-C2b events (no external_id) keep the old anonymous behaviour
  — region is the constant ``'prediction'`` and the title embeds ``doc_id`` — so
  nothing regresses if the field is absent or malformed.

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

# Fallback category tag stored in temporal_events.region when the market identity
# is NOT recoverable (legacy events with no external_id). PLAN-0056 Wave C2b made
# the condition_id recoverable via the enriched event's external_id, so the normal
# path now stores the condition_id in region instead of this constant.
_PREDICTION_REGION = "prediction"

# PLAN-0056 Wave C2b: the synthetic prediction doc's external_id is stamped by S4
# as "polymarket:<condition_id>" and threaded verbatim S4→S5→S6→here.
_EXTERNAL_ID_PREFIX = "polymarket:"


def _parse_condition_id(external_id: Any) -> str | None:
    """Extract the Polymarket condition_id from an ``external_id`` value.

    The synthetic-document emitter (S4 Wave B2) stamps
    ``external_id = "polymarket:<condition_id>"``.  Returns the bare condition_id,
    or ``None`` when the value is absent/empty/malformed (not a string, wrong
    prefix, or empty after the prefix) so the caller can fall back to the old
    anonymous doc_id-based behaviour (backward-compatible).
    """
    if not isinstance(external_id, str):
        return None
    stripped = external_id.strip()
    if not stripped.startswith(_EXTERNAL_ID_PREFIX):
        return None
    condition_id = stripped[len(_EXTERNAL_ID_PREFIX) :].strip()
    return condition_id or None


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
        polarity_classifier: Optional ``MarketPolarityClassifier`` (Wave C3). When
            None exposures are written with NULL polarity. When present AND the
            enriched event carries the market question (``source_title``), it is
            consulted per (market, entity) via
            ``classify(question, entity_name, outcomes, condition_id=, entity_id=)``
            → ('bullish'|'bearish'|'neutral', confidence), classified once per
            (condition_id, entity_id). On any LLM failure it returns
            ('neutral', 0.0) so ingestion is never blocked (PRD §13).
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

        # PLAN-0056 Wave C3: the market QUESTION now rides along as ``source_title``
        # (S6 copies content.article.stored.v1.title verbatim onto the enriched
        # event — pure passthrough).  When present it becomes BOTH the temporal-event
        # title AND the input to the polarity classifier.  Absent on legacy/non-C3
        # events → None → the anonymous placeholder title is used (backward-compatible).
        raw_source_title = value.get("source_title")
        question: str | None = (
            raw_source_title.strip() if isinstance(raw_source_title, str) and raw_source_title.strip() else None
        )

        # PLAN-0056 Wave C2b: prefer the real market identity (condition_id) carried
        # on the enriched event's external_id.  When present, the temporal event is
        # keyed on the condition_id — so the first-sight and resolution docs of the
        # SAME market (distinct doc_ids) collapse to ONE row (idempotent per market),
        # and Wave C4/D2 can join exposures back to a real Polymarket market. When
        # absent/malformed (legacy events) we fall back to the old anonymous
        # doc_id-based key so nothing regresses.
        condition_id = _parse_condition_id(value.get("external_id"))
        if condition_id is not None:
            region = condition_id
            placeholder_title = f"Prediction market {condition_id}"
        else:
            region = _PREDICTION_REGION
            placeholder_title = f"Prediction market {doc_id}"
        # Wave C3: the real question titles the event when available; else the
        # anonymous placeholder.  ``region`` still keys idempotency per market, and
        # the question is stable per market, so the natural key stays unique-per-market.
        title = question or placeholder_title

        # De-dupe + validate the resolved entity ids ONCE up front so the polarity
        # classification (HTTP) and the exposure writes iterate over the same set.
        valid_entity_ids: list[UUID] = []
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
            valid_entity_ids.append(entity_id)

        # PLAN-0056 Wave C3: classify per-entity polarity BEFORE opening the write
        # session — no DB connection is held across the LLM HTTP calls (R24). Runs
        # only when a classifier is wired AND the question text is available; each
        # (condition_id, entity_id) pair is classified at most once (classifier cache).
        polarity_by_entity: dict[UUID, tuple[str | None, float | None]] = {}
        if self._polarity_classifier is not None and question and valid_entity_ids:
            polarity_by_entity = await self._classify_polarities(
                condition_id=condition_id,
                question=question,
                entity_ids=valid_entity_ids,
            )

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
                region=region,
                title=title,
                active_from=active_from,
                active_until=None,  # market close_time not recoverable from enriched event
                residual_impact_days=_RESIDUAL_IMPACT_DAYS,
                confidence=_DEFAULT_EVENT_CONFIDENCE,
            )

            # (b) ONE exposure per resolved entity (DIRECTLY_AFFECTED). Polarity is
            # NULL unless the Wave C3 classifier produced a verdict for this entity.
            for entity_id in valid_entity_ids:
                polarity, polarity_confidence = polarity_by_entity.get(entity_id, (None, None))
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
            # PLAN-0056 Wave C2b: condition_id is None on the legacy fallback path.
            condition_id=condition_id,
            region=region,
            # PLAN-0056 Wave C3: whether the real question titled the event.
            has_question=question is not None,
            polarities_classified=len(polarity_by_entity),
            exposures=exposures_written,
            entities_seen=len(raw_entity_ids),
        )

    async def _classify_polarities(
        self,
        *,
        condition_id: str | None,
        question: str,
        entity_ids: list[UUID],
    ) -> dict[UUID, tuple[str | None, float | None]]:
        """Classify polarity for each (market, entity) pair (PLAN-0056 Wave C3).

        Two phases so no DB connection is held across the LLM HTTP calls (R24):
          1. Look up each entity's canonical name in a short read session, then
             release it.
          2. Call the injected ``polarity_classifier`` (DeepInfra small model) per
             entity that resolved to a name.  The classifier caches by
             ``(condition_id, entity_id)`` and returns ``("neutral", 0.0)`` on any
             failure (PRD §13 — never blocks ingestion), so this never raises.

        Entities with no resolvable name are omitted from the result → their
        exposure keeps NULL polarity.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        # Guarded by the caller (only invoked when polarity_classifier is not None);
        # assert narrows the Any | None type for the classify() call below.
        assert self._polarity_classifier is not None

        # Phase 1 — resolve names (DB), session released before any HTTP call.
        name_by_id: dict[UUID, str | None] = {}
        async with self._sf() as session:
            entity_repo = CanonicalEntityRepository(session)
            for entity_id in entity_ids:
                try:
                    row = await entity_repo.get(entity_id)
                except Exception:
                    logger.warning(
                        "prediction_enriched_consumer_entity_name_lookup_failed",
                        entity_id=str(entity_id),
                        exc_info=True,
                    )
                    row = None
                name = row.get("canonical_name") if row else None
                name_by_id[entity_id] = str(name) if name else None

        # Phase 2 — classify (HTTP, no DB session held).
        results: dict[UUID, tuple[str | None, float | None]] = {}
        for entity_id in entity_ids:
            entity_name = name_by_id.get(entity_id)
            if not entity_name:
                continue  # no name → leave polarity NULL for this exposure
            try:
                polarity, confidence = await self._polarity_classifier.classify(
                    question=question,
                    entity_name=entity_name,
                    outcomes=None,
                    condition_id=condition_id,
                    entity_id=entity_id,
                )
            except Exception:
                # Defensive: the classifier already swallows its own errors, but a
                # broken injection must never block ingestion.
                logger.warning(
                    "prediction_enriched_consumer_polarity_classify_failed",
                    entity_id=str(entity_id),
                    exc_info=True,
                )
                continue
            results[entity_id] = (polarity, confidence)
        return results

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
