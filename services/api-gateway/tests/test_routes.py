"""Tests for composed gateway endpoints with mocked downstream services."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.unit


def _inject_rsa_keys(application) -> None:
    """Inject real RSA keys into app state so _system_headers() can issue JWTs."""
    from api_gateway.oidc import rsa_key_id

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    application.state.rsa_private_key = private_key
    application.state.rsa_public_key = private_key.public_key()
    application.state.rsa_kid = rsa_key_id(private_key.public_key())


@pytest.mark.asyncio
async def test_company_overview_composes_responses(client, mock_clients) -> None:
    """GET /v1/companies/:id/overview returns {instrument, quote, ohlcv, fundamentals}.

    Four parallel market-data calls are made (instrument, company-profile, ohlcv, quote).
    Each call gets its own fresh JWT via make_headers factory to avoid JTI replay.
    The mock dispatches by URL so asyncio.gather ordering doesn't affect the test.
    """
    _entity_id = "01900000-0000-7000-8000-000000001001"

    inst_data = {"id": _entity_id, "symbol": "AAPL", "exchange": "NASDAQ", "is_active": True}
    profile_data = {
        "records": [{"data": {"Name": "Apple Inc.", "Currency": "USD", "GicSector": "Information Technology"}}]
    }
    # Use the real S3 OHLCVListResponse format: items/bar_date/string-values.
    # get_company_overview normalizes this to bars/timestamp/numeric for the frontend.
    ohlcv_data = {
        "items": [
            {
                "instrument_id": _entity_id,
                "timeframe": "1d",
                "bar_date": "2026-04-23T00:00:00",
                "open": "168.00",
                "high": "173.00",
                "low": "167.00",
                "close": "172.00",
                "volume": 900_000,
                "adjusted_close": None,
                "source": "eodhd",
            },
            {
                "instrument_id": _entity_id,
                "timeframe": "1d",
                "bar_date": "2026-04-24T00:00:00",
                "open": "170.00",
                "high": "175.00",
                "low": "169.00",
                "close": "174.00",
                "volume": 1_000_000,
                "adjusted_close": None,
                "source": "eodhd",
            },
        ],
        "total": 2,
        "timeframe": "1d",
    }
    quote_data = {
        "instrument_id": _entity_id,
        "last": "174.00",
        "volume": 1_000_000,
        "timestamp": "2026-04-24T16:00:00Z",
    }
    # All-sections fundamentals response: S3 returns records with a "section" field.
    # S9 extracts highlights (market_cap/pe_ratio) and technicals_snapshot (52w range).
    all_fundamentals_data = {
        "security_id": _entity_id,
        "records": [
            {
                "section": "highlights",
                "period_type": "ttm",
                "period_end_date": "2026-03-31",
                "data": {"MarketCapitalization": 2_500_000_000_000, "PERatio": 28.5},
            },
            {
                "section": "technicals_snapshot",
                "period_type": "daily",
                "period_end_date": "2026-04-24",
                "data": {"52WeekHigh": 195.0, "52WeekLow": 130.0},
            },
        ],
    }

    def _make_resp(data: dict) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = data
        return r

    async def _dispatch(path: str, **kwargs: object) -> MagicMock:
        """Route mock responses by URL path so gather ordering doesn't matter."""
        if "ohlcv" in path:
            return _make_resp(ohlcv_data)
        if "quotes" in path:
            return _make_resp(quote_data)
        if "fundamentals" in path and "company-profile" in path:
            return _make_resp(profile_data)
        if "fundamentals" in path:
            # General all-sections endpoint (/api/v1/fundamentals/{id})
            # returns highlights + technicals_snapshot records.
            return _make_resp(all_fundamentals_data)
        return _make_resp(inst_data)  # /api/v1/instruments/...

    mock_clients.market_data.get = AsyncMock(side_effect=_dispatch)

    response = await client.get(f"/v1/companies/{_entity_id}/overview")
    assert response.status_code == 200

    body = response.json()
    assert "instrument" in body
    assert "quote" in body
    assert "ohlcv" in body
    assert "fundamentals" in body
    assert body["instrument"]["ticker"] == "AAPL"
    assert body["instrument"]["name"] == "Apple Inc."
    # Overview fundamentals are now populated from highlights + technicals sections.
    # WHY not None: S9 now fetches highlights (market_cap, pe_ratio) and
    # technicals_snapshot (52w range) in a 5th parallel call so the instrument
    # detail header can render stats without waiting for a FundamentalsTab request.
    assert body["fundamentals"] is not None
    assert body["fundamentals"]["market_cap"] == 2_500_000_000_000.0
    assert body["fundamentals"]["pe_ratio"] == 28.5
    assert body["fundamentals"]["week_52_high"] == 195.0
    assert body["fundamentals"]["week_52_low"] == 130.0
    # daily_return computed from last 2 OHLCV bars: (174 - 172) / 172 ≈ 0.01163
    assert body["fundamentals"]["daily_return"] is not None
    assert abs(body["fundamentals"]["daily_return"] - (174.0 - 172.0) / 172.0) < 1e-6
    # Verify OHLCV normalized from S3 format (items/bar_date/str) → frontend format (bars/timestamp/float)
    assert body["ohlcv"] is not None
    assert "bars" in body["ohlcv"], "OHLCV should be normalized to 'bars' key"
    assert len(body["ohlcv"]["bars"]) == 2
    bar = body["ohlcv"]["bars"][1]
    assert bar["timestamp"] == "2026-04-24T00:00:00"
    assert bar["close"] == 174.0  # string "174.00" parsed to float


@pytest.mark.asyncio
async def test_company_overview_propagates_downstream_error(client, mock_clients) -> None:
    """Downstream 404 should propagate through the gateway."""
    err_resp = MagicMock(spec=httpx.Response)
    err_resp.status_code = 404
    err_resp.text = "Instrument not found"

    mock_clients.market_data.get = AsyncMock(return_value=err_resp)

    response = await client.get("/v1/companies/UNKNOWN/overview")
    assert response.status_code == 404


# ── PLAN-0059 I-5: instrument page-bundle ─────────────────────────────


@pytest.mark.asyncio
async def test_instrument_page_bundle_composes_all_subresources(client, mock_clients) -> None:
    """GET /v1/instruments/:id/page-bundle returns the 5 sub-resources.

    Verifies the asyncio.gather composition. Each downstream call is dispatched
    to a mock that returns a recognisable shape; the bundle must surface each
    under its named key (overview, fundamentals, technicals, insider, top_news).
    """
    inst_id = "01900000-0000-7000-8000-000000001005"

    inst_data = {"id": inst_id, "symbol": "MSFT", "exchange": "NASDAQ", "is_active": True}
    profile_data = {"records": [{"data": {"Name": "Microsoft", "Currency": "USD"}}]}
    ohlcv_data = {"items": [], "total": 0, "timeframe": "1d"}
    quote_data = {"instrument_id": inst_id, "last": "350.00", "timestamp": "2026-04-30T16:00:00Z"}
    fundamentals_data = {"records": [{"section": "highlights", "data": {"MarketCapitalization": 2e12}}]}
    technicals_data = {"records": [{"section": "technicals_snapshot", "data": {"52WeekHigh": 400.0}}]}
    insider_data = {"records": [{"data": {"0": {"ownerName": "Satya N", "transactionAcquiredDisposed": "A"}}}]}
    news_data = {"articles": [{"article_id": "n1", "title": "Hot news"}], "total": 1}
    kg_lookup_data = {"entity_id": inst_id}

    def _make_resp(data: dict) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = data
        return r

    async def _md_dispatch(path: str, **_kwargs: object) -> MagicMock:
        # Order matters here — more-specific paths must match first.
        if "ohlcv" in path:
            return _make_resp(ohlcv_data)
        if "quotes" in path:
            return _make_resp(quote_data)
        if "company-profile" in path:
            return _make_resp(profile_data)
        if "technicals-snapshot" in path:
            return _make_resp(technicals_data)
        if "insider-transactions" in path:
            return _make_resp(insider_data)
        if "fundamentals/" in path and not any(s in path for s in ("technicals", "insider", "company-profile")):
            # General all-sections fundamentals
            return _make_resp(fundamentals_data)
        return _make_resp(inst_data)

    async def _kg_dispatch(_path: str, **_kwargs: object) -> MagicMock:
        return _make_resp(kg_lookup_data)

    async def _nlp_dispatch(_path: str, **_kwargs: object) -> MagicMock:
        return _make_resp(news_data)

    mock_clients.market_data.get = AsyncMock(side_effect=_md_dispatch)
    mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_dispatch)
    mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_nlp_dispatch)

    response = await client.get(f"/v1/instruments/{inst_id}/page-bundle")
    assert response.status_code == 200

    body = response.json()
    # All five sub-resources surface under named keys.
    assert body["instrument_id"] == inst_id
    assert "entity_id" in body
    assert body["overview"] is not None
    assert body["overview"]["instrument"]["ticker"] == "MSFT"
    assert body["fundamentals"] is not None
    assert body["technicals"] is not None
    assert body["insider"] is not None
    assert body["top_news"] is not None
    assert body["top_news"]["articles"][0]["title"] == "Hot news"


@pytest.mark.asyncio
async def test_instrument_page_bundle_degrades_on_partial_failure(client, mock_clients) -> None:
    """Per-call failure must NOT fail the whole bundle.

    If insider/technicals/news downstream services 5xx, the bundle returns
    null for those keys and the rest still populate. This is the contract
    that lets the FE render a partial page instead of seeing a 5xx.
    """
    inst_id = "01900000-0000-7000-8000-000000001006"

    inst_data = {"id": inst_id, "symbol": "GOOG", "exchange": "NASDAQ", "is_active": True}
    profile_data = {"records": []}
    ohlcv_data = {"items": [], "total": 0, "timeframe": "1d"}
    quote_data = {"instrument_id": inst_id, "last": "150.00"}
    fundamentals_data = {"records": []}

    def _ok(data: dict) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = data
        return r

    def _err(status: int) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = status
        r.text = "Service unavailable"
        return r

    async def _md_dispatch(path: str, **_kwargs: object) -> MagicMock:
        if "technicals-snapshot" in path:
            return _err(503)  # technicals fails
        if "insider-transactions" in path:
            return _err(503)  # insider fails
        if "ohlcv" in path:
            return _ok(ohlcv_data)
        if "quotes" in path:
            return _ok(quote_data)
        if "company-profile" in path:
            return _ok(profile_data)
        if "fundamentals/" in path:
            return _ok(fundamentals_data)
        return _ok(inst_data)

    async def _nlp_dispatch(_path: str, **_kwargs: object) -> MagicMock:
        return _err(500)  # news fails

    async def _kg_dispatch(_path: str, **_kwargs: object) -> MagicMock:
        return _ok({"entity_id": inst_id})

    mock_clients.market_data.get = AsyncMock(side_effect=_md_dispatch)
    mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_nlp_dispatch)
    mock_clients.knowledge_graph.get = AsyncMock(side_effect=_kg_dispatch)

    response = await client.get(f"/v1/instruments/{inst_id}/page-bundle")
    # Bundle MUST still return 200 — the failed sub-resources are null.
    assert response.status_code == 200
    body = response.json()
    assert body["overview"] is not None  # required pieces succeeded
    assert body["technicals"] is None  # downstream 503 → null
    assert body["insider"] is None  # downstream 503 → null
    assert body["top_news"] is None  # downstream 500 → null


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


# ── Fundamentals section proxy routes (PLAN-0041 Wave A-1) ───────────────────
# These 6 routes proxy authenticated requests to S3 section endpoints that were
# previously not accessible through S9.  Each test verifies:
#   1. The correct S3 path is forwarded.
#   2. The X-Internal-JWT header reaches S3 (auth forwarding).
# Tests use authed_client + authed_mock_clients because these routes require
# request.state.user (JWT-authenticated), unlike the public screener endpoints.

_INSTR_ID = "00000000-0000-0000-0000-000000000042"
# Dummy HS256 JWT header — not a real credential; the authed_client fixture decodes
# it without signature verification to inject request.state.user.
_DUMMY_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEiLCJ1c2VyX2lkIjoidXNlci0xIiwidGVuYW50X2lkIjoidGVuYW50LTEifQ.sig"


def _downstream_200(content: bytes = b'{"records": []}') -> MagicMock:
    """Build a mock 200 downstream response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.content = content
    return resp


@pytest.mark.asyncio
async def test_get_technicals_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/technicals → S3 /technicals-snapshot."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/technicals",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/technicals-snapshot" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_share_statistics_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/share-statistics → S3 /share-statistics."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/share-statistics",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/share-statistics" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_insider_transactions_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/insider-transactions → S3 /insider-transactions-snapshot."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/insider-transactions",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/insider-transactions-snapshot" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_earnings_trend_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/earnings-trend → S3 /earnings-trend."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/earnings-trend",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/earnings-trend" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_earnings_annual_trend_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/earnings-annual-trend → S3 /earnings-annual-trend."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/earnings-annual-trend",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/earnings-annual-trend" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_splits_dividends_proxies_to_market_data(authed_client, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/splits-dividends → S3 /splits-dividends."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    response = await authed_client.get(
        f"/v1/fundamentals/{_INSTR_ID}/splits-dividends",
        headers={"Authorization": f"Bearer {_DUMMY_JWT}"},
    )

    assert response.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert "/splits-dividends" in call_args[0][0]


@pytest.mark.asyncio
async def test_fundamentals_section_routes_require_auth(client, mock_clients) -> None:
    """Fundamentals section routes return 401 when user is not authenticated."""
    # Uses the unauthenticated `client` fixture (no bearer token injected)
    mock_clients.market_data.get = AsyncMock(return_value=_downstream_200())

    for path_suffix in [
        "technicals",
        "share-statistics",
        "insider-transactions",
        "earnings-trend",
        "earnings-annual-trend",
        "splits-dividends",
    ]:
        response = await client.get(f"/v1/fundamentals/{_INSTR_ID}/{path_suffix}")
        assert response.status_code == 401, f"Expected 401 for /{path_suffix}, got {response.status_code}"


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


# ── F-02: Public proxy routes send system JWT to backends ─────────────────────


@pytest.mark.asyncio
async def test_screen_instruments_sends_system_jwt(app, mock_clients) -> None:
    """F-02: POST /v1/fundamentals/screen (public) sends X-Internal-JWT to S3."""
    _inject_rsa_keys(app)
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"results": [], "count": 0, "total": 0}'
    mock_clients.market_data.post = AsyncMock(return_value=downstream_resp)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/fundamentals/screen",
            content=b'{"filters": []}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    call_kwargs = mock_clients.market_data.post.call_args[1]
    assert "X-Internal-JWT" in call_kwargs["headers"]


@pytest.mark.asyncio
async def test_screen_fields_sends_system_jwt(app, mock_clients) -> None:
    """F-02: GET /v1/fundamentals/screen/fields (public) sends X-Internal-JWT to S3."""
    _inject_rsa_keys(app)
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"fields": []}'
    mock_clients.market_data.get = AsyncMock(return_value=downstream_resp)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/fundamentals/screen/fields")

    assert response.status_code == 200
    call_kwargs = mock_clients.market_data.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})


@pytest.mark.asyncio
async def test_fundamentals_timeseries_sends_system_jwt(app, mock_clients) -> None:
    """F-02: GET /v1/fundamentals/timeseries (public) sends X-Internal-JWT to S3."""
    _inject_rsa_keys(app)
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"points": []}'
    mock_clients.market_data.get = AsyncMock(return_value=downstream_resp)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/fundamentals/timeseries",
            params={"instrument_id": "abc", "metric": "pe_ratio"},
        )

    assert response.status_code == 200
    call_kwargs = mock_clients.market_data.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})


@pytest.mark.asyncio
async def test_similar_entities_sends_system_jwt(app, mock_clients) -> None:
    """F-02: POST /v1/entities/similar (public) sends X-Internal-JWT to S7."""
    _inject_rsa_keys(app)
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.content = b'{"results": [], "total": 0}'
    mock_clients.knowledge_graph.post = AsyncMock(return_value=downstream_resp)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/entities/similar",
            content=b'{"entity_id": "00000000-0000-0000-0000-000000000001"}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    call_kwargs = mock_clients.knowledge_graph.post.call_args[1]
    assert "X-Internal-JWT" in call_kwargs["headers"]


# ── Entity graph transformation (schema mismatch fix) ────────────────────────


@pytest.mark.asyncio
async def test_entity_graph_transforms_s7_response(authed_client, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph transforms S7 GraphNeighborhoodResponse → EntityGraph.

    S7 returns {center, relations, entities}; the frontend Cytoscape.js renderer
    expects {entity_id, nodes, edges}.  The gateway must bridge this mismatch via
    _transform_graph_response() so the knowledge graph actually renders in the UI.

    This test covers the full happy-path transformation:
    - center node included in nodes with size=2
    - related entities included in nodes with size=1
    - relations mapped to edges (relation_id → id, subject/object → source/target,
      canonical_type → label, confidence → weight)
    """

    _center_id = "01900000-0000-7000-8000-000000001001"
    _neighbor_id = "01900000-0000-7000-8000-000000001002"
    _relation_id = "01900000-0000-7000-8000-000000009001"

    # Simulate the exact payload S7's GraphNeighborhoodResponse returns
    s7_payload = {
        "center": {
            "entity_id": _center_id,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
        },
        "relations": [
            {
                "relation_id": _relation_id,
                "subject_entity_id": _center_id,
                "object_entity_id": _neighbor_id,
                "canonical_type": "COMPETES_WITH",
                "confidence": 0.85,
            }
        ],
        "entities": {
            _neighbor_id: {
                "entity_id": _neighbor_id,
                "canonical_name": "Microsoft Corp.",
                "entity_type": "financial_instrument",
            }
        },
    }

    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.json.return_value = s7_payload

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=downstream_resp)

    # Use a real JWT in the Authorization header so the auth guard passes
    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": "user-1", "user_id": "user-1", "tenant_id": "tenant-1"},
        "test-secret",
        algorithm="HS256",
    )
    response = await authed_client.get(
        f"/v1/entities/{_center_id}/graph",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()

    # Top-level shape must be EntityGraph, not GraphNeighborhoodResponse
    assert "entity_id" in body, "Response must have 'entity_id' (EntityGraph format)"
    assert "nodes" in body, "Response must have 'nodes' (EntityGraph format)"
    assert "edges" in body, "Response must have 'edges' (EntityGraph format)"
    assert "center" not in body, "S7 'center' key must NOT appear in the transformed response"
    assert "relations" not in body, "S7 'relations' key must NOT appear in the transformed response"

    assert body["entity_id"] == _center_id

    # Nodes: center (size=2) + 1 neighbor (size=1)
    assert len(body["nodes"]) == 2, f"Expected 2 nodes, got {len(body['nodes'])}"
    center_node = next(n for n in body["nodes"] if n["id"] == _center_id)
    neighbor_node = next(n for n in body["nodes"] if n["id"] == _neighbor_id)
    assert center_node["label"] == "Apple Inc."
    assert center_node["type"] == "financial_instrument"
    assert center_node["size"] == 2, "Center node must have size=2"
    assert neighbor_node["label"] == "Microsoft Corp."
    assert neighbor_node["size"] == 1, "Neighbor nodes must have size=1"

    # Edges: relation mapped correctly
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert edge["id"] == _relation_id
    assert edge["source"] == _center_id
    assert edge["target"] == _neighbor_id
    assert edge["label"] == "COMPETES_WITH"
    assert edge["weight"] == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_entity_graph_passes_through_s7_errors(authed_client, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph passes S7 4xx responses through unchanged.

    No transformation is attempted on error responses — the status code and body
    are forwarded as-is so the frontend can display a meaningful error state.
    """
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 404
    downstream_resp.content = b'{"detail": "Entity not found"}'

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=downstream_resp)

    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": "user-1", "user_id": "user-1", "tenant_id": "tenant-1"},
        "test-secret",
        algorithm="HS256",
    )
    response = await authed_client.get(
        "/v1/entities/00000000-0000-0000-0000-000000000099/graph",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_entity_graph_resilient_to_missing_fields(authed_client, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph handles partial/empty S7 responses without crashing.

    If S7 returns an empty or partially-formed response (e.g., isolated entity with
    no relations), the transformation must still return a valid EntityGraph shape
    rather than raising KeyError / TypeError.
    """
    # Minimal payload: center only, no relations, no neighbor entities
    s7_minimal = {
        "center": {"entity_id": "abc-123", "canonical_name": "Lonely Corp.", "entity_type": "company"},
        "relations": [],
        "entities": {},
    }
    downstream_resp = MagicMock(spec=httpx.Response)
    downstream_resp.status_code = 200
    downstream_resp.json.return_value = s7_minimal

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=downstream_resp)

    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": "user-1", "user_id": "user-1", "tenant_id": "tenant-1"},
        "test-secret",
        algorithm="HS256",
    )
    response = await authed_client.get(
        "/v1/entities/abc-123/graph",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entity_id"] == "abc-123"
    assert len(body["nodes"]) == 1  # center only
    assert body["nodes"][0]["size"] == 2
    assert body["edges"] == []
