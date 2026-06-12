"""Tests for routes/signals.py — the NEWS MOMENTUM GET /v1/signals/ai feed.

Covers the 2026-06-12 Wave-4 pivot from extraction-confidence "AI signals" to a
``/news/top``-backed news-momentum feed:
- pure helpers: sentiment normalisation, publisher-from-URL derivation, item map
- happy path: S6 /news/top articles → momentum rows with honest relevance
- window selector: allowed windows pass through, out-of-set snaps to 72h default
- rows missing title/url are dropped
- limit trimming
- upstream S6 failure → status passthrough (never a fabricated 200)
- auth required
- route precedence: signals.py supersedes the legacy market.py handler
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from api_gateway.routes.signals import (
    _DEFAULT_WINDOW_HOURS,
    _normalise_sentiment,
    _source_from_url,
    _to_momentum_item,
)
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105


def _make_jwt() -> str:
    return jwt.encode({"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content.decode()
    resp.json.return_value = json.loads(content)
    return resp


def _article(**overrides: object) -> dict[str, object]:
    """One S6 /news/top article (the upstream shape this route consumes)."""
    base: dict[str, object] = {
        "article_id": "art-1",
        "title": "Nvidia Breaks Below $200",
        "url": "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html",
        "published_at": "2026-06-11T15:44:29Z",
        "source_name": None,
        "source_type": "eodhd_ticker_news",
        "routing_tier": "deep",
        "routing_score": 0.73,
        "market_impact_score": None,
        "llm_relevance_score": 0.9,
        "display_relevance_score": 0.83,
        "primary_entity_id": None,
        "primary_entity_symbol": None,
        "impact_windows": None,
        "sentiment": "negative",
        "impact_score": None,
    }
    base.update(overrides)
    return base


def _news_payload(articles: list[dict[str, object]]) -> bytes:
    return json.dumps({"articles": articles, "total": len(articles)}).encode()


async def _call(authed_app, params: str = "") -> httpx.Response:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/v1/signals/ai{params}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_normalise_sentiment_maps_known_values() -> None:
    assert _normalise_sentiment("positive") == "positive"
    assert _normalise_sentiment("NEGATIVE") == "negative"
    assert _normalise_sentiment("neutral") == "neutral"


def test_normalise_sentiment_collapses_mixed_and_unknown_to_neutral() -> None:
    """mixed / null / unrecognised → neutral so the direction dot is always defined."""
    assert _normalise_sentiment("mixed") == "neutral"
    assert _normalise_sentiment(None) == "neutral"
    assert _normalise_sentiment("") == "neutral"
    assert _normalise_sentiment("bullish-ish") == "neutral"


def test_source_from_url_strips_noise_prefixes_and_tld() -> None:
    assert _source_from_url("https://finance.yahoo.com/x", None) == "yahoo"
    assert _source_from_url("https://uk.finance.yahoo.com/x", None) == "yahoo"
    assert _source_from_url("https://www.fxstreet.com/news/abc", None) == "fxstreet"


def test_source_from_url_falls_back_when_no_url() -> None:
    """No URL → fall back to the (usually-null) source_name, else None."""
    assert _source_from_url(None, "Reuters") == "Reuters"
    assert _source_from_url(None, None) is None
    assert _source_from_url("not-a-url", "Reuters") == "Reuters"


def test_to_momentum_item_uses_real_relevance_not_confidence() -> None:
    """The headline number is display_relevance_score — never a fake confidence."""
    item = _to_momentum_item(_article(display_relevance_score=0.83, sentiment="negative"))
    assert item["relevance"] == 0.83
    assert item["sentiment"] == "negative"
    assert item["source"] == "yahoo"
    assert item["title"] == "Nvidia Breaks Below $200"
    assert item["url"].startswith("https://")


# ── Route behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_signals_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/ai")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_momentum_payload_shape(authed_app, authed_mock_clients) -> None:
    """Happy path: S6 /news/top articles → enriched news-momentum rows."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _news_payload(
                [
                    _article(article_id="art-1", display_relevance_score=0.83, sentiment="negative"),
                    _article(
                        article_id="art-2",
                        title="Frasers launches £1.7bn bid for Hugo Boss",
                        url="https://uk.finance.yahoo.com/news/frasers.html",
                        sentiment="positive",
                        display_relevance_score=0.80,
                    ),
                ],
            ),
        ),
    )

    resp = await _call(authed_app)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_hours"] == _DEFAULT_WINDOW_HOURS
    sigs = body["signals"]
    assert len(sigs) == 2
    assert sigs[0]["title"] == "Nvidia Breaks Below $200"
    assert sigs[0]["relevance"] == 0.83
    assert sigs[0]["sentiment"] == "negative"
    assert sigs[0]["source"] == "yahoo"
    assert sigs[1]["sentiment"] == "positive"
    assert sigs[1]["source"] == "yahoo"


@pytest.mark.asyncio
async def test_window_selector_allowed_values_pass_through(authed_app, authed_mock_clients) -> None:
    """?hours=24 / 168 reach S6 verbatim and are echoed in window_hours."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _news_payload([_article()])))

    for hours in (24, 72, 168):
        resp = await _call(authed_app, f"?hours={hours}")
        assert resp.json()["window_hours"] == hours
        call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
        assert call_kwargs["params"]["hours"] == hours


@pytest.mark.asyncio
async def test_window_selector_out_of_set_snaps_to_default(authed_app, authed_mock_clients) -> None:
    """An arbitrary ?hours=5 degrades to the safe 72h default, not passed through."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _news_payload([_article()])))

    resp = await _call(authed_app, "?hours=5")
    assert resp.json()["window_hours"] == _DEFAULT_WINDOW_HOURS
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert call_kwargs["params"]["hours"] == _DEFAULT_WINDOW_HOURS


@pytest.mark.asyncio
async def test_rows_missing_title_or_url_are_dropped(authed_app, authed_mock_clients) -> None:
    """A row the user can neither read nor open carries no momentum → dropped."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _news_payload(
                [
                    _article(article_id="ok", title="Real headline", url="https://x.com/a"),
                    _article(article_id="no-title", title=None),
                    _article(article_id="no-url", url=None),
                ],
            ),
        ),
    )

    resp = await _call(authed_app)
    sigs = resp.json()["signals"]
    assert [s["article_id"] for s in sigs] == ["ok"]


@pytest.mark.asyncio
async def test_limit_trims_and_is_forwarded(authed_app, authed_mock_clients) -> None:
    """?limit=2 → returns 2 rows and asks S6 for 2."""
    articles = [_article(article_id=f"a{i}", url=f"https://x.com/{i}") for i in range(6)]
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _news_payload(articles)))

    resp = await _call(authed_app, "?limit=2")
    assert len(resp.json()["signals"]) == 2
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert call_kwargs["params"]["limit"] == 2


@pytest.mark.asyncio
async def test_s6_error_passes_through(authed_app, authed_mock_clients) -> None:
    """Upstream S6 failure → status passthrough, never a fabricated 200."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(503, b'{"detail": "down"}'))
    resp = await _call(authed_app)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_route_supersedes_legacy_market_handler(authed_app) -> None:
    """Registration order: /v1/signals/ai must resolve to routes.signals.ai_signals.

    Guards the shadowing contract — if market_router is ever registered before
    signals_router the legacy un-enriched handler silently takes over.
    """
    for route in authed_app.routes:
        if getattr(route, "path", None) == "/v1/signals/ai":
            assert route.endpoint.__module__ == "api_gateway.routes.signals"
            break
    else:
        pytest.fail("/v1/signals/ai route not found")
