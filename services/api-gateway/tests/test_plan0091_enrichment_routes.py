"""Tests for PLAN-0091 Data Enrichment — new S9 endpoints (Waves A-2, E-1, E-2).

Covers:
    T-A-2-01  GET /v1/articles/{article_id}/impact-history  → S6 proxy
    T-A-2-02  GET /v1/entities/{entity_id}/sentiment-timeseries  → S6 proxy
    T-A-2-03  GET /v1/portfolios/{id}/sector-attribution  → S1 + S3 composition
    T-A-2-04  GET /v1/market/yield-curve  → S3 macro_indicator or ETF proxy
    T-E-1-01  POST /v1/screener/nl-translate  → S8 LLM + S3 field validation

Reuses ``authed_app`` / ``authed_mock_clients`` / ``app`` / ``mock_clients``
fixtures from conftest.py.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}

_ENTITY_ID = str(uuid.uuid4())
_ARTICLE_ID = str(uuid.uuid4())


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=json.loads(content))
    except Exception:
        resp.json = MagicMock(side_effect=ValueError("invalid JSON"))
    return resp


# ── T-A-2-01: article impact-history ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_article_impact_history_proxies_to_s6(authed_app, authed_mock_clients) -> None:
    """GET /v1/articles/{id}/impact-history calls S6 /api/v1/articles/{id}/impact-windows."""
    payload = b'{"windows": [{"window": "t0", "delta_pct": 1.5}]}'
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/articles/{_ARTICLE_ID}/impact-history",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = authed_mock_clients.nlp_pipeline.get.call_args[0]
    assert f"/api/v1/articles/{_ARTICLE_ID}/impact-windows" in call_args[0]


@pytest.mark.asyncio
async def test_article_impact_history_passes_through_404(authed_app, authed_mock_clients) -> None:
    """S6 404 is forwarded unchanged."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/articles/{_ARTICLE_ID}/impact-history",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


# ── T-A-2-02: entity sentiment timeseries ────────────────────────────────────


@pytest.mark.asyncio
async def test_sentiment_timeseries_requires_auth(app, mock_clients) -> None:
    """Unauthenticated request → 401, no downstream call."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_ID}/sentiment-timeseries")

    assert resp.status_code == 401
    mock_clients.nlp_pipeline.get.assert_not_called()


@pytest.mark.asyncio
async def test_sentiment_timeseries_proxies_to_s6(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/sentiment-timeseries proxies to S6 with days param."""
    payload = json.dumps(
        {"entity_id": _ENTITY_ID, "days": 30, "points": [{"date": "2026-05-01", "article_count": 3}]}
    ).encode()
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
            params={"days": "30"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args, call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args
    assert f"/api/v1/entities/{_ENTITY_ID}/sentiment-timeseries" in call_args[0]
    assert call_kwargs["params"]["days"] == 30


@pytest.mark.asyncio
async def test_sentiment_timeseries_default_days(authed_app, authed_mock_clients) -> None:
    """Default days=90 is forwarded when not supplied."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"entity_id":"x","days":90,"points":[]}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_ID}/sentiment-timeseries",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    _, call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args
    assert call_kwargs["params"]["days"] == 90


# ── T-A-2-03: portfolio sector-attribution ───────────────────────────────────


@pytest.mark.asyncio
async def test_sector_attribution_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios/p-1/sector-attribution")

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_sector_attribution_empty_portfolio(authed_app, authed_mock_clients) -> None:
    """Empty holdings → empty buckets, covered_pct=0."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": []}'),
    )
    authed_mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(200, b"[]"),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/sector-attribution",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["portfolio_id"] == "p-1"
    assert body["buckets"] == []
    assert body["covered_pct"] == 0.0


@pytest.mark.asyncio
async def test_sector_attribution_groups_by_sector(authed_app, authed_mock_clients) -> None:
    """Two holdings in same sector sum their weights."""
    iid_1 = str(uuid.uuid4())
    iid_2 = str(uuid.uuid4())
    holdings_payload = json.dumps(
        {
            "items": [
                {"instrument_id": iid_1, "quantity": "10", "average_cost": "100.00"},
                {"instrument_id": iid_2, "quantity": "5", "average_cost": "200.00"},
            ]
        }
    ).encode()
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, holdings_payload))

    # Price batch: both instruments at $100 flat → no day_change
    price_payload = json.dumps(
        [
            {"instrument_id": iid_1, "price": 100.0, "day_change_pct": 0.0},
            {"instrument_id": iid_2, "price": 200.0, "day_change_pct": 0.0},
        ]
    ).encode()
    authed_mock_clients.market_data.post = AsyncMock(return_value=_mock_response(200, price_payload))

    # Fundamentals returns "Technology" sector for both
    tech_fundamentals = json.dumps({"General": {"Sector": "Technology"}}).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, tech_fundamentals))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/sector-attribution",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["portfolio_id"] == "p-1"
    buckets = {b["sector"]: b for b in body["buckets"]}
    assert "Technology" in buckets
    tech = buckets["Technology"]
    assert tech["holding_count"] == 2
    assert tech["sector_weight_pct"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_sector_attribution_passes_portfolio_404(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/missing/sector-attribution",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


# ── T-A-2-04: yield curve ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_yield_curve_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/market/yield-curve")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_yield_curve_returns_all_null_when_no_data(authed_app, authed_mock_clients) -> None:
    """With no macro_indicator events and ETF lookup failure → all null points."""
    # TemporalEvents returns empty list
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b"[]"))
    # ETF instrument search returns no results → no ETF fetch
    authed_mock_clients.market_data.post = AsyncMock(return_value=_mock_response(200, b"[]"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/yield-curve",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["points"]) == 4
    for pt in body["points"]:
        assert pt["yield_pct"] is None
    assert body["spread_2s10s"] is None
    assert body["spread_2s10s_inverted"] is None


@pytest.mark.asyncio
async def test_yield_curve_uses_macro_indicator_data(authed_app, authed_mock_clients) -> None:
    """Macro indicator events populate yield points and compute spread."""
    events = [
        {"title": "US_2Y_YIELD", "macro_indicators": {"yield": 4.75}, "structured_data": {}},
        {"title": "US_10Y_YIELD", "macro_indicators": {"yield": 4.25}, "structured_data": {}},
    ]
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(events).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/yield-curve",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    by_maturity = {p["maturity"]: p for p in body["points"]}
    assert by_maturity["2Y"]["yield_pct"] == pytest.approx(4.75)
    assert by_maturity["10Y"]["yield_pct"] == pytest.approx(4.25)
    # spread = (4.25 - 4.75) * 100 = -50 bps → inverted
    assert body["spread_2s10s"] == pytest.approx(-50.0)
    assert body["spread_2s10s_inverted"] is True
    assert body["source"] == "macro_indicator"


# ── T-E-1-01: nl-screener translate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_nl_screener_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/screener/nl-translate",
            json={"query": "profitable tech stocks"},
        )

    assert resp.status_code == 401
    mock_clients.rag_chat.post.assert_not_called()


@pytest.mark.asyncio
async def test_nl_screener_happy_path(authed_app, authed_mock_clients) -> None:
    """Valid LLM response with known fields returns 200 with parsed filters."""
    valid_fields = [{"name": "sector"}, {"name": "pe_ratio"}, {"name": "profit_margin"}]
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps({"fields": valid_fields}).encode()),
    )
    llm_result = {"sector": "Technology", "pe_ratio": {"lte": 20}}
    chat_response = json.dumps({"content": json.dumps(llm_result)}).encode()
    authed_mock_clients.rag_chat.post = AsyncMock(return_value=_mock_response(200, chat_response))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/screener/nl-translate",
            json={"query": "profitable tech stocks with low PE"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["filters"]["sector"] == "Technology"
    assert body["natural_language_query"] == "profitable tech stocks with low PE"


@pytest.mark.asyncio
async def test_nl_screener_returns_422_on_invalid_fields(authed_app, authed_mock_clients) -> None:
    """LLM returning hallucinated field names → 422."""
    valid_fields = [{"name": "sector"}, {"name": "pe_ratio"}]
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps({"fields": valid_fields}).encode()),
    )
    llm_result = {"sector": "Technology", "hallucinated_field": 999}
    chat_response = json.dumps({"content": json.dumps(llm_result)}).encode()
    authed_mock_clients.rag_chat.post = AsyncMock(return_value=_mock_response(200, chat_response))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/screener/nl-translate",
            json={"query": "tech stocks"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_nl_screener_returns_422_when_llm_unparseable(authed_app, authed_mock_clients) -> None:
    """LLM returning _unparseable → 422."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"fields": []}'))
    chat_response = json.dumps({"content": json.dumps({"_unparseable": True})}).encode()
    authed_mock_clients.rag_chat.post = AsyncMock(return_value=_mock_response(200, chat_response))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/screener/nl-translate",
            json={"query": "xyz gibberish"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_nl_screener_returns_502_on_llm_error(authed_app, authed_mock_clients) -> None:
    """S8 returning non-200 → 502."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"fields": []}'))
    authed_mock_clients.rag_chat.post = AsyncMock(return_value=_mock_response(503, b"unavailable"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/screener/nl-translate",
            json={"query": "profitable stocks"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 502
