"""Tests for QuotesConsumer's explicit no-op dedup contract (BP-035 pattern).

F-008: QuotesConsumer removed ValkeyDedupMixin from its MRO (PLAN-0084 D-011/DP-001
fix) and documents its own is_duplicate/mark_processed no-ops. These tests guard
the contract so a future refactor cannot accidentally re-introduce Valkey writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_quotes_consumer_is_duplicate_always_false() -> None:
    """is_duplicate must always return False — dedup handled by create_if_not_exists."""
    consumer = QuotesConsumer(
        uow_factory=MagicMock(),
        object_storage=None,
        valkey_client=None,
    )
    assert await consumer.is_duplicate("any-event-id") is False


@pytest.mark.asyncio
async def test_quotes_consumer_mark_processed_is_noop() -> None:
    """mark_processed must be a transparent no-op — no Valkey writes."""
    mock_valkey = MagicMock()
    mock_valkey.set = AsyncMock()
    consumer = QuotesConsumer(
        uow_factory=MagicMock(),
        object_storage=None,
        valkey_client=mock_valkey,
    )
    await consumer.mark_processed("any-event-id")
    mock_valkey.set.assert_not_awaited()


def test_quotes_consumer_dedup_prefix_is_class_attr() -> None:
    """_dedup_prefix must be a class attribute (not instance) for architecture enforcement."""
    assert hasattr(QuotesConsumer, "_dedup_prefix"), "_dedup_prefix must be a class attribute"
    assert isinstance(QuotesConsumer._dedup_prefix, str)
    assert QuotesConsumer._dedup_prefix.startswith("market-data:")


@pytest.mark.asyncio
async def test_quotes_consumer_is_duplicate_returns_false_with_valkey_client() -> None:
    """Even when a valkey_client is provided, is_duplicate must return False (no Valkey read)."""
    mock_valkey = MagicMock()
    mock_valkey.exists = AsyncMock(return_value=True)  # would indicate duplicate if checked
    consumer = QuotesConsumer(
        uow_factory=MagicMock(),
        object_storage=None,
        valkey_client=mock_valkey,
    )
    result = await consumer.is_duplicate("evt-with-valkey")
    assert result is False, "is_duplicate must return False regardless of Valkey state"
    mock_valkey.exists.assert_not_awaited()
