"""Unit tests for IntelligenceConsumer."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.application.use_cases.alert_fanout import FanoutResult
from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer
from structlog.testing import capture_logs

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


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
    def test_get_schema_path_returns_path_for_signal_topic(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path("nlp.signal.detected.v1") is not None

    @pytest.mark.unit
    def test_get_schema_path_returns_none_for_unknown_topic(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path("unknown.topic.v1") is None

    @pytest.mark.unit
    async def test_is_duplicate_no_client(self) -> None:
        consumer, _ = _make_consumer()
        assert await consumer.is_duplicate("any-id") is False

    # ── Valkey error resilience (T-A-1-03) ───────────────────────────────────

    @pytest.mark.unit
    async def test_is_duplicate_valkey_error_returns_false(self) -> None:
        """When Valkey raises, is_duplicate returns False without propagating."""
        mock_dedup = AsyncMock()
        mock_dedup.exists = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer, _ = _make_consumer()
        consumer._dedup_client = mock_dedup

        with capture_logs() as cap:
            result = await consumer.is_duplicate("evt-err-001")

        assert result is False
        assert any(
            e.get("event") == "intelligence_consumer.valkey_check_failed" for e in cap
        ), f"Expected warning log not found in {cap}"

    @pytest.mark.unit
    async def test_mark_processed_valkey_error_logs_warning(self) -> None:
        """When Valkey raises on set, mark_processed logs warning and returns silently."""
        mock_dedup = AsyncMock()
        mock_dedup.set = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer, _ = _make_consumer()
        consumer._dedup_client = mock_dedup

        with capture_logs() as cap:
            await consumer.mark_processed("evt-err-002")  # must not raise

        assert any(
            e.get("event") == "intelligence_consumer.valkey_mark_failed" for e in cap
        ), f"Expected warning log not found in {cap}"

    # ── Topic whitelist (T-A-1-04) ────────────────────────────────────────────

    @pytest.mark.unit
    def test_resolve_topic_from_header_known(self) -> None:
        """Known X-Source-Topic header returns header value without warning."""
        headers = {"X-Source-Topic": "nlp.signal.detected.v1"}
        with capture_logs() as cap:
            result = IntelligenceConsumer._resolve_topic({}, headers)
        assert result == "nlp.signal.detected.v1"
        assert not any("unknown_topic_from_header" in e.get("event", "") for e in cap)

    @pytest.mark.unit
    def test_resolve_topic_from_header_unknown_logs_warning(self) -> None:
        """Unknown X-Source-Topic header logs a warning and falls through to event_type resolution.

        Unknown headers are NOT returned as-is to prevent arbitrary strings being stored
        in the alerts.source_topic column (F-057).
        """
        headers = {"X-Source-Topic": "some.unknown.topic.v9"}
        with capture_logs() as cap:
            result = IntelligenceConsumer._resolve_topic({"event_type": "nlp.signal.detected"}, headers)
        # Falls through to event_type resolution — returns the canonical topic, not the header
        assert result == "nlp.signal.detected.v1"
        assert any(
            e.get("event") == "intelligence_consumer.unknown_topic_from_header" for e in cap
        ), f"Expected warning not found in {cap}"

    @pytest.mark.unit
    def test_resolve_topic_fallback_signal(self) -> None:
        value = {"event_type": "nlp.signal.detected"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "nlp.signal.detected.v1"

    @pytest.mark.unit
    def test_resolve_topic_fallback_graph(self) -> None:
        value = {"event_type": "graph.state.changed"}
        assert IntelligenceConsumer._resolve_topic(value, {}) == "graph.state.changed.v1"

    @pytest.mark.unit
    def test_resolve_topic_unknown_logs_warning(self) -> None:
        """Fully unresolvable event_type logs a warning and returns event_type as-is."""
        value = {"event_type": "totally.unknown.event", "event_id": "abc"}
        with capture_logs() as cap:
            result = IntelligenceConsumer._resolve_topic(value, {})
        assert result == "totally.unknown.event"
        assert any(
            e.get("event") == "intelligence_consumer.unresolvable_topic" for e in cap
        ), f"Expected warning not found in {cap}"


# ── market_impact_score extraction (PRD-0021 Wave A-3) ───────────────────────


class TestIntelligenceConsumerMarketImpactScore:
    @pytest.mark.unit
    async def test_consumer_passes_market_impact_score_to_fanout(self) -> None:
        """process_message() passes market_impact_score=0.9 from event to fanout."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "market_impact_score": 0.9,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert "market_impact_score" in call_kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(0.9)

    @pytest.mark.unit
    async def test_consumer_defaults_score_to_zero_if_absent(self) -> None:
        """Event without market_impact_score → 0.0 passed to fanout."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            # No market_impact_score key
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(0.0)

    @pytest.mark.unit
    async def test_consumer_clamps_score_above_1(self) -> None:
        """market_impact_score=2.0 → clamped to 1.0 before passing to fanout."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "market_impact_score": 2.0,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(1.0)

    @pytest.mark.unit
    async def test_consumer_clamps_score_below_0(self) -> None:
        """market_impact_score=-0.5 → clamped to 0.0 before passing to fanout."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "market_impact_score": -0.5,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(0.0)

    @pytest.mark.unit
    async def test_consumer_handles_none_score(self) -> None:
        """market_impact_score=None in event → defaults to 0.0 (TypeError guard, BP-138)."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "market_impact_score": None,
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(0.0)

    @pytest.mark.unit
    async def test_consumer_handles_non_numeric_score(self) -> None:
        """market_impact_score='N/A' → defaults to 0.0 (ValueError guard, BP-138)."""
        consumer, mock_fanout = _make_consumer()
        value = {
            "event_id": str(uuid4()),
            "event_type": "nlp.signal.detected",
            "subject_entity_id": str(uuid4()),
            "is_backfill": False,
            "market_impact_score": "N/A",
        }

        await consumer.process_message(None, value, {})

        call_kwargs = mock_fanout.execute.call_args.kwargs
        assert call_kwargs["market_impact_score"] == pytest.approx(0.0)


class TestAvroDeserialization:
    """PLAN-0062 Wave C: Confluent-Avro on the wire for intelligence.contradiction.v1."""

    @pytest.mark.unit
    def test_get_schema_path_returns_path_for_known_topics(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path("intelligence.contradiction.v1") is not None
        assert consumer.get_schema_path("nlp.signal.detected.v1") is not None
        assert consumer.get_schema_path("graph.state.changed.v1") is not None
        assert consumer.get_schema_path("unknown.topic.v1") is None

    @pytest.mark.unit
    def test_decodes_confluent_avro_contradiction(self) -> None:
        from messaging.kafka.serialization_utils import serialize_confluent_avro

        consumer, _ = _make_consumer()
        schema_path = consumer.get_schema_path("intelligence.contradiction.v1")
        assert schema_path is not None
        record = {
            "event_id": "01900000-0000-7000-0000-000000000030",
            "event_type": "intelligence.contradiction",
            "schema_version": 1,
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "subject_entity_id": "01234567-89ab-7def-8012-345678901234",
            "claim_type": "analyst_rating",
            "new_claim_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
            "contradicting_claim_id": "01234567-89ab-7def-8012-bbbbbbbbbbbb",
            "contradiction_strength": 0.7,
            "affected_relation_ids": [],
            "is_backfill": False,
            "correlation_id": None,
        }
        wire_bytes = serialize_confluent_avro(schema_path, record)
        decoded = consumer.deserialize_value(wire_bytes, schema_path=schema_path)
        assert decoded["subject_entity_id"] == record["subject_entity_id"]
        assert decoded["claim_type"] == "analyst_rating"
        assert decoded["contradiction_strength"] == pytest.approx(0.7)

    @pytest.mark.unit
    def test_falls_back_to_json_for_legacy_payload(self) -> None:
        import json

        from structlog.testing import capture_logs

        consumer, _ = _make_consumer()
        schema_path = consumer.get_schema_path("intelligence.contradiction.v1")
        legacy = json.dumps({"event_id": "x", "event_type": "intelligence.contradiction"}).encode()
        # PLAN-0062 F-021: every JSON-fallback hit must emit a structured warning.
        with capture_logs() as logs:
            decoded = consumer.deserialize_value(legacy, schema_path=schema_path)
        assert decoded["event_type"] == "intelligence.contradiction"
        warnings = [le for le in logs if le.get("event") == "intelligence_consumer.legacy_json_payload"]
        assert warnings, "expected intelligence_consumer.legacy_json_payload warning"

    # ── PLAN-0062 F-018: oversized JSON-fallback payload ─────────────────

    @pytest.mark.unit
    def test_json_fallback_oversized_payload_raises_malformed_data_error(self) -> None:
        """A JSON-fallback payload above the 16 MiB cap must raise
        :class:`MalformedDataError` BEFORE ``json.loads`` is called.
        """
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer, _ = _make_consumer()
        schema_path = consumer.get_schema_path("intelligence.contradiction.v1")
        payload = b'{"x":"' + b"a" * (17 * 1024 * 1024) + b'"}'
        with pytest.raises(MalformedDataError):
            consumer.deserialize_value(payload, schema_path=schema_path)

    # ── PLAN-0062 F-015: malformed Avro raises non-JSONDecodeError ────────

    @pytest.mark.unit
    def test_malformed_avro_raises(self) -> None:
        """Magic byte present + truncated body — must NOT route to JSON path."""
        consumer, _ = _make_consumer()
        schema_path = consumer.get_schema_path("intelligence.contradiction.v1")
        garbage = b"\x00\x00\x00\x00\x01\x42"
        with pytest.raises(Exception) as exc_info:
            consumer.deserialize_value(garbage, schema_path=schema_path)
        import json

        assert not isinstance(exc_info.value, json.JSONDecodeError)
