"""Tests for composed gateway endpoints with mocked downstream services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_company_overview_composes_responses(client, mock_clients) -> None:
    """GET /v1/companies/:id/overview merges market-data + content-store."""
    # Mock market-data fundamentals
    fund_resp = MagicMock(spec=httpx.Response)
    fund_resp.status_code = 200
    fund_resp.json.return_value = {"pe_ratio": 25.0}

    # Mock market-data OHLCV
    ohlcv_resp = MagicMock(spec=httpx.Response)
    ohlcv_resp.status_code = 200
    ohlcv_resp.json.return_value = {"bars": []}

    # Mock content-store articles
    news_resp = MagicMock(spec=httpx.Response)
    news_resp.status_code = 200
    news_resp.json.return_value = {"articles": []}

    mock_clients.market_data.get = AsyncMock(side_effect=[fund_resp, ohlcv_resp])
    mock_clients.content_store.get = AsyncMock(return_value=news_resp)

    response = await client.get("/v1/companies/AAPL/overview")
    assert response.status_code == 200

    body = response.json()
    assert body["company_id"] == "AAPL"
    assert "fundamentals" in body
    assert "ohlcv" in body
    assert "latest_news" in body


@pytest.mark.asyncio
async def test_company_overview_propagates_downstream_error(client, mock_clients) -> None:
    """Downstream 404 should propagate through the gateway."""
    err_resp = MagicMock(spec=httpx.Response)
    err_resp.status_code = 404
    err_resp.text = "Instrument not found"

    mock_clients.market_data.get = AsyncMock(return_value=err_resp)

    response = await client.get("/v1/companies/UNKNOWN/overview")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_map_layers_returns_static(client) -> None:
    """GET /v1/map/layers returns layer definitions."""
    response = await client.get("/v1/map/layers")
    assert response.status_code == 200
    body = response.json()
    assert "layers" in body
    assert len(body["layers"]) >= 1
