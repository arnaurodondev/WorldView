"""Unit tests for Kafka consumers (EnrichedArticleConsumer + EntityCreatedConsumer)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_enriched_message(
    *,
    doc_id: str | None = None,
    raw_relations: list | None = None,
    is_backfill: bool = False,
) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": "nlp.article.enriched",
        "schema_version": 1,
        "occurred_at": _NOW.isoformat(),
        "doc_id": doc_id or str(uuid4()),
        "source_type": "news",
        "is_backfill": is_backfill,
        "routing_tier": "DEEP",
        "routing_score": 0.85,
        "section_count": 5,
        "chunk_count": 12,
        "mention_count": 4,
        "resolved_entity_ids": [],
        "relation_count": len(raw_relations or []),
        "claim_count": 0,
        "event_count": 0,
        "provisional_entity_count": 0,
        "correlation_id": None,
        "raw_relations": raw_relations or [],
        "raw_events": [],
        "raw_claims": [],
    }


def _raw_relation_dict(
    subject_id: str | None = None,
    object_id: str | None = None,
) -> dict:
    return {
        "subject_entity_id": subject_id or str(uuid4()),
        "object_entity_id": object_id or str(uuid4()),
        "raw_type": "employs",
        "polarity": "positive",
        "extraction_confidence": 0.85,
        "source_trust_weight": 1.0,
        "evidence_date": _NOW.isoformat(),
        "is_backfill": False,
        "entity_provisional": False,
    }


class _MockEmbeddingClient:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _MockDirectProducer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None:
        self.calls.append({"topic": topic, "key": key, "value": value})


def _make_session_factory(session: AsyncMock | None = None) -> AsyncMock:
    """Build a mock session factory (async context manager)."""
    s = session or _make_mock_session()
    factory = MagicMock()
    # __call__ returns an async context manager that yields the session
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=s)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = cm
    return factory


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = (str(uuid4()),)
    result.rowcount = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# EnrichedArticleConsumer — orchestration
# ---------------------------------------------------------------------------


class TestEnrichedConsumerOrchestration:
    def _make_consumer(self, session: AsyncMock | None = None) -> object:
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
            EnrichedArticleConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="kg-test-group",
            topics=["nlp.article.enriched.v1"],
        )
        return EnrichedArticleConsumer(
            config=config,
            session_factory=_make_session_factory(session),
            embedding_client=_MockEmbeddingClient(),  # type: ignore[arg-type]
            direct_producer=_MockDirectProducer(),
            entity_dirtied_topic="entity.dirtied.v1",
        )

    def test_process_empty_message_completes_without_error(self) -> None:
        consumer = self._make_consumer()
        msg = _build_enriched_message()
        asyncio.run(
            consumer.process_message(None, msg, {})  # type: ignore[attr-defined]
        )

    def test_process_message_commits_session(self) -> None:
        session = _make_mock_session()
        consumer = self._make_consumer(session)
        msg = _build_enriched_message()
        asyncio.run(
            consumer.process_message(None, msg, {})  # type: ignore[attr-defined]
        )
        session.commit.assert_called_once()

    def test_blocks_called_in_order_for_relation(self) -> None:
        """Block 11 must run before Block 12a (canonicalization before materialization)."""
        call_order: list[str] = []

        async def mock_canonicalize(*args: object, **kwargs: object) -> object:
            call_order.append("block11")
            from knowledge_graph.application.blocks.canonicalization import (
                CanonicalizationResult,
            )

            return CanonicalizationResult(
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="STANDARD",
                decay_alpha=0.000950,
                base_confidence=0.70,
                step="exact",
            )

        async def mock_materialize(*args: object, **kwargs: object) -> object:
            call_order.append("block12a")
            from knowledge_graph.application.blocks.graph_write import MaterializationSummary

            return MaterializationSummary(
                relations_upserted=1,
                evidence_rows_inserted=1,
                events_inserted=0,
                claims_inserted=0,
                entities_dirtied=2,
            )

        consumer = self._make_consumer()
        rel = _raw_relation_dict()
        msg = _build_enriched_message(raw_relations=[rel])

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
                side_effect=mock_canonicalize,
            ),
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.materialize_graph",
                side_effect=mock_materialize,
            ),
        ):
            asyncio.run(
                consumer.process_message(None, msg, {})  # type: ignore[attr-defined]
            )

        assert call_order == ["block11", "block12a"]

    def test_deserialize_value_is_json(self) -> None:
        consumer = self._make_consumer()
        payload = {"event_id": "test", "doc_id": str(uuid4())}
        raw = json.dumps(payload).encode()
        result = consumer.deserialize_value(raw)  # type: ignore[attr-defined]
        assert result["event_id"] == "test"

    def test_extract_event_id(self) -> None:
        consumer = self._make_consumer()
        eid = str(uuid4())
        result = consumer.extract_event_id({"event_id": eid})  # type: ignore[attr-defined]
        assert result == eid


# ---------------------------------------------------------------------------
# EnrichedArticleConsumer — idempotency (no dedup_client → always False)
# ---------------------------------------------------------------------------


class TestEnrichedConsumerIdempotency:
    def _make_consumer(self) -> object:
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
            EnrichedArticleConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        return EnrichedArticleConsumer(
            config=ConsumerConfig(
                bootstrap_servers="localhost:9092",
                group_id="kg-test",
                topics=["nlp.article.enriched.v1"],
            ),
            session_factory=_make_session_factory(),
            embedding_client=_MockEmbeddingClient(),  # type: ignore[arg-type]
            direct_producer=_MockDirectProducer(),
            entity_dirtied_topic="entity.dirtied.v1",
            dedup_client=None,
        )

    def test_is_duplicate_returns_false_without_dedup(self) -> None:
        consumer = self._make_consumer()
        result = asyncio.run(
            consumer.is_duplicate(str(uuid4()))  # type: ignore[attr-defined]
        )
        assert result is False

    def test_mark_processed_noop_without_dedup(self) -> None:
        consumer = self._make_consumer()
        # Should not raise
        asyncio.run(
            consumer.mark_processed(str(uuid4()))  # type: ignore[attr-defined]
        )


# ---------------------------------------------------------------------------
# EntityCreatedConsumer
# ---------------------------------------------------------------------------


class TestEntityCreatedConsumer:
    def _make_consumer(self, session: AsyncMock | None = None) -> object:
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
            EntityCreatedConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        return EntityCreatedConsumer(
            config=ConsumerConfig(
                bootstrap_servers="localhost:9092",
                group_id="kg-entity-group",
                topics=["entity.canonical.created.v1"],
            ),
            session_factory=_make_session_factory(session),
        )

    def test_process_message_commits_session(self) -> None:
        session = _make_mock_session()
        consumer = self._make_consumer(session)
        msg = {
            "event_id": str(uuid4()),
            "entity_id": str(uuid4()),
            "canonical_name": "Apple Inc",
            "entity_type": "financial_instrument",
            "provisional_queue_id": str(uuid4()),
        }
        asyncio.run(
            consumer.process_message(None, msg, {})  # type: ignore[attr-defined]
        )
        session.commit.assert_called_once()

    def test_process_message_executes_update(self) -> None:
        session = _make_mock_session()
        consumer = self._make_consumer(session)
        msg = {
            "event_id": str(uuid4()),
            "entity_id": str(uuid4()),
            "canonical_name": "Apple Inc",
            "entity_type": "financial_instrument",
            "provisional_queue_id": str(uuid4()),
        }
        asyncio.run(
            consumer.process_message(None, msg, {})  # type: ignore[attr-defined]
        )
        # UPDATE relation_evidence_raw must have been called
        session.execute.assert_called()
        sqls = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("entity_provisional" in s for s in sqls)

    def test_deserialize_is_json(self) -> None:
        consumer = self._make_consumer()
        payload = {"event_id": "x"}
        result = consumer.deserialize_value(json.dumps(payload).encode())  # type: ignore[attr-defined]
        assert result == payload


# ---------------------------------------------------------------------------
# EntityCreatedConsumer — dedup resilience (P-4 regression)
# ---------------------------------------------------------------------------


class TestEntityCreatedConsumerDedupResilience:
    def _make_consumer_with_dedup(self, dedup_client: object) -> object:
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
            EntityCreatedConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        return EntityCreatedConsumer(
            config=ConsumerConfig(
                bootstrap_servers="localhost:9092",
                group_id="kg-entity-group",
                topics=["entity.canonical.created.v1"],
            ),
            session_factory=_make_session_factory(),
            dedup_client=dedup_client,
        )

    def test_entity_consumer_dedup_check_failure_returns_false(self) -> None:
        """is_duplicate() returns False (not crash) when Valkey is down (P-4)."""
        dedup_client = AsyncMock()
        dedup_client.exists = AsyncMock(side_effect=ConnectionError("valkey down"))

        consumer = self._make_consumer_with_dedup(dedup_client)

        result = asyncio.run(
            consumer.is_duplicate("event-1")  # type: ignore[attr-defined]
        )
        assert result is False

    def test_entity_consumer_dedup_check_failure_logs_warning(self) -> None:
        """is_duplicate() emits entity_consumer_dedup_check_failed warning on error (P-4)."""
        dedup_client = AsyncMock()
        dedup_client.exists = AsyncMock(side_effect=ConnectionError("valkey down"))

        consumer = self._make_consumer_with_dedup(dedup_client)

        with patch("knowledge_graph.infrastructure.messaging.consumers.entity_consumer.logger") as mock_logger:
            asyncio.run(
                consumer.is_duplicate("event-1")  # type: ignore[attr-defined]
            )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args.args[0] == "entity_consumer_dedup_check_failed"
        assert call_args.kwargs.get("event_id") == "event-1"

    def test_entity_consumer_dedup_mark_failure_does_not_crash(self) -> None:
        """mark_processed() does not raise when Valkey is down (P-4)."""
        dedup_client = AsyncMock()
        dedup_client.set = AsyncMock(side_effect=ConnectionError("valkey down"))

        consumer = self._make_consumer_with_dedup(dedup_client)

        # Should not raise
        asyncio.run(
            consumer.mark_processed("event-1")  # type: ignore[attr-defined]
        )

    def test_entity_consumer_dedup_mark_failure_logs_warning(self) -> None:
        """mark_processed() emits entity_consumer_dedup_mark_failed warning on error (P-4)."""
        dedup_client = AsyncMock()
        dedup_client.set = AsyncMock(side_effect=ConnectionError("valkey down"))

        consumer = self._make_consumer_with_dedup(dedup_client)

        with patch("knowledge_graph.infrastructure.messaging.consumers.entity_consumer.logger") as mock_logger:
            asyncio.run(
                consumer.mark_processed("event-1")  # type: ignore[attr-defined]
            )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args.args[0] == "entity_consumer_dedup_mark_failed"
        assert call_args.kwargs.get("event_id") == "event-1"
