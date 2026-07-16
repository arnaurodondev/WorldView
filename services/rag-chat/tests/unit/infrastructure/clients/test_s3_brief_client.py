"""Unit tests for S3BriefClient HTTP adapter (PLAN-0081 Wave A)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_client():
    from rag_chat.infrastructure.clients.s3_brief_client import S3BriefClient

    return S3BriefClient(base_url="http://s9-mock", timeout=5.0)


@pytest.mark.asyncio
async def test_screen_instruments_happy_path():
    client = _make_client()
    mock_response = {"instruments": [{"ticker": "AAPL", "market_cap": 3e12}]}
    mock_post = AsyncMock(return_value=mock_response)
    with patch.object(client, "_post", new=mock_post):
        result = await client.screen_instruments({"sector": "Technology"})
        # Assert inside context manager while mock is still bound
        mock_post.assert_awaited_once_with("/v1/fundamentals/screen", payload={"sector": "Technology"})
    assert result == mock_response


@pytest.mark.asyncio
async def test_screen_instruments_error_returns_empty():
    client = _make_client()
    with patch.object(client, "_post", new=AsyncMock(return_value={})):
        result = await client.screen_instruments({})
    assert result == {}


@pytest.mark.asyncio
async def test_get_top_movers_uppercases_period():
    """C-2 fix: period must be sent uppercase to S9."""
    client = _make_client()
    mock_response = {"movers": [{"ticker": "AAPL", "change_percent": 5.2}]}
    captured_params = {}

    async def _mock_get(path, params=None, **kwargs):
        captured_params.update(params or {})
        return mock_response

    with patch.object(client, "_get", new=_mock_get):
        result = await client.get_top_movers(mover_type="gainers", limit=5, period="1d")
    assert captured_params.get("period") == "1D", "period must be uppercased to match S9 contract"
    assert result == mock_response


@pytest.mark.asyncio
async def test_get_top_movers_already_uppercase_period():
    client = _make_client()
    captured_params = {}

    async def _mock_get(path, params=None, **kwargs):
        captured_params.update(params or {})
        return {}

    with patch.object(client, "_get", new=_mock_get):
        await client.get_top_movers(period="1W")
    assert captured_params["period"] == "1W"


@pytest.mark.asyncio
async def test_get_economic_calendar_extracts_events_key():
    client = _make_client()
    events = [{"date": "2026-05-09", "name": "CPI"}]
    with patch.object(client, "_get", new=AsyncMock(return_value={"events": events, "total": 1})):
        result = await client.get_economic_calendar()
    assert result == events


@pytest.mark.asyncio
async def test_get_economic_calendar_error_returns_empty_list():
    client = _make_client()
    with patch.object(client, "_get", new=AsyncMock(return_value={})):
        result = await client.get_economic_calendar()
    assert result == []


@pytest.mark.asyncio
async def test_get_earnings_calendar_extracts_events_key():
    """C-1 fix: earnings-calendar returns {events: [...]} not {earnings: [...]}."""
    client = _make_client()
    entries = [{"date": "2026-05-12", "ticker": "AAPL", "eps_estimate": 1.5}]
    with patch.object(client, "_get", new=AsyncMock(return_value={"events": entries, "total": 1})):
        result = await client.get_earnings_calendar()
    assert result == entries


@pytest.mark.asyncio
async def test_get_earnings_calendar_error_returns_empty_list():
    client = _make_client()
    with patch.object(client, "_get", new=AsyncMock(return_value={})):
        result = await client.get_earnings_calendar()
    assert result == []


@pytest.mark.asyncio
async def test_get_economic_calendar_passes_params():
    client = _make_client()
    captured = {}

    async def _mock(path, params=None, **kwargs):
        captured.update(params or {})
        return {"events": []}

    with patch.object(client, "_get", new=_mock):
        await client.get_economic_calendar(from_date="2026-05-01", to_date="2026-05-31", region="US")
    assert captured == {"from": "2026-05-01", "to": "2026-05-31", "region": "US"}


# ── get_prediction_markets: prod S9-auth-gap bypass (BP-73x, 2026-07-16) ──────
# The persistent prediction-market chat refusal was NOT routing (tool_use v1.25
# invokes the tool) — it was the S9 gateway 401'ing the forwarded internal JWT,
# so the tool got [] and the pipeline refused. get_prediction_markets must hit
# market-data DIRECTLY when a market_data_base_url is wired.


def _make_direct_client():
    from rag_chat.infrastructure.clients.s3_brief_client import S3BriefClient

    return S3BriefClient(
        base_url="http://s9-mock",
        timeout=5.0,
        market_data_base_url="http://market-data-mock:8003",
    )


@pytest.mark.asyncio
async def test_get_prediction_markets_uses_direct_market_data_route_when_wired():
    """With market_data_base_url set, the tool must bypass the S9 gateway and call
    market-data's /api/v1/prediction-markets (the route that accepts the internal
    JWT) — NOT the gateway /v1/signals/... route that 401s in prod."""
    client = _make_direct_client()
    items = [{"market_id": "0x1", "question": "Will Donald Trump win the 2028 US Presidential Election?"}]
    captured: dict = {}

    async def _direct_get(path, params=None, **kwargs):
        captured["path"] = path
        captured["params"] = dict(params or {})
        return {"items": items, "total": 1}

    # The gateway path must NOT be used — make it explode if it is.
    async def _gateway_get(path, params=None, **kwargs):  # pragma: no cover
        raise AssertionError(f"S9 gateway route must not be called; got {path}")

    with (
        patch.object(client._md_direct, "_get", new=_direct_get),
        patch.object(client, "_get", new=_gateway_get),
    ):
        result = await client.get_prediction_markets(
            query="Donald Trump 2028 US Presidential Election",
            category=None,
            status="open",
            limit=10,
        )

    assert captured["path"] == "/api/v1/prediction-markets"
    assert captured["params"] == {
        "status": "open",
        "limit": 10,
        "query": "Donald Trump 2028 US Presidential Election",
    }
    assert result == items


@pytest.mark.asyncio
async def test_get_prediction_markets_direct_extracts_items_key():
    client = _make_direct_client()
    items = [{"market_id": "0x9", "question": "Will bitcoin hit $1m before GTA VI?"}]
    with patch.object(client._md_direct, "_get", new=AsyncMock(return_value={"items": items, "total": 1})):
        result = await client.get_prediction_markets(query="bitcoin", category=None, status="open", limit=10)
    assert result == items


@pytest.mark.asyncio
async def test_get_prediction_markets_direct_error_returns_empty():
    client = _make_direct_client()
    with patch.object(client._md_direct, "_get", new=AsyncMock(return_value={})):
        result = await client.get_prediction_markets(query="x", category=None, status="open", limit=10)
    assert result == []


@pytest.mark.asyncio
async def test_get_prediction_markets_falls_back_to_gateway_without_direct_url():
    """Without market_data_base_url (dev/tests) the legacy S9 gateway route is used
    so existing behaviour is preserved."""
    client = _make_client()
    assert client._md_direct is None
    captured: dict = {}

    async def _gateway_get(path, params=None, **kwargs):
        captured["path"] = path
        return {"items": [], "total": 0}

    with patch.object(client, "_get", new=_gateway_get):
        await client.get_prediction_markets(query="x", category=None, status="open", limit=5)
    assert captured["path"] == "/v1/signals/prediction-markets"
