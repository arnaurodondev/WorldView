"""Unit tests for PredictionSignalEmitter (PLAN-0056 Wave D2).

Covers:
- material_move score = clamp(|delta|); adverse boost (bearish+up / bullish+down).
- new_market score = base * exposure.confidence; resolution = fixed base.
- one signal emitted per exposure; polarity carried onto the payload.
- new_market gate off → nothing emitted.
- idempotent dedup: same (market, entity, trigger, window) → same outbox event_id.

PLAN-0056 Wave D2 (PRD-0033).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from knowledge_graph.application.services.prediction_signal_emitter import (
    TRIGGER_MATERIAL_MOVE,
    TRIGGER_NEW_MARKET,
    TRIGGER_RESOLUTION,
    ExposureSignalInput,
    MoveContext,
    PredictionSignalEmitter,
)

from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_CONDITION_ID = "0xabc123"
_ENTITY_A = UUID("01920000-0000-7000-8000-000000000001")
_ENTITY_B = UUID("01920000-0000-7000-8000-000000000002")
_SIGNAL_SCHEMA = get_schema_path("market.prediction.signal.v1.avsc")


def _emitter(**kwargs: object) -> PredictionSignalEmitter:
    defaults: dict[str, object] = {
        "emit_new_market": True,
        "new_market_base": 0.5,
        "resolution_base": 0.6,
        "material_move_adverse_factor": 1.25,
    }
    defaults.update(kwargs)
    return PredictionSignalEmitter(**defaults)  # type: ignore[arg-type]


def _exposure(polarity: str | None = None, confidence: float = 0.5) -> ExposureSignalInput:
    return ExposureSignalInput(
        entity_id=_ENTITY_A,
        polarity=polarity,
        polarity_confidence=None,
        confidence=confidence,
    )


def _decode(payload_bytes: bytes) -> dict[str, object]:
    return deserialize_confluent_avro(_SIGNAL_SCHEMA, payload_bytes)


# ── Scoring ──────────────────────────────────────────────────────────────────


class TestComputeImpactScore:
    def test_material_move_score_from_delta(self) -> None:
        emitter = _emitter()
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="neutral"),
            move=MoveContext(delta=0.3, direction="up", window_start_ts="2026-07-09T00:00:00+00:00"),
        )
        assert score == pytest.approx(0.3)

    def test_material_move_delta_clamped_to_one(self) -> None:
        emitter = _emitter()
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="neutral"),
            move=MoveContext(delta=-1.5, direction="down", window_start_ts=None),
        )
        assert score == pytest.approx(1.0)

    def test_adverse_boost_bearish_up(self) -> None:
        """bearish outcome rising is adverse → base * adverse_factor (capped at 1)."""
        emitter = _emitter(material_move_adverse_factor=1.25)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="bearish"),
            move=MoveContext(delta=0.4, direction="up", window_start_ts=None),
        )
        assert score == pytest.approx(0.5)  # 0.4 * 1.25

    def test_adverse_boost_bullish_down(self) -> None:
        """favourable (bullish) outcome falling is adverse → boosted."""
        emitter = _emitter(material_move_adverse_factor=1.25)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="bullish"),
            move=MoveContext(delta=-0.4, direction="down", window_start_ts=None),
        )
        assert score == pytest.approx(0.5)

    def test_non_adverse_move_not_boosted(self) -> None:
        """bullish outcome rising is favourable, not adverse → no boost."""
        emitter = _emitter(material_move_adverse_factor=1.25)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="bullish"),
            move=MoveContext(delta=0.4, direction="up", window_start_ts=None),
        )
        assert score == pytest.approx(0.4)

    def test_adverse_boost_capped_at_one(self) -> None:
        emitter = _emitter(material_move_adverse_factor=2.0)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_MATERIAL_MOVE,
            exposure=_exposure(polarity="bearish"),
            move=MoveContext(delta=0.8, direction="up", window_start_ts=None),
        )
        assert score == pytest.approx(1.0)  # 0.8 * 2.0 = 1.6 → clamped

    def test_new_market_score_is_base_times_confidence(self) -> None:
        emitter = _emitter(new_market_base=0.5)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_NEW_MARKET,
            exposure=_exposure(confidence=0.6),
        )
        assert score == pytest.approx(0.3)  # 0.5 * 0.6

    def test_resolution_score_is_fixed_base(self) -> None:
        emitter = _emitter(resolution_base=0.6)
        score = emitter.compute_impact_score(
            trigger=TRIGGER_RESOLUTION,
            exposure=_exposure(confidence=0.9),
        )
        assert score == pytest.approx(0.6)  # independent of confidence

    def test_material_move_without_context_raises(self) -> None:
        emitter = _emitter()
        with pytest.raises(ValueError, match="MoveContext"):
            emitter.compute_impact_score(trigger=TRIGGER_MATERIAL_MOVE, exposure=_exposure())


# ── Emit ─────────────────────────────────────────────────────────────────────


class TestEmit:
    def test_one_signal_per_exposure(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        emitted = asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Will X happen?",
                trigger=TRIGGER_NEW_MARKET,
                exposures=[
                    ExposureSignalInput(_ENTITY_A, "bullish", 0.8, 0.5),
                    ExposureSignalInput(_ENTITY_B, "bearish", 0.7, 0.5),
                ],
            ),
        )
        assert emitted == 2
        assert outbox.append.await_count == 2
        subjects = {_decode(c.kwargs["payload_avro"])["subject_entity_id"] for c in outbox.append.call_args_list}
        assert subjects == {str(_ENTITY_A), str(_ENTITY_B)}

    def test_polarity_carried_onto_payload(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_RESOLUTION,
                exposures=[ExposureSignalInput(_ENTITY_A, "bearish", 0.7, 0.5)],
            ),
        )
        payload = _decode(outbox.append.call_args.kwargs["payload_avro"])
        assert payload["polarity"] == "bearish"
        assert payload["trigger"] == "resolution"
        assert payload["market_id"] == _CONDITION_ID
        assert payload["question"] == "Q?"
        assert payload["url"] is None

    def test_null_polarity_defaults_to_neutral(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_RESOLUTION,
                exposures=[ExposureSignalInput(_ENTITY_A, None, None, 0.5)],
            ),
        )
        payload = _decode(outbox.append.call_args.kwargs["payload_avro"])
        assert payload["polarity"] == "neutral"

    def test_new_market_gate_off_emits_nothing(self) -> None:
        emitter = _emitter(emit_new_market=False)
        outbox = AsyncMock(append=AsyncMock())
        emitted = asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_NEW_MARKET,
                exposures=[_exposure()],
            ),
        )
        assert emitted == 0
        outbox.append.assert_not_awaited()

    def test_gate_off_still_allows_material_move(self) -> None:
        emitter = _emitter(emit_new_market=False)
        outbox = AsyncMock(append=AsyncMock())
        emitted = asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_MATERIAL_MOVE,
                exposures=[_exposure(polarity="neutral")],
                move=MoveContext(delta=0.2, direction="up", window_start_ts=None),
            ),
        )
        assert emitted == 1

    def test_empty_exposures_emit_nothing(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        emitted = asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_RESOLUTION,
                exposures=[],
            ),
        )
        assert emitted == 0
        outbox.append.assert_not_awaited()

    def test_idempotent_event_id_stable_across_calls(self) -> None:
        """Re-emitting the same (market, entity, trigger, window) uses the SAME event_id."""
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        move = MoveContext(delta=0.3, direction="up", window_start_ts="2026-07-09T00:00:00+00:00")
        for _ in range(2):
            asyncio.run(
                emitter.emit(
                    outbox,
                    condition_id=_CONDITION_ID,
                    question="Q?",
                    trigger=TRIGGER_MATERIAL_MOVE,
                    exposures=[_exposure(polarity="neutral")],
                    move=move,
                ),
            )
        first_id = outbox.append.call_args_list[0].kwargs["event_id"]
        second_id = outbox.append.call_args_list[1].kwargs["event_id"]
        assert first_id == second_id

    def test_distinct_windows_get_distinct_event_ids(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        for ts in ("2026-07-09T00:00:00+00:00", "2026-07-10T00:00:00+00:00"):
            asyncio.run(
                emitter.emit(
                    outbox,
                    condition_id=_CONDITION_ID,
                    question="Q?",
                    trigger=TRIGGER_MATERIAL_MOVE,
                    exposures=[_exposure(polarity="neutral")],
                    move=MoveContext(delta=0.3, direction="up", window_start_ts=ts),
                ),
            )
        first_id = outbox.append.call_args_list[0].kwargs["event_id"]
        second_id = outbox.append.call_args_list[1].kwargs["event_id"]
        assert first_id != second_id

    def test_partition_key_is_subject_entity(self) -> None:
        emitter = _emitter()
        outbox = AsyncMock(append=AsyncMock())
        asyncio.run(
            emitter.emit(
                outbox,
                condition_id=_CONDITION_ID,
                question="Q?",
                trigger=TRIGGER_RESOLUTION,
                exposures=[_exposure()],
            ),
        )
        assert outbox.append.call_args.kwargs["partition_key"] == str(_ENTITY_A)
