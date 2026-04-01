"""Unit tests for EnrichedArticleConsumer Valkey dedup hardening (T-A-1-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import EnrichedArticleConsumer
from structlog.testing import capture_logs

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]


def _make_consumer(*, dedup_client: object | None = None) -> EnrichedArticleConsumer:
    config = ConsumerConfig(
        group_id="kg-enriched-test",
        topics=["nlp.article.enriched.v1"],
    )
    consumer = EnrichedArticleConsumer(
        config=config,
        session_factory=MagicMock(),
        embedding_client=MagicMock(),
        direct_producer=MagicMock(),
        entity_dirtied_topic="entity.dirtied.v1",
        dedup_client=dedup_client,
    )
    return consumer


class TestEnrichedConsumerValkey:
    @pytest.mark.unit
    async def test_is_duplicate_none_client_returns_false(self) -> None:
        """Without dedup client, is_duplicate always returns False."""
        consumer = _make_consumer()
        assert await consumer.is_duplicate("any-id") is False

    @pytest.mark.unit
    async def test_is_duplicate_valkey_error_returns_false(self) -> None:
        """When Valkey raises, is_duplicate returns False without propagating."""
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer = _make_consumer(dedup_client=mock_client)

        with capture_logs() as cap:
            result = await consumer.is_duplicate("evt-001")

        assert result is False
        assert any(
            e.get("event") == "enriched_consumer.valkey_check_failed" for e in cap
        ), f"Expected warning log not found in {cap}"

    @pytest.mark.unit
    async def test_mark_processed_valkey_error_logs_warning(self) -> None:
        """When Valkey raises on set, mark_processed logs warning and returns silently."""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer = _make_consumer(dedup_client=mock_client)

        with capture_logs() as cap:
            # Must not raise
            await consumer.mark_processed("evt-002")

        assert any(
            e.get("event") == "enriched_consumer.valkey_mark_failed" for e in cap
        ), f"Expected warning log not found in {cap}"
