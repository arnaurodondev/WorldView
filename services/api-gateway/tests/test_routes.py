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


# ── Screener + timeseries proxy (PRD-0017 Wave C-1) ───────────────────────────


@pytest.mark.asyncio
async def test_screen_instruments_proxies_to_market_data(client, mock_clients) -> None:
    """POST /v1/fundamentals/screen proxies body to S3 market-data."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"results": [], "count": 0, "total": 0}'

    mock_clients.market_data.post = AsyncMock(return_value=downstream_resp)

    response = await client.post(
        "/v1/fundamentals/screen",
        content=b'{"filters": [{"metric": "pe_ratio", "op": "lt", "value": 20}]}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    mock_clients.market_data.post.assert_called_once()
    call_args = mock_clients.market_data.post.call_args[0]
    assert "/api/v1/fundamentals/screen" in call_args[0]


@pytest.mark.asyncio
async def test_screen_instruments_propagates_s3_422(client, mock_clients) -> None:
    """S3 422 (invalid filter) is propagated unchanged to the frontend."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 422
    downstream_resp.content = b'{"detail": "unknown metric"}'

    mock_clients.market_data.post = AsyncMock(return_value=downstream_resp)

    response = await client.post(
        "/v1/fundamentals/screen",
        content=b'{"filters": [{"metric": "bogus", "op": "lt", "value": 1}]}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_screen_fields_proxies_to_market_data(client, mock_clients) -> None:
    """GET /v1/fundamentals/screen/fields proxies to S3 market-data."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"fields": []}'

    mock_clients.market_data.get = AsyncMock(return_value=downstream_resp)

    response = await client.get("/v1/fundamentals/screen/fields")

    assert response.status_code == 200
    mock_clients.market_data.get.assert_called_once()
    call_args = mock_clients.market_data.get.call_args[0]
    assert "/api/v1/fundamentals/screen/fields" in call_args[0]


@pytest.mark.asyncio
async def test_get_fundamentals_timeseries_proxies_to_market_data(client, mock_clients) -> None:
    """GET /v1/fundamentals/timeseries proxies query params to S3 market-data."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"points": []}'

    mock_clients.market_data.get = AsyncMock(return_value=downstream_resp)

    response = await client.get(
        "/v1/fundamentals/timeseries",
        params={"instrument_id": "abc", "metric": "pe_ratio"},
    )

    assert response.status_code == 200
    call_kwargs = mock_clients.market_data.get.call_args[1]
    assert "params" in call_kwargs


# ── Similar entities proxy (PRD-0017 Wave C-1) ────────────────────────────────


@pytest.mark.asyncio
async def test_find_similar_entities_proxies_to_knowledge_graph(client, mock_clients) -> None:
    """POST /v1/entities/similar proxies body to S7 knowledge-graph."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = (
        b'{"entity_id": "' + entity_id.encode() + b'", "canonical_name": "AAPL", "results": [], "total": 0}'
    )

    mock_clients.knowledge_graph.post = AsyncMock(return_value=downstream_resp)

    response = await client.post(
        "/v1/entities/similar",
        content=b'{"entity_id": "00000000-0000-0000-0000-000000000001"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    mock_clients.knowledge_graph.post.assert_called_once()
    call_args = mock_clients.knowledge_graph.post.call_args[0]
    assert "/api/v1/entities/similar" in call_args[0]


@pytest.mark.asyncio
async def test_find_similar_entities_propagates_s7_404(client, mock_clients) -> None:
    """S7 404 (entity not found) is propagated unchanged."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 404
    downstream_resp.content = b'{"detail": "Entity not found"}'

    mock_clients.knowledge_graph.post = AsyncMock(return_value=downstream_resp)

    response = await client.post(
        "/v1/entities/similar",
        content=b'{"entity_id": "00000000-0000-0000-0000-000000000099"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_find_similar_entities_propagates_s7_503(client, mock_clients) -> None:
    """S7 503 (pgvector unavailable) is propagated unchanged."""
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 503
    downstream_resp.content = b'{"detail": "Similarity search unavailable"}'

    mock_clients.knowledge_graph.post = AsyncMock(return_value=downstream_resp)

    response = await client.post(
        "/v1/entities/similar",
        content=b'{"entity_id": "00000000-0000-0000-0000-000000000001"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503
