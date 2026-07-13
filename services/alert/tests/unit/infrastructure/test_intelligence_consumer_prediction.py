"""Unit tests for IntelligenceConsumer — prediction-signal path (PLAN-0056 Wave D3).

Covers: topic resolution for ``market.prediction.signal.v1``, schema-path
registration, and routing the deserialized event into AlertFanoutUseCase with the
market_impact_score gating field carried through.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.application.use_cases.alert_fanout import FanoutResult
from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_PREDICTION_TOPIC = "market.prediction.signal.v1"


def _make_consumer() -> tuple[IntelligenceConsumer, AsyncMock]:
    mock_fanout = AsyncMock()
    mock_fanout.execute = AsyncMock(return_value=FanoutResult())
    config = ConsumerConfig(
        group_id="alert-service-group",
        topics=[
            "nlp.signal.detected.v1",
            "graph.state.changed.v1",
            "intelligence.contradiction.v1",
            _PREDICTION_TOPIC,
        ],
    )
    return IntelligenceConsumer(config, fanout_use_case=mock_fanout), mock_fanout


class TestIntelligenceConsumerPrediction:
    @pytest.mark.unit
    def test_resolve_topic_prediction_from_header(self) -> None:
        headers = {"X-Source-Topic": _PREDICTION_TOPIC}
        assert IntelligenceConsumer._resolve_topic({}, headers) == _PREDICTION_TOPIC

    @pytest.mark.unit
    def test_resolve_topic_prediction_from_event_type(self) -> None:
        value = {"event_type": "market.prediction.signal"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == _PREDICTION_TOPIC

    @pytest.mark.unit
    def test_get_schema_path_returns_path_for_prediction_topic(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path(_PREDICTION_TOPIC) is not None

    @pytest.mark.unit
    async def test_routes_prediction_event_to_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "market.prediction.signal",
            "subject_entity_id": str(uuid4()),
            "market_id": "0xcondition",
            "trigger": "material_move",
            "polarity": "bearish",
            "market_impact_score": 0.72,
            "question": "Will ACME miss guidance?",
            "is_backfill": False,
        }

        await consumer.process_message(None, value, {})

        mock_fanout.execute.assert_awaited_once()
        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["topic"] == _PREDICTION_TOPIC
        # The gating score must be clamped into [0,1] and forwarded to fanout.
        assert call_kwargs["market_impact_score"] == pytest.approx(0.72)

    @pytest.mark.unit
    async def test_prediction_score_clamped_before_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "market.prediction.signal",
            "subject_entity_id": str(uuid4()),
            "market_impact_score": 1.9,  # out of range → clamps to 1.0
            "is_backfill": False,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(1.0)
