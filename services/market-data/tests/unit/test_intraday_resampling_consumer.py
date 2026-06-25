"""Unit tests for IntradayResamplingConsumer (PLAN-0040 Wave B-3)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from market_data.infrastructure.messaging.consumers.intraday_resampling_consumer import (
    IntradayResamplingConsumer,
)

pytestmark = pytest.mark.unit


def _make_1m_jsonl(n: int = 3) -> bytes:
    """Build a JSONL payload with n 1-minute OHLCV bars."""
    bars = []
    for i in range(n):
        bar = {
            "symbol": "AAPL",
            "exchange": "US",
            "date": f"2024-06-01T09:{10 + i:02d}:00",
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 99.0 + i,
            "close": 102.0 + i,
            "volume": 50_000,
            "adjusted_close": 102.0 + i,
            "source": "alpaca",
        }
        bars.append(json.dumps(bar))
    return "\n".join(bars).encode()


def _make_message(
    *,
    dataset_type: str = "ohlcv",
    timeframe: str = "1m",
    instrument_id: str = "instr-001",
) -> dict:
    return {
        "event_id": "evt-resampling-001",
        "dataset_type": dataset_type,
        "timeframe": timeframe,
        "silver_ref_bucket": "market-silver",
        "silver_ref_key": "ohlcv/AAPL/2024/1m.jsonl",
        "instrument_id": instrument_id,
        "symbol": "AAPL",
        "exchange": "US",
        "provider": "alpaca",
    }


def _make_consumer(mock_uow: AsyncMock, mock_storage: AsyncMock) -> IntradayResamplingConsumer:
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    consumer = IntradayResamplingConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
    )
    consumer._current_uow = mock_uow
    return consumer


@pytest.mark.asyncio
async def test_worker_processes_1m_ohlcv_event() -> None:
    """Valid 1m OHLCV event → ResampledOHLCVUseCase.execute() called per bar."""
    mock_uow = AsyncMock()
    mock_uow.ohlcv.find_by_instrument_timeframe_datetime_range = AsyncMock(return_value=[])
    mock_uow.ohlcv.bulk_upsert_derived = AsyncMock()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(2))

    consumer = _make_consumer(mock_uow, mock_storage)
    msg = _make_message()

    with patch(
        "market_data.infrastructure.messaging.consumers.intraday_resampling_consumer.ResampledOHLCVUseCase"
    ) as mock_use_case_cls:
        mock_instance = AsyncMock()
        mock_instance.execute = AsyncMock(return_value=[])
        mock_instance.execute_batch = AsyncMock(return_value=[])
        mock_use_case_cls.return_value = mock_instance

        await consumer.process_message(key=None, value=msg, headers={})

        assert mock_instance.execute_batch.call_count == 1  # batched: one call for all bars


@pytest.mark.asyncio
async def test_worker_skips_non_1m_event() -> None:
    """Event with timeframe=1d → no storage download, no execute() call."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    msg = _make_message(timeframe="1d")
    await consumer.process_message(key=None, value=msg, headers={})

    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_worker_skips_non_ohlcv_event() -> None:
    """Event with dataset_type=fundamentals → no storage download."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    msg = _make_message(dataset_type="fundamentals")
    await consumer.process_message(key=None, value=msg, headers={})

    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_worker_skips_missing_silver_ref() -> None:
    """Event with no silver_ref → logs warning, no crash."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    msg = _make_message()
    msg.pop("silver_ref_bucket")
    msg.pop("silver_ref_key")
    # Also remove canonical_ref variants
    msg.pop("canonical_ref_bucket", None)
    msg.pop("canonical_ref_key", None)

    await consumer.process_message(key=None, value=msg, headers={})

    mock_storage.get_bytes.assert_not_called()


def test_worker_event_id_extracted() -> None:
    """extract_event_id() returns value['event_id']."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()
    consumer = _make_consumer(mock_uow, mock_storage)

    msg = _make_message()
    assert consumer.extract_event_id(msg) == "evt-resampling-001"


@pytest.mark.asyncio
async def test_worker_dedup_key_namespaced() -> None:
    """create_if_not_exists is called with '<event_id>:intraday_resampling' key.

    This prevents the ohlcv_consumer's bare event_id entries from causing false
    duplicate detection in the intraday resampling consumer (both consumers
    subscribe to market.dataset.fetched and share event IDs).
    """
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(1))
    consumer = _make_consumer(mock_uow, mock_storage)

    msg = _make_message()

    with patch(
        "market_data.infrastructure.messaging.consumers.intraday_resampling_consumer.ResampledOHLCVUseCase"
    ) as mock_use_case_cls:
        mock_instance = AsyncMock()
        mock_instance.execute = AsyncMock(return_value=[])
        mock_instance.execute_batch = AsyncMock(return_value=[])
        mock_use_case_cls.return_value = mock_instance
        await consumer.process_message(key=None, value=msg, headers={})

    expected_key = "evt-resampling-001:intraday_resampling"
    mock_uow.ingestion_events.create_if_not_exists.assert_called_once_with(expected_key, "intraday_resampling", None)


def test_worker_consumer_group_id() -> None:
    """Consumer group is market-data-intraday-resampling."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()
    consumer = IntradayResamplingConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
    )
    assert consumer._config.group_id == "market-data-intraday-resampling"


@pytest.mark.asyncio
async def test_worker_source_timeframe_5m_skips_1m_event() -> None:
    """Consumer configured with source_timeframe='5m' skips timeframe='1m' events."""
    mock_uow = AsyncMock()
    mock_storage = AsyncMock()
    consumer = IntradayResamplingConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
        source_timeframe="5m",
    )
    consumer._current_uow = mock_uow

    msg = _make_message(timeframe="1m")
    await consumer.process_message(key=None, value=msg, headers={})

    mock_storage.get_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_worker_source_timeframe_5m_processes_5m_event() -> None:
    """Consumer configured with source_timeframe='5m' processes timeframe='5m' events."""
    mock_uow = AsyncMock()
    mock_uow.ingestion_events.create_if_not_exists = AsyncMock(return_value=True)
    mock_uow.ohlcv.find_by_instrument_timeframe_datetime_range = AsyncMock(return_value=[])
    mock_uow.ohlcv.bulk_upsert_derived = AsyncMock()
    mock_storage = AsyncMock()
    mock_storage.get_bytes = AsyncMock(return_value=_make_1m_jsonl(1))

    consumer = IntradayResamplingConsumer(
        uow_factory=lambda: mock_uow,
        object_storage=mock_storage,
        source_timeframe="5m",
    )
    consumer._current_uow = mock_uow

    msg = _make_message(timeframe="5m")

    with patch(
        "market_data.infrastructure.messaging.consumers.intraday_resampling_consumer.ResampledOHLCVUseCase"
    ) as mock_use_case_cls:
        mock_instance = AsyncMock()
        mock_instance.execute = AsyncMock(return_value=[])
        mock_instance.execute_batch = AsyncMock(return_value=[])
        mock_use_case_cls.return_value = mock_instance

        await consumer.process_message(key=None, value=msg, headers={})

        assert mock_instance.execute_batch.call_count == 1  # batched: one call for all bars
