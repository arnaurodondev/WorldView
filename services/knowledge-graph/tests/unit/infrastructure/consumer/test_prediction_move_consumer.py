"""Unit tests for PredictionMoveConsumer (PLAN-0056 Wave D2).

Covers:
- A move for a market with 2 exposures → 2 material_move signals (one per entity).
- An unlinked market (no exposures) → 0 signals, no commit.
- Backfilled moves are skipped (never fire user signals).
- Missing/bad fields are handled defensively.
- The emitter receives the move context (delta/direction/window).

PLAN-0056 Wave D2 (PRD-0033).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_CONDITION_ID = "0xabc123"
_ENTITY_A = UUID("01920000-0000-7000-8000-000000000001")
_ENTITY_B = UUID("01920000-0000-7000-8000-000000000002")

_EXPOSURE_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.EntityEventExposureRepository"  # noqa: E501
_OUTBOX_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.outbox.OutboxRepository"


def _make_consumer(
    *,
    exposures: list[dict[str, Any]] | None = None,
    question: str | None = "Will X happen?",
) -> tuple[Any, Any, Any, Any]:
    """Build a PredictionMoveConsumer with mocked session, repos and emitter.

    Returns (consumer, exposure_repo_mock, emitter_mock, session_mock).
    """
    from knowledge_graph.infrastructure.messaging.consumers.prediction_move_consumer import (
        PredictionMoveConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-prediction-move-test",
        topics=["market.prediction.move.v1"],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    exposure_repo = AsyncMock()
    exposure_repo.list_exposures_for_condition = AsyncMock(return_value=(question, exposures or []))

    emitter = AsyncMock()
    emitter.emit = AsyncMock(return_value=len(exposures or []))

    consumer = PredictionMoveConsumer(config=config, session_factory=sf, signal_emitter=emitter)
    return consumer, exposure_repo, emitter, session


def _move(
    *,
    market_id: str = _CONDITION_ID,
    delta: float = 0.3,
    direction: str = "up",
    is_backfill: bool = False,
    window_start_ts: str | None = "2026-07-09T00:00:00+00:00",
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "event_id": str(uuid4()),
        "market_id": market_id,
        "token_id": "tok-1",
        "delta": delta,
        "direction": direction,
        "prev_price": 0.4,
        "new_price": 0.4 + delta,
        "is_backfill": is_backfill,
    }
    if window_start_ts is not None:
        msg["window_start_ts"] = window_start_ts
    return msg


def _exposure_rows() -> list[dict[str, Any]]:
    return [
        {"entity_id": _ENTITY_A, "polarity": "bullish", "polarity_confidence": 0.8, "confidence": 0.5},
        {"entity_id": _ENTITY_B, "polarity": "bearish", "polarity_confidence": 0.7, "confidence": 0.5},
    ]


class TestPredictionMoveConsumerHappyPath:
    def test_two_exposures_yield_two_signals(self) -> None:
        consumer, exposure_repo, emitter, session = _make_consumer(exposures=_exposure_rows())
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, _move(), {}))

        emitter.emit.assert_awaited_once()
        kwargs = emitter.emit.call_args.kwargs
        assert kwargs["trigger"] == "material_move"
        assert len(kwargs["exposures"]) == 2
        assert kwargs["condition_id"] == _CONDITION_ID
        assert kwargs["question"] == "Will X happen?"
        session.commit.assert_awaited_once()

    def test_move_context_passed_to_emitter(self) -> None:
        consumer, exposure_repo, emitter, _ = _make_consumer(exposures=_exposure_rows())
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, _move(delta=-0.25, direction="down"), {}))

        move = emitter.emit.call_args.kwargs["move"]
        assert move.delta == pytest.approx(-0.25)
        assert move.direction == "down"
        assert move.window_start_ts == "2026-07-09T00:00:00+00:00"

    def test_question_falls_back_to_condition_id(self) -> None:
        consumer, exposure_repo, emitter, _ = _make_consumer(exposures=_exposure_rows(), question=None)
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, _move(), {}))
        assert emitter.emit.call_args.kwargs["question"] == _CONDITION_ID


class TestPredictionMoveConsumerNoOp:
    def test_unlinked_market_emits_nothing(self) -> None:
        consumer, exposure_repo, emitter, session = _make_consumer(exposures=[])
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, _move(), {}))

        emitter.emit.assert_not_awaited()
        session.commit.assert_not_awaited()

    def test_backfill_move_skipped(self) -> None:
        consumer, exposure_repo, emitter, _ = _make_consumer(exposures=_exposure_rows())
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, _move(is_backfill=True), {}))

        exposure_repo.list_exposures_for_condition.assert_not_awaited()
        emitter.emit.assert_not_awaited()


class TestPredictionMoveConsumerMalformed:
    def test_missing_market_id_skipped(self) -> None:
        consumer, exposure_repo, emitter, _ = _make_consumer(exposures=_exposure_rows())
        msg = _move()
        del msg["market_id"]
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))
        emitter.emit.assert_not_awaited()

    def test_bad_delta_skipped(self) -> None:
        consumer, exposure_repo, emitter, _ = _make_consumer(exposures=_exposure_rows())
        with (
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=AsyncMock()),
        ):
            asyncio.run(consumer.process_message(None, {"market_id": _CONDITION_ID, "delta": "n/a"}, {}))
        emitter.emit.assert_not_awaited()


class TestPredictionMoveConsumerPlumbing:
    def test_extract_event_id(self) -> None:
        consumer, _, _, _ = _make_consumer()
        assert consumer.extract_event_id({"event_id": "abc-1"}) == "abc-1"

    def test_get_schema_path(self) -> None:
        consumer, _, _, _ = _make_consumer()
        assert consumer.get_schema_path("market.prediction.move.v1") is not None
        assert consumer.get_schema_path("other.topic") is None
