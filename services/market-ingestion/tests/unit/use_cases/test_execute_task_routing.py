"""Unit tests for provider routing logic in ExecuteTaskUseCase.

Covers:
- OHLCV 1d/1w routes to Yahoo Finance when registered
- OHLCV 1h stays with EODHD (intraday not supported by Yahoo)
- NEWS_SENTIMENT routes to Finnhub when registered
- NEWS falls back to EODHD when Finnhub not registered
- FUNDAMENTALS always uses EODHD
- provider_routing_override event emitted on override
- Quota check skipped for Yahoo
- Quota check skipped for Finnhub
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.application.use_cases.execute_task import (
    ExecuteTaskUseCase,
    _preferred_provider,
)
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(*providers: Provider) -> ProviderRegistry:
    """Build a ProviderRegistry with mock adapters for the given providers."""
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
    task.id = "task-routing-01"
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


# ===========================================================================
# _preferred_provider() unit tests
# ===========================================================================


@pytest.mark.unit()
def test_ohlcv_1d_routes_to_yahoo_when_registered() -> None:
    """OHLCV daily routes to Yahoo Finance when the adapter is registered."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    result = _preferred_provider(DatasetType.OHLCV, "1d", registry)
    assert result == Provider.YAHOO_FINANCE


@pytest.mark.unit()
def test_ohlcv_1h_stays_eodhd() -> None:
    """OHLCV intraday (1h) stays with EODHD — Yahoo only supports daily."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    result = _preferred_provider(DatasetType.OHLCV, "1h", registry)
    assert result == Provider.EODHD


@pytest.mark.unit()
def test_news_routes_to_finnhub_when_registered() -> None:
    """NEWS_SENTIMENT routes to Finnhub when registered."""
    registry = _make_registry(Provider.EODHD, Provider.FINNHUB)
    result = _preferred_provider(DatasetType.NEWS_SENTIMENT, None, registry)
    assert result == Provider.FINNHUB


@pytest.mark.unit()
def test_news_falls_back_to_eodhd_when_no_finnhub() -> None:
    """NEWS_SENTIMENT falls back to EODHD when Finnhub is not registered."""
    registry = _make_registry(Provider.EODHD)
    result = _preferred_provider(DatasetType.NEWS_SENTIMENT, None, registry)
    assert result == Provider.EODHD


@pytest.mark.unit()
def test_fundamentals_always_eodhd() -> None:
    """FUNDAMENTALS always uses EODHD regardless of other registered providers."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE, Provider.FINNHUB)
    result = _preferred_provider(DatasetType.FUNDAMENTALS, None, registry)
    assert result == Provider.EODHD


# ===========================================================================
# ExecuteTaskUseCase integration — routing override logging
# ===========================================================================


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_routing_override_logged() -> None:
    """provider_routing_override event is emitted when adapter is changed."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    uow = _make_uow()
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.put = AsyncMock(return_value=MagicMock(sha256="abc", byte_length=10, mime_type="application/x-ndjson"))
    serializer = MagicMock()
    serializer.serialize_ohlcv = MagicMock(return_value=b'{"test":1}\n')

    use_case = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
    )
    task = _make_task(DatasetType.OHLCV, "1d", Provider.EODHD)

    # Mock the Yahoo adapter's fetch_ohlcv
    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(
        return_value=MagicMock(
            provider=Provider.YAHOO_FINANCE,
            dataset_type=DatasetType.OHLCV,
            raw_data=b'[{"open":1}]',
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=1,
        ),
    )

    with patch("market_ingestion.application.use_cases.execute_task.logger") as mock_logger:
        mock_logger.bind = MagicMock(return_value=mock_logger)
        mock_logger.info = MagicMock()
        mock_logger.debug = MagicMock()
        await use_case.execute(task)
        # Check that provider_routing_override was logged
        override_calls = [
            c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "provider_routing_override"
        ]
        assert len(override_calls) == 1
        kwargs = override_calls[0].kwargs
        assert kwargs["selected"] == "yahoo_finance"


# ===========================================================================
# Quota/CB bypass tests
# ===========================================================================


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_quota_check_skipped_for_yahoo() -> None:
    """When Yahoo is selected, quota service try_consume() is NOT called."""
    registry = _make_registry(Provider.EODHD, Provider.YAHOO_FINANCE)
    uow = _make_uow()
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.put = AsyncMock(return_value=MagicMock(sha256="abc", byte_length=10, mime_type="application/x-ndjson"))
    serializer = MagicMock()
    serializer.serialize_ohlcv = MagicMock(return_value=b'{"test":1}\n')
    quota_service = MagicMock()
    quota_service.try_consume = AsyncMock()

    use_case = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        quota_service=quota_service,
    )
    task = _make_task(DatasetType.OHLCV, "1d", Provider.EODHD)

    yahoo_adapter = registry.get(Provider.YAHOO_FINANCE)
    yahoo_adapter.fetch_ohlcv = AsyncMock(
        return_value=MagicMock(
            provider=Provider.YAHOO_FINANCE,
            dataset_type=DatasetType.OHLCV,
            raw_data=b'[{"open":1}]',
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=1,
        ),
    )

    await use_case.execute(task)
    quota_service.try_consume.assert_not_called()


@pytest.mark.unit()
@pytest.mark.asyncio()
async def test_quota_check_skipped_for_finnhub() -> None:
    """When Finnhub is selected, quota service try_consume() is NOT called."""
    registry = _make_registry(Provider.EODHD, Provider.FINNHUB)
    uow = _make_uow()
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.put = AsyncMock(return_value=MagicMock(sha256="abc", byte_length=10, mime_type="application/x-ndjson"))
    serializer = MagicMock()
    serializer.serialize_passthrough = MagicMock(return_value=b'{"test":1}\n')
    quota_service = MagicMock()
    quota_service.try_consume = AsyncMock()

    use_case = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        quota_service=quota_service,
    )
    task = _make_task(DatasetType.NEWS_SENTIMENT, None, Provider.EODHD)

    finnhub_adapter = registry.get(Provider.FINNHUB)
    finnhub_adapter.fetch_news_sentiment = AsyncMock(
        return_value=MagicMock(
            provider=Provider.FINNHUB,
            dataset_type=DatasetType.NEWS_SENTIMENT,
            raw_data=b'[{"headline":"test"}]',
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
            bars_returned=1,
        ),
    )

    await use_case.execute(task)
    quota_service.try_consume.assert_not_called()
