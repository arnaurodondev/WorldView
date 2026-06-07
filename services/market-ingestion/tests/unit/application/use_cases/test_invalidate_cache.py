"""Unit tests for :class:`InvalidateCacheUseCase` (PLAN-0108 Wave E)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from market_ingestion.application.metrics.cache import provider_cache_invalidated_total
from market_ingestion.application.use_cases.invalidate_cache import InvalidateCacheUseCase
from market_ingestion.infrastructure.cache.cache_policy import DatasetType

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_execute_invokes_cache_and_increments_metric() -> None:
    """Execute calls cache.invalidate(dataset_type, symbol) and increments the
    audit Counter by the number of keys deleted.
    """
    # Capture the counter value before so the assertion is monotonic and does
    # not depend on global metric state set by other tests in this session.
    label = DatasetType.FUNDAMENTALS_SNAPSHOT.value
    before = provider_cache_invalidated_total.labels(dataset_type=label)._value.get()  # type: ignore[attr-defined]

    cache = AsyncMock()
    cache.invalidate = AsyncMock(return_value=3)

    use_case = InvalidateCacheUseCase(cache=cache)
    result = await use_case.execute(DatasetType.FUNDAMENTALS_SNAPSHOT, "AAPL")

    # Cache called exactly once with the right coordinate.
    cache.invalidate.assert_awaited_once_with(DatasetType.FUNDAMENTALS_SNAPSHOT, "AAPL")
    # Response envelope shape is the operator-visible contract.
    assert result == {
        "dataset_type": "fundamentals_snapshot",
        "symbol": "AAPL",
        "keys_deleted": 3,
    }
    # Counter incremented by the number of keys removed -- not by 1.
    after = provider_cache_invalidated_total.labels(dataset_type=label)._value.get()  # type: ignore[attr-defined]
    assert after - before == 3
