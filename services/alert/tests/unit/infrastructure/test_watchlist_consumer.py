"""Unit tests for WatchlistConsumer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alert.infrastructure.consumer.watchlist_consumer import WatchlistConsumer

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]


def _make_consumer(
    dedup_client: MagicMock | None = None,
) -> tuple[WatchlistConsumer, AsyncMock]:
    mock_cache = AsyncMock()
    mock_cache.invalidate = AsyncMock()
    config = ConsumerConfig(
        group_id="alert-service-watchlist-group",
        topics=["portfolio.watchlist.updated.v1"],
    )
    consumer = WatchlistConsumer(config, mock_cache, dedup_client=dedup_client)
    return consumer, mock_cache


class TestWatchlistConsumer:
    @pytest.mark.unit
    async def test_item_added_is_noop(self) -> None:
        consumer, mock_cache = _make_consumer()
        event = {
            "event_id": str(uuid4()),
            "event_type": "watchlist.item_added",
            "entity_id": str(uuid4()),
            "entity_ids_affected": [],
        }

        await consumer.process_message(None, event, {})

        mock_cache.invalidate.assert_not_called()

    @pytest.mark.unit
    async def test_item_deleted_invalidates_entity_id(self) -> None:
        consumer, mock_cache = _make_consumer()
        entity_id = str(uuid4())
        event = {
            "event_id": str(uuid4()),
            "event_type": "watchlist.item_deleted",
            "entity_id": entity_id,
            "entity_ids_affected": [],
        }

        await consumer.process_message(None, event, {})

        mock_cache.invalidate.assert_awaited_once_with(entity_id)

    @pytest.mark.unit
    async def test_item_deleted_invalidates_all_affected_entities(self) -> None:
        consumer, mock_cache = _make_consumer()
        entity_id = str(uuid4())
        extra1, extra2 = str(uuid4()), str(uuid4())
        event = {
            "event_id": str(uuid4()),
            "event_type": "watchlist.item_deleted",
            "entity_id": entity_id,
            "entity_ids_affected": [extra1, extra2],
        }

        await consumer.process_message(None, event, {})

        assert mock_cache.invalidate.await_count == 3

    @pytest.mark.unit
    async def test_item_deleted_deduplicates_entity_ids(self) -> None:
        """entity_id present in both entity_id and entity_ids_affected → invalidated once."""
        consumer, mock_cache = _make_consumer()
        entity_id = str(uuid4())
        event = {
            "event_id": str(uuid4()),
            "event_type": "watchlist.item_deleted",
            "entity_id": entity_id,
            "entity_ids_affected": [entity_id],  # duplicate
        }

        await consumer.process_message(None, event, {})

        mock_cache.invalidate.assert_awaited_once_with(entity_id)

    @pytest.mark.unit
    def test_deserialize_value_json(self) -> None:
        consumer, _ = _make_consumer()
        raw = b'{"event_id": "abc", "event_type": "watchlist.item_added"}'
        result = consumer.deserialize_value(raw)
        assert result["event_id"] == "abc"

    @pytest.mark.unit
    def test_extract_event_id(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.extract_event_id({"event_id": "xyz"}) == "xyz"

    @pytest.mark.unit
    def test_get_schema_path_returns_none(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.get_schema_path("any.topic") is None

    @pytest.mark.unit
    async def test_is_duplicate_returns_false_without_dedup_client(self) -> None:
        consumer, _ = _make_consumer(dedup_client=None)
        result = await consumer.is_duplicate("any-id")
        assert result is False

    @pytest.mark.unit
    async def test_mark_processed_is_noop_without_dedup_client(self) -> None:
        consumer, _ = _make_consumer(dedup_client=None)
        # Should not raise
        await consumer.mark_processed("any-id")
