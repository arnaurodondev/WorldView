"""Unit tests for IntelligenceConsumer."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.application.use_cases.alert_fanout import FanoutResult
from alert.infrastructure.consumer.intelligence_consumer import IntelligenceConsumer

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]


def _make_consumer(
    fanout_result: FanoutResult | None = None,
) -> tuple[IntelligenceConsumer, AsyncMock]:
    mock_fanout = AsyncMock()
    mock_fanout.execute = AsyncMock(return_value=fanout_result or FanoutResult())
    config = ConsumerConfig(
        group_id="alert-service-group",
        topics=[
            "nlp.signal.detected.v1",
            "graph.state.changed.v1",
            "intelligence.contradiction.v1",
        ],
    )
    consumer = IntelligenceConsumer(config, fanout_use_case=mock_fanout)
    return consumer, mock_fanout


class TestIntelligenceConsumer:
    # ── Topic resolution ──────────────────────────────────────────────────────

    @pytest.mark.unit
    def test_resolve_topic_from_header(self) -> None:
        headers = {"X-Source-Topic": "nlp.signal.detected.v1"}
        assert IntelligenceConsumer._resolve_topic({}, headers) == "nlp.signal.detected.v1"

    @pytest.mark.unit
    def test_resolve_topic_nlp_signal_from_event_type(self) -> None:
        value = {"event_type": "nlp.signal.detected"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "nlp.signal.detected.v1"

    @pytest.mark.unit
    def test_resolve_topic_graph_state_from_event_type(self) -> None:
        value = {"event_type": "graph.state.changed"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "graph.state.changed.v1"

    @pytest.mark.unit
    def test_resolve_topic_contradiction_from_event_type(self) -> None:
        value = {"event_type": "intelligence.contradiction"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "intelligence.contradiction.v1"  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_resolve_topic_unknown_falls_back_to_event_type(self) -> None:
        value = {"event_type": "some.unknown.topic"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "some.unknown.topic"

    # ── process_message routing ───────────────────────────────────────────────

    @pytest.mark.unit
    async def test_routes_signal_event_to_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
        }

        await consumer.process_message(None, value, {})

        mock_fanout.execute.assert_awaited_once()
        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["topic"] == "nlp.signal.detected.v1"

    @pytest.mark.unit
    async def test_routes_graph_event_to_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "graph.state.changed",
            "primary_entity_id": str(uuid4()),
            "is_backfill": False,
        }

        await consumer.process_message(None, value, {})

        mock_fanout.execute.assert_awaited_once()
        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["topic"] == "graph.state.changed.v1"

    @pytest.mark.unit
    async def test_routes_contradiction_event_to_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "intelligence.contradiction",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
        }

        await consumer.process_message(None, value, {})

        mock_fanout.execute.assert_awaited_once()
        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["topic"] == "intelligence.contradiction.v1"

    @pytest.mark.unit
    async def test_passes_correlation_id_to_fanout(self) -> None:
        consumer, mock_fanout = _make_consumer()
        corr_id = str(uuid4())
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "correlation_id": corr_id,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["correlation_id"] == corr_id

    # ── Serialization / misc ──────────────────────────────────────────────────

    @pytest.mark.unit
    def test_deserialize_value_json(self) -> None:
        consumer, _ = _make_consumer()
        raw = b'{"event_id": "abc"}'
        result = consumer.deserialize_value(raw)
        assert result["event_id"] == "abc"

    @pytest.mark.unit
    def test_get_schema_path_returns_none(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path("nlp.signal.detected.v1") is None

    @pytest.mark.unit
    async def test_is_duplicate_no_client(self) -> None:
        consumer, _ = _make_consumer()
        assert await consumer.is_duplicate("any-id") is False
