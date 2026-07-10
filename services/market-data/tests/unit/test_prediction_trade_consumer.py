"""Unit tests for PredictionTradeConsumer (PLAN-0056 Wave A3, T-A-3-03)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import PredictionMarketTrade
from market_data.infrastructure.messaging.consumers.prediction_trade_consumer import (
    PredictionTradeConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_TS = datetime(2026, 4, 9, 12, 30, 0, tzinfo=UTC)

_VALID_EVENT: dict = {
    "event_id": "01900000-0000-7000-8000-0000000000c3",
    "event_type": "market.prediction.trade",
    "schema_version": 1,
    "occurred_at": _TS.isoformat(),
    "market_id": "0xabc123",
    "trade_id": "trade_987",
    "token_id": "tok_yes",
    "price": 0.65,
    "size_usd": 250.5,
    "side": "buy",
    "ts": _TS.isoformat(),
    "correlation_id": None,
}


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.ingestion_events = MagicMock()
    uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    uow.prediction_market_trades = MagicMock()
    uow.prediction_market_trades.insert_if_not_exists = AsyncMock(return_value=True)
    uow.commit = AsyncMock()
    uow.failed_tasks = MagicMock()
    uow.failed_tasks.create = AsyncMock()
    return uow


def _make_consumer(uow: MagicMock) -> PredictionTradeConsumer:
    consumer = PredictionTradeConsumer(
        uow_factory=lambda: uow,
        config=ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            topics=["market.prediction.trade.v1"],
        ),
    )
    consumer._current_uow = uow
    return consumer


class TestProcessMessageInsertTrade:
    @pytest.mark.asyncio
    async def test_inserts_trade_on_valid_event(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_trades.insert_if_not_exists.assert_called_once()
        trade: PredictionMarketTrade = uow.prediction_market_trades.insert_if_not_exists.call_args[0][0]
        assert isinstance(trade, PredictionMarketTrade)
        assert trade.market_id == "0xabc123"
        assert trade.trade_id == "trade_987"
        assert trade.token_id == "tok_yes"  # noqa: S105 — test fixture, not a secret
        assert trade.price == Decimal("0.65")
        assert trade.size_usd == Decimal("250.5")
        assert trade.side == "buy"
        assert trade.ts == _TS

    @pytest.mark.asyncio
    async def test_null_size_maps_to_none(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value={**_VALID_EVENT, "size_usd": None}, headers={})

        trade: PredictionMarketTrade = uow.prediction_market_trades.insert_if_not_exists.call_args[0][0]
        assert trade.size_usd is None

    @pytest.mark.asyncio
    async def test_commit_not_called_in_process_message(self) -> None:
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

        assert uow.prediction_market_trades.insert_if_not_exists.call_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_event_skips_all_writes(self) -> None:
        uow = _make_uow()
        uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=False)
        consumer = _make_consumer(uow)

        await consumer.process_message(key=None, value=_VALID_EVENT, headers={})

        uow.prediction_market_trades.insert_if_not_exists.assert_not_called()


class TestProcessMessageMalformed:
    @pytest.mark.asyncio
    async def test_missing_trade_id_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="trade_id"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "trade_id": None}, headers={})

    @pytest.mark.asyncio
    async def test_missing_side_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="side"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "side": None}, headers={})

    @pytest.mark.asyncio
    async def test_invalid_ts_raises(self) -> None:
        uow = _make_uow()
        consumer = _make_consumer(uow)
        with pytest.raises(MalformedDataError, match="ts"):
            await consumer.process_message(key=None, value={**_VALID_EVENT, "ts": "not-a-date"}, headers={})
