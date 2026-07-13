"""Unit tests for PredictionHistoryConsumer (PLAN-0056 Wave A3, T-A-3-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionMarketPrice
from market_data.infrastructure.messaging.consumers.prediction_history_consumer import (
    PredictionHistoryConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
_ISO = _NOW.isoformat()

_VALID_EVENT: dict = {
    "event_id": "01900000-0000-7000-8000-0000000000a1",
    "event_type": "market.prediction.history",
    "schema_version": 1,
    "occurred_at": _ISO,
    "market_id": "0xabc123",
    "token_id": "tok_yes",
    "outcome_name": "Yes",
    "interval": "1h",
    "window_start_ts": _ISO,
    "price": 0.72,
    "source": "polymarket_clob",
    "is_backfill": False,
    "correlation_id": None,
}


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.ingestion_events = MagicMock()
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.prediction_market_prices = MagicMock()
    uow.prediction_market_prices.insert_if_not_exists = AsyncMock(return_value=True)
    uow.commit = AsyncMock()
    uow.failed_tasks = MagicMock()
    uow.failed_tasks.create = AsyncMock()
    return uow


def _make_consumer(uow: MagicMock) -> PredictionHistoryConsumer:
    consumer = PredictionHistoryConsumer(
        uow_factory=lambda: uow,
        config=ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            topics=["market.prediction.history.v1"],
        ),
    )
    consumer._current_uow = uow
    return consumer


class TestProcessMessageInsertPrice:
    """Valid event → prediction_market_prices insert with mapped entity."""

    @pytest.mark.asyncio
    async def test_inserts_price_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_prices.insert_if_not_exists.assert_called_once()
        price: PredictionMarketPrice = uow.prediction_market_prices.insert_if_not_exists.call_args[0][0]
        assert isinstance(price, PredictionMarketPrice)
        assert price.market_id == "0xabc123"
        assert price.token_id == "tok_yes"  # noqa: S105 — test fixture, not a secret
        assert price.interval == "1h"
        assert price.outcome_name == "Yes"
        assert price.price == Decimal("0.72")
        assert price.source == "polymarket_clob"
        assert price.is_backfill is False
        assert price.window_start_ts == _NOW

    @pytest.mark.asyncio
    async def test_commit_not_called_in_process_message(self) -> None:
        """M-04: base class owns the commit; process_message must not commit."""
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.commit.assert_not_called()


class TestProcessMessageIdempotent:
    @pytest.mark.asyncio
    async def test_replay_duplicate_skipped(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(side_effect=[True, False])
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})
        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        assert uow.prediction_market_prices.insert_if_not_exists.call_count == 1
        assert uow.commit.call_count == 0

    @pytest.mark.asyncio
    async def test_duplicate_event_skips_all_writes(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_prices.insert_if_not_exists.assert_not_called()


class TestProcessMessageMalformed:
    @pytest.mark.asyncio
    async def test_missing_event_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="event_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "event_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_missing_token_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="token_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "token_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_invalid_window_start_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        bad = {**_VALID_EVENT, "window_start_ts": "not-a-date"}
        with pytest.raises(MalformedDataError, match="window_start_ts"):
            await consumer.process_message(key=None, value=bad, headers={})


class TestDeserializeValueJsonFallback:
    def test_json_fallback_when_no_schema(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        import json

        raw = json.dumps(_VALID_EVENT).encode()
        assert consumer.deserialize_value(raw, schema_path=None)["market_id"] == "0xabc123"
