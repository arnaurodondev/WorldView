"""PredictionSignalEmitter — turn prediction triggers into per-entity signals (Wave D2).

PLAN-0056 Wave D2 (PRD-0033).  S7 owns ``entity_event_exposures`` (entity +
polarity + condition_id), so it is the natural place to compute the per-entity
``market.prediction.signal.v1`` signal for the three prediction triggers:

  * ``new_market``    — a prediction market referencing an entity is seen for the
    first time (first-sight synthetic doc).  Emitted by ``PredictionEnrichedConsumer``.
  * ``material_move`` — the market's implied probability moved materially
    (``market.prediction.move.v1`` from S3 Wave D1).  Emitted by
    ``PredictionMoveConsumer``.
  * ``resolution``    — the market resolved (resolution synthetic doc).  Emitted by
    ``PredictionEnrichedConsumer``.

For EACH entity exposure the emitter writes ONE signal via the transactional
**outbox** (R8) — the alert service (Wave D3) consumes the topic and gates fanout
on the user watchlist (the "tracked entity" gate lives downstream, not here).

Scoring (``market_impact_score`` ∈ [0, 1], tunables from S7 config — no magic
numbers buried in logic):

  * ``material_move``: ``base = clamp(|delta|, 0..1)``.  When the move is *adverse*
    for the entity — the bearish outcome rising (``polarity=='bearish' and
    direction=='up'``) OR the entity's favourable outcome falling
    (``polarity=='bullish' and direction=='down'``) — ``base`` is multiplied by
    ``material_move_adverse_factor`` and re-clamped to ≤ 1.0.
  * ``new_market``: ``clamp(new_market_base * exposure.confidence, 0..1)``.
  * ``resolution``: ``clamp(resolution_base, 0..1)`` (fixed).

Idempotency: the outbox event_id is derived deterministically via ``uuid5`` from
``(condition_id, subject_entity_id, trigger, window)`` so a re-delivery inserts the
SAME outbox row — ``OutboxRepository.append`` uses ``ON CONFLICT (event_id) DO
NOTHING`` — and never double-emits.  ``window`` is the move window-start for
``material_move`` (so distinct windows are distinct signals) and the trigger name
for ``new_market`` / ``resolution`` (once per market+entity+trigger).

R8 (outbox), R10/R11 (``new_uuid7`` unused here — deterministic ids; ``utc_now``).
Domain-layer independence: this application service depends only on an
``OutboxRepositoryPort``-shaped object (``append``) and pure config values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

import common.time as ct  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.topics import MARKET_PREDICTION_SIGNAL  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Trigger discriminators (mirror the market.prediction.signal.v1.avsc ``trigger`` doc).
TRIGGER_NEW_MARKET = "new_market"
TRIGGER_MATERIAL_MOVE = "material_move"
TRIGGER_RESOLUTION = "resolution"

_SIGNAL_EVENT_TYPE = "market.prediction.signal"
_SIGNAL_SCHEMA_PATH = get_schema_path("market.prediction.signal.v1.avsc")

# Stable namespace for deterministic per-signal event ids (idempotent outbox key).
# A fixed UUID → uuid5 is reproducible across processes/restarts so re-delivery of
# the same (market, entity, trigger, window) yields the SAME outbox event_id.
_SIGNAL_ID_NAMESPACE = UUID("6f3d2c1a-9b4e-5f70-8a21-0c9d7e5b1234")


def _clamp01(value: float) -> float:
    """Clamp *value* into the closed unit interval [0.0, 1.0]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class ExposureSignalInput:
    """One entity exposure to signal on (subset of ``entity_event_exposures``)."""

    entity_id: UUID
    polarity: str | None
    polarity_confidence: float | None
    confidence: float


@dataclass(frozen=True)
class MoveContext:
    """Material-move context carried from ``market.prediction.move.v1`` (Wave D1)."""

    delta: float
    direction: str  # "up" | "down"
    window_start_ts: str | None


class PredictionSignalEmitter:
    """Emit per-entity ``market.prediction.signal.v1`` events via the outbox (R8).

    Stateless apart from the injected config tunables; safe to share across
    consumers.  ``emit`` is called from inside the caller's write transaction so
    the signal rows commit atomically with the caller's own writes.
    """

    def __init__(
        self,
        *,
        emit_new_market: bool = True,
        new_market_base: float = 0.5,
        resolution_base: float = 0.6,
        material_move_adverse_factor: float = 1.25,
    ) -> None:
        self._emit_new_market = emit_new_market
        self._new_market_base = new_market_base
        self._resolution_base = resolution_base
        self._material_move_adverse_factor = material_move_adverse_factor

    # ------------------------------------------------------------------
    # Scoring (pure)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_adverse(polarity: str | None, direction: str) -> bool:
        """True when a material move is adverse for the entity.

        Adverse = the bearish (bad-for-entity) outcome rising, OR the entity's
        favourable (bullish) outcome falling.
        """
        return (polarity == "bearish" and direction == "up") or (polarity == "bullish" and direction == "down")

    def compute_impact_score(
        self,
        *,
        trigger: str,
        exposure: ExposureSignalInput,
        move: MoveContext | None = None,
    ) -> float:
        """Compute the gating ``market_impact_score`` ∈ [0, 1] for one exposure."""
        if trigger == TRIGGER_MATERIAL_MOVE:
            if move is None:
                msg = "material_move trigger requires a MoveContext"
                raise ValueError(msg)
            base = _clamp01(abs(move.delta))
            if self._is_adverse(exposure.polarity, move.direction):
                base = _clamp01(base * self._material_move_adverse_factor)
            return base
        if trigger == TRIGGER_NEW_MARKET:
            return _clamp01(self._new_market_base * exposure.confidence)
        if trigger == TRIGGER_RESOLUTION:
            return _clamp01(self._resolution_base)
        msg = f"unknown prediction signal trigger: {trigger!r}"
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # Idempotency helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_window(trigger: str, move: MoveContext | None) -> str:
        """Return the dedup window component for the deterministic event id.

        material_move keys on the move window-start (distinct windows → distinct
        signals); new_market / resolution key on the trigger (once per market+entity).
        """
        if trigger == TRIGGER_MATERIAL_MOVE and move is not None:
            return move.window_start_ts or ""
        return trigger

    def _signal_event_id(self, *, condition_id: str, entity_id: UUID, trigger: str, window: str) -> UUID:
        """Deterministic UUIDv5 keyed on (market, entity, trigger, window)."""
        return uuid5(_SIGNAL_ID_NAMESPACE, f"{condition_id}|{entity_id}|{trigger}|{window}")

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    def build_signal_payload(
        self,
        *,
        event_id: UUID,
        condition_id: str,
        question: str,
        trigger: str,
        exposure: ExposureSignalInput,
        move: MoveContext | None,
        occurred_at: str,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        """Build the ``market.prediction.signal.v1`` record (schema-aligned dict)."""
        return {
            "event_id": str(event_id),
            "event_type": _SIGNAL_EVENT_TYPE,
            "schema_version": 1,
            "occurred_at": occurred_at,
            "subject_entity_id": str(exposure.entity_id),
            "market_id": condition_id,
            "trigger": trigger,
            "market_impact_score": self.compute_impact_score(trigger=trigger, exposure=exposure, move=move),
            # Polarity defaults to neutral when the exposure has no directional verdict.
            "polarity": exposure.polarity or "neutral",
            "question": question,
            # S7 has no market slug; the gateway builds the /event/{slug} link from
            # market_id (condition_id) downstream.
            "url": None,
            "correlation_id": correlation_id,
        }

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    async def emit(
        self,
        outbox_repo: Any,
        *,
        condition_id: str,
        question: str,
        trigger: str,
        exposures: Sequence[ExposureSignalInput],
        move: MoveContext | None = None,
        correlation_id: str | None = None,
    ) -> int:
        """Emit ONE signal per exposure via the outbox; return the count emitted.

        No-ops (returns 0) when: the new_market gate is off and trigger==new_market,
        or ``exposures`` is empty.  Each signal is serialized to Confluent-Avro
        BEFORE the outbox append (fail before the DB write, never after) and keyed
        on a deterministic event_id so re-delivery is idempotent.
        """
        if trigger == TRIGGER_NEW_MARKET and not self._emit_new_market:
            logger.debug("prediction_signal_new_market_gated_off", condition_id=condition_id)
            return 0
        if not exposures:
            return 0

        from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

        window = self._dedup_window(trigger, move)
        occurred_at = ct.utc_now().isoformat()
        emitted = 0
        for exposure in exposures:
            event_id = self._signal_event_id(
                condition_id=condition_id,
                entity_id=exposure.entity_id,
                trigger=trigger,
                window=window,
            )
            payload = self.build_signal_payload(
                event_id=event_id,
                condition_id=condition_id,
                question=question,
                trigger=trigger,
                exposure=exposure,
                move=move,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
            payload_bytes = serialize_confluent_avro(_SIGNAL_SCHEMA_PATH, payload)
            # partition_key = subject_entity_id so the alert fanout observes a
            # market's signals for one entity in causal order (mirrors graph.state.changed).
            await outbox_repo.append(
                topic=MARKET_PREDICTION_SIGNAL,
                partition_key=str(exposure.entity_id),
                payload_avro=payload_bytes,
                event_id=event_id,
            )
            emitted += 1

        logger.info(
            "prediction_signal_emitted",
            condition_id=condition_id,
            trigger=trigger,
            signals=emitted,
        )
        return emitted
