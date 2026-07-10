"""PredictionMoveConsumer — material-move → per-entity prediction signals (Wave D2).

Consumer group: ``kg-prediction-move-group`` (own group on
``market.prediction.move.v1``).

PLAN-0056 Wave D2 (PRD-0033). S3 Wave D1 (PredictionMoveDetector) emits a
``market.prediction.move.v1`` event whenever a Polymarket market's implied
probability moves materially over a window. S7 owns the entity↔market linkage
(``entity_event_exposures`` keyed on ``temporal_events.region == condition_id``),
so it is the service that joins a move back to the market's exposed entities and
emits one ``market.prediction.signal.v1`` per entity (via ``PredictionSignalEmitter``).

Pipeline (per move event):
  1. Skip backfilled moves (``is_backfill=True``) — those must never fire user
     signals (they are historical, not live).
  2. Look up the market's entity exposures via
     ``EntityEventExposureRepository.list_exposures_for_condition(condition_id)``.
  3. If ≥ 1 exposure, call ``PredictionSignalEmitter.emit`` with
     ``trigger='material_move'`` + the move context (delta/direction/window). If
     none, no-op (the market is not linked to any tracked entity).
  4. Commit (R26 — the consumer OWNS the commit).

Idempotency: the emitter derives a deterministic outbox event_id from
``(condition_id, entity_id, 'material_move', window_start_ts)`` so a re-delivered
move for the same window inserts the SAME outbox row (ON CONFLICT DO NOTHING).

R9 (own DB + Kafka only), R8 (outbox), R10/R11 (``utc_now`` in the emitter).
structlog only.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from knowledge_graph.application.services.prediction_signal_emitter import (
    TRIGGER_MATERIAL_MOVE,
    ExposureSignalInput,
    MoveContext,
)
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


_MOVE_TOPIC = "market.prediction.move.v1"
_MOVE_SCHEMA_PATH = get_schema_path("market.prediction.move.v1.avsc")


class _NoOpUoW:
    """Minimal UoW satisfying BaseKafkaConsumer's context-manager contract.

    The consumer manages its own AsyncSession inside process_message (mirrors
    PredictionEnrichedConsumer), so the base UoW is a no-op.
    """

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class PredictionMoveConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Consume ``market.prediction.move.v1`` and emit per-entity material-move signals.

    Args:
    ----
        config:           Consumer configuration (bootstrap servers, group, topics).
        session_factory:  async_sessionmaker for intelligence_db (read + outbox write).
        signal_emitter:   ``PredictionSignalEmitter`` — required; turns the move into
                          one signal per linked entity.
        dedup_client:     Optional Valkey dedup client (idempotency across restarts).
    """

    _dedup_prefix: str = "kg:dedup:prediction_move_consumer"
    _dedup_ttl_seconds: ClassVar[int] = 7 * 86400

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        signal_emitter: Any,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._signal_emitter = signal_emitter
        self._dedup_client = dedup_client

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Join a material move to its market's entity exposures and emit signals."""
        # Backfilled moves are historical — never fire user-facing signals (D1 §).
        if bool(value.get("is_backfill", False)):
            return

        condition_id = value.get("market_id")
        if not condition_id or not isinstance(condition_id, str):
            logger.warning("prediction_move_consumer_missing_market_id")
            return

        raw_delta = value.get("delta")
        try:
            delta = float(raw_delta)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            logger.warning("prediction_move_consumer_bad_delta", market_id=condition_id, delta=str(raw_delta))
            return
        direction = str(value.get("direction", ""))
        window_start_ts = value.get("window_start_ts")
        window_start = str(window_start_ts) if isinstance(window_start_ts, str) else None

        from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
            OutboxRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        signals_emitted = 0
        async with self._sf() as session:
            exposure_repo = EntityEventExposureRepository(session)
            question, rows = await exposure_repo.list_exposures_for_condition(condition_id=condition_id)
            if not rows:
                # Market not linked to any entity → nothing to signal (no-op).
                logger.debug("prediction_move_consumer_no_exposures", market_id=condition_id)
                return

            exposures = [
                ExposureSignalInput(
                    entity_id=row["entity_id"],  # type: ignore[arg-type]
                    polarity=row["polarity"],  # type: ignore[arg-type]
                    polarity_confidence=row["polarity_confidence"],  # type: ignore[arg-type]
                    confidence=float(row["confidence"]),  # type: ignore[arg-type]
                )
                for row in rows
            ]

            outbox_repo = OutboxRepository(session)
            signals_emitted = await self._signal_emitter.emit(
                outbox_repo,
                condition_id=condition_id,
                # question falls back to the market id when the title is unknown
                # (the signal schema requires a non-null question).
                question=question or condition_id,
                trigger=TRIGGER_MATERIAL_MOVE,
                exposures=exposures,
                move=MoveContext(delta=delta, direction=direction, window_start_ts=window_start),
                correlation_id=value.get("correlation_id"),
            )

            # R26: the consumer OWNS the commit — outbox rows roll back otherwise.
            await session.commit()

        logger.info(
            "prediction_move_consumer_processed",
            market_id=condition_id,
            direction=direction,
            delta=round(delta, 4),
            exposures=len(rows),
            signals_emitted=signals_emitted,
        )

    # ------------------------------------------------------------------
    # Failure tracking (log-only — mirrors the other KG consumers)
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(
            "prediction_move_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(
            "prediction_move_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(
            "prediction_move_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(
            "prediction_move_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode market.prediction.move.v1 (Confluent-Avro wire format, JSON fallback)."""
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _MOVE_SCHEMA_PATH
        if raw and raw[:1] == b"\x00" and path:
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _MOVE_TOPIC:
            return _MOVE_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
