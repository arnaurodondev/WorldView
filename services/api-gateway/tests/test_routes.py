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


# ── Email preferences proxy ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_email_preferences_proxies_to_alert(client, mock_clients) -> None:
    """GET /v1/email/preferences proxies to S10 alert service."""
    prefs_resp = MagicMock(spec=httpx.Response)
    prefs_resp.status_code = 200
    prefs_resp.content = b'{"weekly_digest_enabled": true, "send_day_of_week": 6}'

    mock_clients.alert.get = AsyncMock(return_value=prefs_resp)

    response = await client.get("/v1/email/preferences")
    assert response.status_code == 200
    mock_clients.alert.get.assert_called_once()
    call_args = mock_clients.alert.get.call_args
    assert "/api/v1/email/preferences" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_email_preferences_forwards_auth_headers(client, mock_clients) -> None:
    """GET /v1/email/preferences passes X-Tenant-Id + X-User-Id from JWT."""
    prefs_resp = MagicMock(spec=httpx.Response)
    prefs_resp.status_code = 200
    prefs_resp.content = b"{}"

    mock_clients.alert.get = AsyncMock(return_value=prefs_resp)

    # Inject fake JWT payload into request state via the app
    from unittest.mock import patch

    with patch("api_gateway.routes.proxy._auth_headers", return_value={"X-Tenant-Id": "t1", "X-User-Id": "u1"}):
        response = await client.get("/v1/email/preferences")

    assert response.status_code == 200
    call_kwargs = mock_clients.alert.get.call_args[1]
    passed_headers = call_kwargs.get("headers", {})
    assert passed_headers.get("X-Tenant-Id") == "t1"
    assert passed_headers.get("X-User-Id") == "u1"


@pytest.mark.asyncio
async def test_put_email_preferences_proxies_to_alert(client, mock_clients) -> None:
    """PUT /v1/email/preferences proxies body to S10 alert service."""
    update_resp = MagicMock(spec=httpx.Response)
    update_resp.status_code = 200
    update_resp.content = b'{"weekly_digest_enabled": false}'

    mock_clients.alert.put = AsyncMock(return_value=update_resp)

    response = await client.put(
        "/v1/email/preferences",
        content=b'{"weekly_digest_enabled": false}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    mock_clients.alert.put.assert_called_once()


@pytest.mark.asyncio
async def test_put_email_preferences_propagates_s10_400(client, mock_clients) -> None:
    """S10 4xx responses pass through unchanged to the frontend."""
    err_resp = MagicMock(spec=httpx.Response)
    err_resp.status_code = 400
    err_resp.content = b'{"detail": "send_day_of_week must be 0-6"}'

    mock_clients.alert.put = AsyncMock(return_value=err_resp)

    response = await client.put(
        "/v1/email/preferences",
        content=b'{"send_day_of_week": 99}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
