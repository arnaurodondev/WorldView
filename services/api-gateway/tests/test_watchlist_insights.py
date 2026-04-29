"""PLAN-0050 T-B-2-01 — GET /v1/watchlists/{id}/insights composite tests.

Verifies:
1. Auth required (no JWT → 401, downstream untouched).
2. Happy path: members + quotes + overviews + news + alerts compose into one
   payload with the documented shape.
3. Per-member sector enrichment populates from the instrument record.
4. Active-alert flag flips on for members whose entity_id appears in
   /api/v1/alerts/pending.
5. News count and top-news fields populate from the 24h news pool.
6. Biggest news article (highest impact_score) is selected from members'
   articles only — not from the global news pool.
7. Sector breakdown sums to members_count and is sorted desc by count.
8. weighted_return_1d averages only members with quotes (skips loading rows).
9. Cache-Control header set with private + max-age=60.
10. Empty watchlist returns the documented shape with zero counts.
11. (F-Q1-02) Quotes come from PriceSnapshot (/internal/v1/price/{iid})
    returning price + price_change_pct; not from legacy QuoteResponse.
12. (F-Q1-13) Movers sorted by |change_pct| DESC so gainers/losers split
    always shows the most-moved instruments first.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105


def _make_jwt() -> str:
    return jwt.encode(
        {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _resp(status: int, body: dict) -> MagicMock:
    """Build a MagicMock httpx.Response shape that the gateway helpers expect."""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.content = json.dumps(body).encode()
    r.text = json.dumps(body)
    r.json = MagicMock(return_value=body)
    return r


# ── Fixtures (per-test rebinding so each test owns its fan-out) ──────────────


@pytest.fixture
def members_payload() -> dict:
    """Two members with resolved instrument_ids and entity_ids."""
    return {
        "members": [
            {"instrument_id": "i-aapl", "entity_id": "e-aapl", "ticker": "AAPL", "name": "Apple"},
            {"instrument_id": "i-msft", "entity_id": "e-msft", "ticker": "MSFT", "name": "Microsoft"},
        ]
    }


@pytest.fixture
def news_payload() -> dict:
    """One article touching each member; AAPL article has higher impact.

    F-QA2-01 fix: fixtures now match S6's actual `RankedArticleResponse`
    contract — single `primary_entity_id`, NOT a `entity_ids` list. The
    prior list-shape fixture happened to make tests pass while the
    composer was reading a non-existent field, masking a production bug.
    """
    # Iso 8601 with timezone — within 24h cutoff (current logic uses datetime.now).
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
    return {
        "articles": [
            {
                "article_id": "art-1",
                "title": "Apple beats earnings",
                "url": "https://news.example/aapl",
                "published_at": recent,
                "ticker": "AAPL",
                "primary_entity_id": "e-aapl",
                "market_impact_score": 0.9,
            },
            {
                "article_id": "art-2",
                "title": "Microsoft cloud growth",
                "url": "https://news.example/msft",
                "published_at": recent,
                "ticker": "MSFT",
                "primary_entity_id": "e-msft",
                "market_impact_score": 0.4,
            },
            # Article touching neither member — must NOT appear in biggest_news.
            {
                "article_id": "art-3",
                "title": "Unrelated mega-impact",
                "url": "https://news.example/oth",
                "published_at": recent,
                "ticker": "GOOG",
                "primary_entity_id": "e-goog",
                "market_impact_score": 1.0,
            },
        ]
    }


@pytest.fixture
def alerts_payload() -> dict:
    """One pending alert flagging AAPL; MSFT has none."""
    return {"alerts": [{"alert_id": "al-1", "entity_id": "e-aapl", "severity": "high"}]}


def _wire_clients(authed_mock_clients, members, news, alerts, *, quotes=None, overviews=None) -> None:
    """Wire the four downstream clients with the per-path mocks.

    F-Q1-02: quotes dict is now keyed by iid and values use PriceSnapshot shape:
      { "price": float|None, "price_change_pct": float|None }
    The mock intercepts /internal/v1/price/{iid} — not the legacy /api/v1/quotes/{iid}.
    """

    async def _portfolio_get(path: str, **_kwargs):
        if "/api/v1/watchlists/" in path and path.endswith("/members"):
            return _resp(200, members)
        return _resp(404, {"detail": "not-found"})

    async def _market_data_get(path: str, **_kwargs):
        # F-Q1-02: insights now calls /internal/v1/price/{iid} (PriceSnapshot) instead
        # of the legacy /api/v1/quotes/{iid} (QuoteResponse without change_pct).
        if path.startswith("/internal/v1/price/"):
            iid = path.rsplit("/", 1)[-1]
            return _resp(200, (quotes or {}).get(iid, {}))
        if path.startswith("/api/v1/instruments/"):
            iid = path.rsplit("/", 1)[-1]
            return _resp(200, (overviews or {}).get(iid, {}))
        return _resp(404, {"detail": "not-found"})

    async def _nlp_get(path: str, **_kwargs):
        if path == "/api/v1/news/top":
            return _resp(200, news)
        return _resp(404, {"detail": "not-found"})

    async def _alert_get(path: str, **_kwargs):
        if path == "/api/v1/alerts/pending":
            return _resp(200, alerts)
        return _resp(404, {"detail": "not-found"})

    authed_mock_clients.portfolio.get = AsyncMock(side_effect=_portfolio_get)
    authed_mock_clients.market_data.get = AsyncMock(side_effect=_market_data_get)
    authed_mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_nlp_get)
    authed_mock_clients.alert.get = AsyncMock(side_effect=_alert_get)


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insights_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/watchlists/wl-1/insights")
    assert resp.status_code == 401
    # No downstream call should have fired
    mock_clients.portfolio.get.assert_not_called()
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_insights_happy_path_composes_all_signals(
    authed_app, authed_mock_clients, members_payload, news_payload, alerts_payload
) -> None:
    # F-Q1-02: quotes now use PriceSnapshot shape (price, price_change_pct)
    # rather than legacy QuoteResponse (last, bid, ask — no change_pct).
    quotes = {
        "i-aapl": {"price": "200.0", "price_change_pct": "1.5"},
        "i-msft": {"price": "410.0", "price_change_pct": "-0.5"},
    }
    overviews = {
        "i-aapl": {"gics_sector": "Information Technology"},
        "i-msft": {"gics_sector": "Information Technology"},
    }
    _wire_clients(
        authed_mock_clients,
        members_payload,
        news_payload,
        alerts_payload,
        quotes=quotes,
        overviews=overviews,
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["watchlist_id"] == "wl-1"
    assert body["members_count"] == 2
    assert len(body["movers"]) == 2

    aapl = next(m for m in body["movers"] if m["ticker"] == "AAPL")
    msft = next(m for m in body["movers"] if m["ticker"] == "MSFT")

    # Per-member quote + sector enrichment (F-Q1-02: price from PriceSnapshot)
    assert aapl["price"] == pytest.approx(200.0)
    assert aapl["change_pct"] == pytest.approx(1.5)
    assert aapl["sector"] == "Information Technology"
    assert msft["price"] == pytest.approx(410.0)
    assert msft["sector"] == "Information Technology"

    # News + alert linkage
    assert aapl["news_count_24h"] == 1
    assert aapl["top_news_title"] == "Apple beats earnings"
    assert aapl["has_active_alert"] is True
    assert msft["news_count_24h"] == 1
    assert msft["has_active_alert"] is False

    # Aggregates
    # weighted_return_1d = avg(1.5, -0.5) = 0.5
    assert body["weighted_return_1d"] == pytest.approx(0.5)
    assert body["alerts_count"] == 1

    # Sector breakdown sorted desc by count
    assert body["sectors"] == [
        {"sector": "Information Technology", "count": 2, "weight": 1.0},
    ]

    # F-Q1-13: movers must be sorted by |change_pct| DESC.
    # AAPL (+1.5%) has higher abs than MSFT (-0.5%), so AAPL must come first.
    assert body["movers"][0]["ticker"] == "AAPL"
    assert body["movers"][1]["ticker"] == "MSFT"


@pytest.mark.asyncio
async def test_insights_biggest_news_only_from_members(
    authed_app, authed_mock_clients, members_payload, news_payload, alerts_payload
) -> None:
    """The art-3 article (impact=1.0) touches no member — must NOT win biggest_news.

    art-1 (AAPL, 0.9) is the highest-impact article that actually mentions a
    watchlist member, so it should be returned. This pins the "members-only"
    selection rule that distinguishes biggest_news from a generic top-impact feed.
    """
    _wire_clients(authed_mock_clients, members_payload, news_payload, alerts_payload)
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    body = resp.json()
    assert body["biggest_news"]["title"] == "Apple beats earnings"
    assert body["biggest_news"]["impact_score"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_insights_weighted_return_skips_loading_rows(
    authed_app, authed_mock_clients, members_payload, news_payload, alerts_payload
) -> None:
    """Members whose quote did not return must not contribute to the weighted avg.

    Treating a missing quote as 0% would lie about a flat day on a watchlist
    where only one symbol has loaded — the dashboard would briefly read green
    for an unknown reason. The spec is "skip rows without quotes".
    """
    # F-Q1-02: PriceSnapshot shape (price, price_change_pct), not legacy QuoteResponse
    quotes = {"i-aapl": {"price": "200.0", "price_change_pct": "2.0"}}  # MSFT missing
    _wire_clients(authed_mock_clients, members_payload, news_payload, alerts_payload, quotes=quotes)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    body = resp.json()
    # Only AAPL contributed a change_pct → avg is 2.0, not (2.0 + 0)/2.
    assert body["weighted_return_1d"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_insights_empty_watchlist(authed_app, authed_mock_clients) -> None:
    """An empty members list returns the full envelope with safe zero defaults."""
    _wire_clients(
        authed_mock_clients,
        members={"members": []},
        news={"articles": []},
        alerts={"alerts": []},
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-empty/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    body = resp.json()
    assert body["members_count"] == 0
    assert body["movers"] == []
    assert body["sectors"] == []
    assert body["weighted_return_1d"] is None
    assert body["biggest_news"] is None
    assert body["alerts_count"] == 0


@pytest.mark.asyncio
async def test_insights_sets_cache_control_header(
    authed_app, authed_mock_clients, members_payload, news_payload, alerts_payload
) -> None:
    _wire_clients(authed_mock_clients, members_payload, news_payload, alerts_payload)
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    cc = resp.headers.get("cache-control", "")
    assert "max-age=60" in cc
    assert "private" in cc, "shared CDN must not mix users' watchlist insights"


@pytest.mark.asyncio
async def test_insights_propagates_s1_auth_error(authed_app, authed_mock_clients, news_payload, alerts_payload) -> None:
    """F-QA-05/F-QA-01 regression: S1 returns 403 → gateway returns 403.

    The prior _safe_get(members) silently turned auth errors into an empty
    200, hiding ownership violations. The fix uses _checked_get for the
    members fanout so S1's permission decision propagates through the gateway.
    """

    async def _portfolio_get(path: str, **_kwargs):
        if "/api/v1/watchlists/" in path and path.endswith("/members"):
            return _resp(403, {"detail": "not your watchlist"})
        return _resp(404, {"detail": "not-found"})

    async def _other(_path: str, **_kwargs):
        return _resp(200, {})

    authed_mock_clients.portfolio.get = AsyncMock(side_effect=_portfolio_get)
    authed_mock_clients.market_data.get = AsyncMock(side_effect=_other)
    authed_mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_other)
    authed_mock_clients.alert.get = AsyncMock(side_effect=_other)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-someone-else/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    # The gateway must NOT mask S1's 403 as an empty 200. Status passes through.
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_insights_member_without_entity_id_does_not_falsely_alert(authed_app, authed_mock_clients) -> None:
    """F-QA-05/F-QA-06 regression: a member with no entity_id must NOT match
    an alert payload that happens to carry an empty-string entity_id."""
    members = {
        "members": [
            # No entity_id (e.g. unresolved or non-equity instrument).
            {"instrument_id": "i-x", "ticker": "X", "name": "X Co", "entity_id": None},
        ]
    }
    # Defensive: an alert with an empty-string entity_id should not match.
    alerts = {"alerts": [{"alert_id": "a-1", "entity_id": "", "severity": "high"}]}
    _wire_clients(
        authed_mock_clients,
        members,
        {"articles": []},
        alerts,
        # F-Q1-02: PriceSnapshot shape
        quotes={"i-x": {"price": "1.0", "price_change_pct": "0.0"}},
        overviews={"i-x": {"gics_sector": "Energy"}},
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    body = resp.json()
    assert body["movers"][0]["has_active_alert"] is False
    assert body["alerts_count"] == 0


@pytest.mark.asyncio
async def test_insights_accepts_legacy_entity_ids_list(
    authed_app, authed_mock_clients, members_payload, alerts_payload
) -> None:
    """F-QA2-01 belt-and-braces: the composer also accepts a legacy
    `entity_ids: list[str]` shape so a future schema change introducing
    multi-entity articles flows through without a gateway change."""
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
    legacy_news = {
        "articles": [
            {
                "article_id": "art-legacy",
                "title": "Legacy multi-entity article",
                "url": "https://news.example/legacy",
                "published_at": recent,
                "ticker": "AAPL",
                "entity_ids": ["e-aapl", "e-msft"],
                "market_impact_score": 0.85,
            }
        ]
    }
    _wire_clients(authed_mock_clients, members_payload, legacy_news, alerts_payload)
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    body = resp.json()
    aapl = next(m for m in body["movers"] if m["ticker"] == "AAPL")
    msft = next(m for m in body["movers"] if m["ticker"] == "MSFT")
    assert aapl["news_count_24h"] == 1
    assert msft["news_count_24h"] == 1
    assert aapl["top_news_title"] == "Legacy multi-entity article"


@pytest.mark.asyncio
async def test_insights_handles_malformed_published_at(
    authed_app, authed_mock_clients, members_payload, alerts_payload
) -> None:
    """F-QA-05 coverage: malformed published_at strings must NOT crash the
    composer; the article is treated as in-window so it still appears."""
    news = {
        "articles": [
            {
                "article_id": "art-bad",
                "title": "Bad date article",
                "url": "https://news.example.com/x",
                "published_at": "not-an-iso-date",
                "ticker": "AAPL",
                "primary_entity_id": "e-aapl",
                "market_impact_score": 0.5,
            }
        ]
    }
    _wire_clients(authed_mock_clients, members_payload, news, alerts_payload)
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    aapl = next(m for m in body["movers"] if m["ticker"] == "AAPL")
    # Malformed date is treated as in-window — the article counts.
    assert aapl["news_count_24h"] == 1
    assert aapl["top_news_title"] == "Bad date article"


@pytest.mark.asyncio
async def test_insights_degrades_on_news_failure(
    authed_app, authed_mock_clients, members_payload, alerts_payload
) -> None:
    """If S6 news returns 5xx, the rest of the payload still composes.

    The widget's primary information is movers — a flaky news service must
    not gate the dashboard's main render.
    """

    async def _portfolio_get(path: str, **_kwargs):
        return _resp(200, members_payload)

    async def _market_data_get(path: str, **_kwargs):
        # F-Q1-02: insights now calls /internal/v1/price/{iid} (PriceSnapshot shape)
        if path.startswith("/internal/v1/price/"):
            return _resp(200, {"price": "100.0", "price_change_pct": "1.0"})
        return _resp(200, {"gics_sector": "Information Technology"})

    async def _nlp_get(path: str, **_kwargs):
        return _resp(503, {"detail": "service-unavailable"})

    async def _alert_get(path: str, **_kwargs):
        return _resp(200, alerts_payload)

    authed_mock_clients.portfolio.get = AsyncMock(side_effect=_portfolio_get)
    authed_mock_clients.market_data.get = AsyncMock(side_effect=_market_data_get)
    authed_mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_nlp_get)
    authed_mock_clients.alert.get = AsyncMock(side_effect=_alert_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["members_count"] == 2
    assert body["biggest_news"] is None
    # All members → news_count_24h = 0, top_news_title = None
    for m in body["movers"]:
        assert m["news_count_24h"] == 0
        assert m["top_news_title"] is None


# ── F-Q1-02 regression: price comes from PriceSnapshot, not legacy QuoteResponse ──


@pytest.mark.asyncio
async def test_insights_uses_price_snapshot_endpoint(
    authed_app, authed_mock_clients, members_payload, news_payload, alerts_payload
) -> None:
    """F-Q1-02 regression: the composer must call /internal/v1/price/{iid}
    (PriceSnapshot) to get change_pct, NOT /api/v1/quotes/{iid} (QuoteResponse).

    The legacy QuoteResponse has no change_pct field — reading it always returns
    None, breaking the gainers/losers split and weighted_return_1d aggregate.
    PriceSnapshot exposes price_change_pct as an authoritative signed % change.
    """
    # Provide PriceSnapshot-shaped responses with non-null price_change_pct.
    # If the code called the legacy /api/v1/quotes/ path, these mocks would
    # return 404 (that path is not wired) and change_pct would be null.
    quotes = {
        "i-aapl": {"price": "193.50", "price_change_pct": "2.3"},
        "i-msft": {"price": "415.00", "price_change_pct": "-1.1"},
    }
    _wire_clients(
        authed_mock_clients,
        members_payload,
        news_payload,
        alerts_payload,
        quotes=quotes,
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Both members must have non-null change_pct (proves PriceSnapshot was called)
    for m in body["movers"]:
        assert m["change_pct"] is not None, f"change_pct is null for {m['ticker']} — PriceSnapshot endpoint not used"

    aapl = next(m for m in body["movers"] if m["ticker"] == "AAPL")
    msft = next(m for m in body["movers"] if m["ticker"] == "MSFT")
    assert aapl["price"] == pytest.approx(193.50)
    assert aapl["change_pct"] == pytest.approx(2.3)
    assert msft["change_pct"] == pytest.approx(-1.1)

    # weighted_return_1d must also be non-null since both members have change_pct
    assert body["weighted_return_1d"] is not None


# ── F-Q1-13: movers sorted by |change_pct| DESC ───────────────────────────────


@pytest.mark.asyncio
async def test_insights_movers_sorted_by_absolute_change_pct(
    authed_app, authed_mock_clients, news_payload, alerts_payload
) -> None:
    """F-Q1-13 regression: movers array must be sorted by |change_pct| DESC.

    The widget renders top-N gainers and losers from this list — if it were
    returned in insertion order (watchlist member order), the most volatile
    names might not appear in top-5 slots.
    """
    # Three members with varying absolute change magnitudes.
    members = {
        "members": [
            # Insertion order: low → mid → high.  After sorting: high → mid → low.
            {"instrument_id": "i-low", "entity_id": "e-low", "ticker": "LOW", "name": "Low Mover"},
            {"instrument_id": "i-mid", "entity_id": "e-mid", "ticker": "MID", "name": "Mid Mover"},
            {"instrument_id": "i-high", "entity_id": "e-high", "ticker": "HIGH", "name": "High Mover"},
        ]
    }
    quotes = {
        "i-low": {"price": "10.0", "price_change_pct": "0.5"},  # |0.5|
        "i-mid": {"price": "20.0", "price_change_pct": "-2.0"},  # |2.0|
        "i-high": {"price": "30.0", "price_change_pct": "5.0"},  # |5.0| — biggest mover
    }

    async def _portfolio_get(path: str, **_kwargs):
        return _resp(200, members)

    async def _market_data_get(path: str, **_kwargs):
        if path.startswith("/internal/v1/price/"):
            iid = path.rsplit("/", 1)[-1]
            return _resp(200, quotes.get(iid, {}))
        return _resp(200, {})

    async def _nlp_get(_path: str, **_kwargs):
        return _resp(200, {"articles": []})

    async def _alert_get(_path: str, **_kwargs):
        return _resp(200, {"alerts": []})

    authed_mock_clients.portfolio.get = AsyncMock(side_effect=_portfolio_get)
    authed_mock_clients.market_data.get = AsyncMock(side_effect=_market_data_get)
    authed_mock_clients.nlp_pipeline.get = AsyncMock(side_effect=_nlp_get)
    authed_mock_clients.alert.get = AsyncMock(side_effect=_alert_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-sort/insights",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    tickers = [m["ticker"] for m in body["movers"]]
    # HIGH (|5.0|) → MID (|2.0|) → LOW (|0.5|)
    assert tickers == ["HIGH", "MID", "LOW"], f"Expected [HIGH, MID, LOW] sorted by |change_pct| DESC, got {tickers}"
