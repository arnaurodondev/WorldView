"""Unit tests for FundamentalsDescriptionConsumer (T-D-3-10) — Consumer 13D-5."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = str(uuid4())


def _make_consumer(*, current_hash: str | None = None):
    """Build a FundamentalsDescriptionConsumer with mocked dependencies."""
    from knowledge_graph.infrastructure.consumer.fundamentals_consumer import FundamentalsDescriptionConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-fundamentals-test",
        topics=["market.dataset.fetched"],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock()
    sf.return_value = session

    def_worker = AsyncMock()
    def_worker.refresh_for_entity = AsyncMock()

    storage = AsyncMock()

    # Patch _get_current_hash to avoid real DB
    consumer = FundamentalsDescriptionConsumer(
        config=config,
        session_factory=sf,
        definition_worker=def_worker,
        storage_client=storage,
    )
    consumer._get_current_hash = AsyncMock(return_value=current_hash)

    return consumer, def_worker, storage


class TestFundamentalsConsumerDescriptionChange:
    def test_changed_description_triggers_reembed(self) -> None:
        """New hash != stored hash -> refresh_for_entity() called."""
        consumer, def_worker, storage = _make_consumer(current_hash="old_hash_value")

        description = "Updated description about Apple Inc."
        storage.get_json = AsyncMock(return_value={"General": {"Description": description}})

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "object_key": "fundamentals/aapl.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_awaited_once()

    def test_unchanged_description_skips_reembed(self) -> None:
        """Same hash -> refresh_for_entity() NOT called."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import sha256_hex

        description = "Stable description, no change."
        current_hash = sha256_hex(description)

        consumer, def_worker, storage = _make_consumer(current_hash=current_hash)
        storage.get_json = AsyncMock(return_value={"General": {"Description": description}})

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "object_key": "fundamentals/aapl.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_non_fundamentals_event_skipped(self) -> None:
        """dataset_type != 'fundamentals' -> process_message returns early."""
        consumer, def_worker, storage = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "ohlcv",
            "instrument_id": _INSTRUMENT_ID,
            "object_key": "ohlcv/aapl.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        storage.get_json.assert_not_awaited()
        def_worker.refresh_for_entity.assert_not_awaited()

    def test_no_description_in_payload_skips_reembed(self) -> None:
        """Payload has no General.Description -> refresh_for_entity not called."""
        consumer, def_worker, storage = _make_consumer(current_hash=None)
        storage.get_json = AsyncMock(return_value={"General": {}})

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "object_key": "fundamentals/aapl.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_storage_error_does_not_raise(self) -> None:
        """Storage failure -> method returns cleanly, refresh_for_entity not called."""
        consumer, def_worker, storage = _make_consumer()
        storage.get_json = AsyncMock(side_effect=RuntimeError("minio down"))

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "instrument_id": _INSTRUMENT_ID,
            "object_key": "fundamentals/aapl.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_missing_instrument_id_skips(self) -> None:
        """Missing instrument_id -> returns early without any work."""
        consumer, def_worker, _storage = _make_consumer()

        msg = {
            "event_id": str(uuid4()),
            "dataset_type": "fundamentals",
            "object_key": "fundamentals/unknown.json",
        }

        asyncio.get_event_loop().run_until_complete(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()
