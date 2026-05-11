"""Unit tests for zero-bar failover logic in ExecuteTaskUseCase.

Covers:
- Zero-bar OHLCV increments streak via record_zero()
- Non-zero bars resets streak via reset()
- Failover fires at threshold 5
- Failover does not fire below threshold
- EODHD intraday has no fallback — logs warning
- _fallback_provider returns None for EODHD OHLCV intraday
- _fallback_provider returns EODHD for Yahoo daily
- _fallback_provider returns EODHD for Finnhub news
- zero_bar_tracker=None skips all logic
- FUNDAMENTALS dataset is not tracked
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.application.use_cases.execute_task import (
    ExecuteTaskUseCase,
    _fallback_provider,
)
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderAuthError, ProviderRateLimited
from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(*providers: Provider) -> ProviderRegistry:
    registry = ProviderRegistry()
    for p in providers:
        adapter = MagicMock()
        adapter.provider = p
        registry.register(adapter)
    return registry


def _make_uow() -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()
    uow.commit = AsyncMock()
    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(
        return_value=MagicMock(
            has_changed=MagicMock(return_value=True),
            current_bar_ts=None,
            advance_bar_ts=MagicMock(),
        )
    )
    uow.watermarks.get_for_update = AsyncMock(return_value=None)
    uow.watermarks.save = AsyncMock()
    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock()
    return uow


def _make_task(
    dataset_type: DatasetType = DatasetType.OHLCV,
    timeframe: str | None = "1d",
    provider: Provider = Provider.EODHD,
) -> MagicMock:
    task = MagicMock()
    task.id = "task-zb-01"
    task.provider = provider
    task.dataset_type = dataset_type
    task.symbol = "AAPL"
    task.exchange = "US"
    task.timeframe = timeframe
    task.variant = None
    task.range_start = None
    task.range_end = datetime.now(tz=UTC)
    task.created_at = datetime.now(tz=UTC)
    task.succeed = MagicMock()
    task.retry = MagicMock()
    task.fail = MagicMock()
    return task


def _make_fetch_result(bars_returned: int = 0) -> MagicMock:
    return MagicMock(
        provider=Provider.YAHOO_FINANCE,
        dataset_type=DatasetType.OHLCV,
        raw_data=b'[{"open":1}]',
        content_type="application/json",
        fetched_at=datetime.now(tz=UTC),
        duration_ms=10,
        bars_returned=bars_returned,
    )


def _make_zero_bar_tracker(streak_value: int = 1) -> MagicMock:
    tracker = MagicMock()
    tracker.record_zero = AsyncMock(return_value=streak_value)
    tracker.reset = AsyncMock()
    tracker.should_failover = MagicMock(side_effect=lambda s: s >= 5)
    tracker.FAILOVER_THRESHOLD = 5
    return tracker


def _build_use_case(
    registry: ProviderRegistry,
    zero_bar_tracker: MagicMock | None = None,
) -> tuple[ExecuteTaskUseCase, MagicMock]:
    uow = _make_uow()
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.put = AsyncMock(return_value=MagicMock(sha256="abc", byte_length=10, mime_type="application/x-ndjson"))
    serializer = MagicMock()
    serializer.serialize_ohlcv = MagicMock(return_value=b'{"test":1}\n')
    serializer.serialize_passthrough = MagicMock(return_value=b'{"test":1}\n')

    use_case = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        zero_bar_tracker=zero_bar_tracker,
    )
    return use_case, uow


# ===========================================================================
# _fallback_provider() unit tests
# ===========================================================================


@pytest.mark.unit()
def test_fallback_returns_none_for_eodhd_ohlcv_intraday() -> None:
    """EODHD OHLCV intraday has no fallback — returns None."""
    registry = _make_registry(Provider.EODHD)
    result = _fallback_provider(DatasetType.OHLCV, "1m", Provider.EODHD, registry)
    assert result is None


@pytest.mark.unit()
def test_fallback_returns_eodhd_for_yahoo_daily() -> None:
    """Yahoo OHLCV daily falls back to EODHD."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    result = _fallback_provider(DatasetType.OHLCV, "1d", Provider.YAHOO_FINANCE, registry)
    assert result == Provider.EODHD


@pytest.mark.unit()
def test_fallback_returns_eodhd_for_finnhub_news() -> None:
    """Finnhub NEWS_SENTIMENT falls back to EODHD."""
    registry = _make_registry(Provider.EODHD, Provider.FINNHUB)
    result = _fallback_provider(DatasetType.NEWS_SENTIMENT, None, Provider.FINNHUB, registry)
    assert result == Provider.EODHD


# ===========================================================================
# Zero-bar streak tracking
# ===========================================================================


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_zero_bar_ohlcv_increments_streak() -> None:
    """bars_returned=0 calls record_zero() on the tracker."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker(streak_value=1)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    await use_case.execute(task)

    tracker.record_zero.assert_called_once_with(
        provider="yahoo_finance",
        symbol="AAPL",
        timeframe="1d",
        dataset_type="ohlcv",
    )


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_nonzero_bar_resets_streak() -> None:
    """bars_returned=5 calls reset() on the tracker."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker()
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=5))

    await use_case.execute(task)

    tracker.reset.assert_called_once_with(
        provider="yahoo_finance",
        symbol="AAPL",
        timeframe="1d",
        dataset_type="ohlcv",
    )
    tracker.record_zero.assert_not_called()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_failover_fires_at_threshold_5() -> None:
    """Streak=5 triggers re-fetch with EODHD fallback adapter."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker(streak_value=5)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    eodhd_adapter = registry.get(Provider.EODHD)
    eodhd_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=10))

    await use_case.execute(task)

    # Yahoo was called first (zero bars), then EODHD fallback was called
    yahoo_adapter.fetch_ohlcv.assert_called_once()
    eodhd_adapter.fetch_ohlcv.assert_called_once()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_failover_does_not_fire_below_threshold() -> None:
    """Streak=4 does NOT trigger re-fetch."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker(streak_value=4)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    eodhd_adapter = registry.get(Provider.EODHD)

    await use_case.execute(task)

    yahoo_adapter.fetch_ohlcv.assert_called_once()
    eodhd_adapter.fetch_ohlcv.assert_not_called()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_eodhd_intraday_no_fallback_logs_warning() -> None:
    """EODHD OHLCV intraday zero bars at threshold logs no_fallback warning."""
    registry = _make_registry(Provider.EODHD)
    tracker = _make_zero_bar_tracker(streak_value=5)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1h", Provider.EODHD)

    eodhd_adapter = registry.get(Provider.EODHD)
    eodhd_adapter.fetch_ohlcv = AsyncMock(
        return_value=MagicMock(
            provider=Provider.EODHD,
            dataset_type=DatasetType.OHLCV,
            raw_data=b"[]",
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=0,
        )
    )
    # Need to mock fetch_intraday since 1h is intraday
    eodhd_adapter.fetch_intraday = AsyncMock(
        return_value=MagicMock(
            provider=Provider.EODHD,
            dataset_type=DatasetType.OHLCV,
            raw_data=b"[]",
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=0,
        )
    )

    with patch("market_ingestion.application.use_cases.execute_task.logger") as mock_logger:
        mock_logger.bind = MagicMock(return_value=mock_logger)
        mock_logger.info = MagicMock()
        mock_logger.debug = MagicMock()
        mock_logger.warning = MagicMock()
        await use_case.execute(task)

        no_fallback_calls = [
            c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "provider_zero_bar_no_fallback"
        ]
        assert len(no_fallback_calls) == 1


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_zero_bar_tracker_none_skips_logic() -> None:
    """zero_bar_tracker=None means no calls to record_zero or reset."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=None)
    task = _make_task(DatasetType.OHLCV, "1d")

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    # Should execute without errors — no zero-bar tracking
    await use_case.execute(task)


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fundamentals_not_tracked() -> None:
    """FUNDAMENTALS dataset is not tracked for zero bars."""
    registry = _make_registry(Provider.EODHD)
    tracker = _make_zero_bar_tracker()
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.FUNDAMENTALS, None, Provider.EODHD)

    eodhd_adapter = registry.get(Provider.EODHD)
    eodhd_adapter.fetch_fundamentals = AsyncMock(
        return_value=MagicMock(
            provider=Provider.EODHD,
            dataset_type=DatasetType.FUNDAMENTALS,
            raw_data=b'{"General":{}}',
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=1,
        )
    )

    await use_case.execute(task)

    tracker.record_zero.assert_not_called()
    tracker.reset.assert_not_called()


# ===========================================================================
# F-011f: Fallback fetch error paths
# ===========================================================================


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fallback_rate_limited_retries_task() -> None:
    """Fallback adapter raises ProviderRateLimited → task.retry() is called."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker(streak_value=5)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    # Primary (Yahoo) returns zero bars to trigger failover
    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    # Fallback (EODHD) raises rate-limited error
    eodhd_adapter = registry.get(Provider.EODHD)
    eodhd_adapter.fetch_ohlcv = AsyncMock(side_effect=ProviderRateLimited("EODHD rate limit hit", retry_after=60.0))

    with pytest.raises(ProviderRateLimited):
        await use_case.execute(task)

    # task.retry() should have been called (retryable error)
    task.retry.assert_called_once()
    # task.fail() should NOT have been called
    task.fail.assert_not_called()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_fallback_auth_error_fails_task() -> None:
    """Fallback adapter raises ProviderAuthError → task.fail() is called."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    tracker = _make_zero_bar_tracker(streak_value=5)
    use_case, _ = _build_use_case(registry, zero_bar_tracker=tracker)
    task = _make_task(DatasetType.OHLCV, "1d")

    # Primary (Yahoo) returns zero bars to trigger failover
    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(return_value=_make_fetch_result(bars_returned=0))

    # Fallback (EODHD) raises auth error (fatal)
    eodhd_adapter = registry.get(Provider.EODHD)
    eodhd_adapter.fetch_ohlcv = AsyncMock(side_effect=ProviderAuthError("EODHD API key invalid"))

    with pytest.raises(ProviderAuthError):
        await use_case.execute(task)

    # task.fail() should have been called (fatal error)
    task.fail.assert_called_once()
    # task.retry() should NOT have been called
    task.retry.assert_not_called()
