"""Unit tests for S3MarketDataClient.get_price_batch (PLAN-0113 T-1-06)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from alert.config import Settings
from alert.infrastructure.clients.s3_client import S3MarketDataClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        s3_market_data_base_url="http://s3:8003",
    )


@pytest.mark.asyncio
async def test_get_price_batch_parses_list_shape() -> None:
    iid1, iid2 = uuid4(), uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"instrument_id": str(iid1), "price": "201.50"},
        {"instrument_id": str(iid2), "price": "33.0"},
    ]
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    client = S3MarketDataClient(_settings(), client=mock_client)
    result = await client.get_price_batch([iid1, iid2])

    assert result == {iid1: 201.50, iid2: 33.0}


@pytest.mark.asyncio
async def test_get_price_batch_empty_input_no_call() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_price_batch([]) == {}
    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_get_price_batch_missing_instrument_omitted() -> None:
    """An instrument with no data is absent from the result (not an error)."""
    iid1, iid2 = uuid4(), uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"instrument_id": str(iid1), "price": "10.0"}]
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    client = S3MarketDataClient(_settings(), client=mock_client)
    result = await client.get_price_batch([iid1, iid2])
    assert result == {iid1: 10.0}


@pytest.mark.asyncio
async def test_get_price_batch_chunks_over_50_ids() -> None:
    ids = [uuid4() for _ in range(120)]
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    client = S3MarketDataClient(_settings(), client=mock_client)
    await client.get_price_batch(ids)
    # 120 ids → 3 chunks of ≤50.
    assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_get_price_batch_failure_is_best_effort() -> None:
    """A transport error contributes nothing rather than raising."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_price_batch([uuid4()]) == {}


# ── get_fundamental_metric (PLAN-0113 T-2-03) ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_fundamental_metric_returns_latest() -> None:
    """``data`` is ASC by date → the last non-null value_numeric is the latest."""
    iid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "instrument_id": str(iid),
        "metric": "pe_ratio",
        "data": [
            {"as_of_date": "2024-01-01", "value_numeric": 18.0},
            {"as_of_date": "2024-04-01", "value_numeric": 22.5},
        ],
    }
    mock_resp.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_fundamental_metric(iid, "pe_ratio") == 22.5


@pytest.mark.asyncio
async def test_get_fundamental_metric_skips_null_tail() -> None:
    """A null value_numeric at the tail is skipped for the latest non-null."""
    iid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"as_of_date": "2024-01-01", "value_numeric": 18.0},
            {"as_of_date": "2024-04-01", "value_numeric": None},
        ],
    }
    mock_resp.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_fundamental_metric(iid, "pe_ratio") == 18.0


@pytest.mark.asyncio
async def test_get_fundamental_metric_empty_returns_none() -> None:
    iid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_fundamental_metric(iid, "pe_ratio") is None


@pytest.mark.asyncio
async def test_get_fundamental_metric_failure_returns_none() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client = S3MarketDataClient(_settings(), client=mock_client)
    assert await client.get_fundamental_metric(uuid4(), "pe_ratio") is None
