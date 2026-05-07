"""Integration tests: ValkeyDedupMixin contract for market-data consumers.

T-B-2-02 acceptance: each of the 3 market-data consumers inheriting
ValkeyDedupMixin must satisfy:
  - is_duplicate(event_id) returns False before mark_processed
  - is_duplicate(event_id) returns True after mark_processed
  - is_duplicate(event_id) returns False for a different event_id

These tests use an AsyncMock Valkey client so they run without a live Redis/
Valkey container.  A live-container variant is left as a future exercise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
    FundamentalsConsumer,
)
from market_data.infrastructure.messaging.consumers.intraday_resampling_consumer import (
    IntradayResamplingConsumer,
)
from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey_mock() -> AsyncMock:
    """Return a minimal Valkey AsyncMock that stores keys in a local dict.

    The mock is stateful: ``set`` records a key, ``exists`` checks it.
    This mirrors the real ValkeyDedupMixin contract without a live server.
    """
    store: dict[str, str] = {}

    mock = AsyncMock()

    async def _exists(key: str) -> int:
        return 1 if key in store else 0

    async def _set(key: str, value: str, ex: int | None = None) -> None:
        store[key] = value

    mock.exists = AsyncMock(side_effect=_exists)
    mock.set = AsyncMock(side_effect=_set)
    return mock


# ---------------------------------------------------------------------------
# OHLCVConsumer
# ---------------------------------------------------------------------------


class TestOHLCVConsumerDedupMixin:
    """ValkeyDedupMixin contract for OHLCVConsumer."""

    @pytest.fixture()
    def consumer(self) -> OHLCVConsumer:
        config = ConsumerConfig(group_id="market-data-ohlcv", topics=["market.dataset.fetched"])
        return OHLCVConsumer(
            uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
            object_storage=None,
            config=config,
            dedup_client=_make_valkey_mock(),
        )

    async def test_not_duplicate_before_mark(self, consumer: OHLCVConsumer) -> None:
        """is_duplicate returns False for an unseen event_id."""
        assert await consumer.is_duplicate("evt-ohlcv-001") is False

    async def test_duplicate_after_mark(self, consumer: OHLCVConsumer) -> None:
        """is_duplicate returns True after mark_processed."""
        event_id = "evt-ohlcv-002"
        await consumer.mark_processed(event_id)
        assert await consumer.is_duplicate(event_id) is True

    async def test_different_id_not_duplicate(self, consumer: OHLCVConsumer) -> None:
        """Marking one event_id does not affect a different one."""
        await consumer.mark_processed("evt-ohlcv-003")
        assert await consumer.is_duplicate("evt-ohlcv-004") is False


# ---------------------------------------------------------------------------
# FundamentalsConsumer
# ---------------------------------------------------------------------------


class TestFundamentalsConsumerDedupMixin:
    """ValkeyDedupMixin contract for FundamentalsConsumer."""

    @pytest.fixture()
    def consumer(self) -> FundamentalsConsumer:
        config = ConsumerConfig(group_id="market-data-fundamentals", topics=["market.dataset.fetched"])
        return FundamentalsConsumer(
            uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
            object_storage=None,
            config=config,
            dedup_client=_make_valkey_mock(),
        )

    async def test_not_duplicate_before_mark(self, consumer: FundamentalsConsumer) -> None:
        assert await consumer.is_duplicate("evt-fund-001") is False

    async def test_duplicate_after_mark(self, consumer: FundamentalsConsumer) -> None:
        event_id = "evt-fund-002"
        await consumer.mark_processed(event_id)
        assert await consumer.is_duplicate(event_id) is True

    async def test_different_id_not_duplicate(self, consumer: FundamentalsConsumer) -> None:
        await consumer.mark_processed("evt-fund-003")
        assert await consumer.is_duplicate("evt-fund-004") is False


# ---------------------------------------------------------------------------
# IntradayResamplingConsumer
# ---------------------------------------------------------------------------


class TestIntradayResamplingConsumerDedupMixin:
    """ValkeyDedupMixin contract for IntradayResamplingConsumer."""

    @pytest.fixture()
    def consumer(self) -> IntradayResamplingConsumer:
        config = ConsumerConfig(
            group_id="market-data-intraday-resampling",
            topics=["market.dataset.fetched"],
        )
        return IntradayResamplingConsumer(
            uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
            object_storage=None,
            config=config,
            dedup_client=_make_valkey_mock(),
        )

    async def test_not_duplicate_before_mark(self, consumer: IntradayResamplingConsumer) -> None:
        assert await consumer.is_duplicate("evt-intraday-001") is False

    async def test_duplicate_after_mark(self, consumer: IntradayResamplingConsumer) -> None:
        event_id = "evt-intraday-002"
        await consumer.mark_processed(event_id)
        assert await consumer.is_duplicate(event_id) is True

    async def test_different_id_not_duplicate(self, consumer: IntradayResamplingConsumer) -> None:
        await consumer.mark_processed("evt-intraday-003")
        assert await consumer.is_duplicate("evt-intraday-004") is False
