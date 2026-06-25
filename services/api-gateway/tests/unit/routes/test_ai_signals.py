"""Tests for routes/signals.py — the NEWS MOMENTUM GET /v1/signals/ai feed.

Covers the PLAN-0099 W4 per-entity momentum feed (proxies S6
``/news/trending-entities``):
- pure helpers: sentiment normalisation, momentum-row mapping
- happy path: S6 entity rows → momentum rows with ticker/name/trend/headline
- window selector: allowed windows pass through, out-of-set snaps to 24h default
- rows without a ticker are dropped
- limit trimming + forwarding
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
    _to_momentum_row,
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


def _entity(**overrides: object) -> dict[str, object]:
    """One S6 /news/trending-entities row (the upstream shape this route consumes)."""
    base: dict[str, object] = {
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "ticker": "NVDA",
        "name": "Nvidia",
        "count": 6,
        "prior_count": 2,
        "delta": 4,
        "delta_pct": 200.0,
        "top_article": {
            "id": "art-1",
            "title": "Nvidia Breaks Below $200",
            "url": "https://finance.yahoo.com/markets/stocks/articles/nvidia-200.html",
            "source": "yahoo",
            "published_at": "2026-06-11T15:44:29Z",
            "sentiment": "negative",
            "relevance": 0.83,
        },
    }
    base.update(overrides)
    return base


def _payload(entities: list[dict[str, object]], window_hours: int = 24) -> bytes:
    return json.dumps({"entities": entities, "window_hours": window_hours}).encode()


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


def test_to_momentum_row_carries_trend_and_honest_relevance() -> None:
    """The row carries the momentum fields + an honest display_relevance_score."""
    row = _to_momentum_row(_entity())
    assert row is not None
    assert row["ticker"] == "NVDA"
    assert row["name"] == "Nvidia"
    assert row["count"] == 6
    assert row["prior_count"] == 2
    assert row["delta"] == 4
    assert row["delta_pct"] == 200.0
    assert row["top_article"]["relevance"] == 0.83
    assert row["top_article"]["sentiment"] == "negative"
    assert row["top_article"]["source"] == "yahoo"


def test_to_momentum_row_drops_entity_without_ticker() -> None:
    """A row with no ticker (macro noise) carries nowhere to navigate → dropped."""
    assert _to_momentum_row(_entity(ticker=None)) is None
    assert _to_momentum_row(_entity(ticker="")) is None


def test_to_momentum_row_tolerates_missing_top_article() -> None:
    """A null top_article degrades to a row with a neutral, empty headline."""
    row = _to_momentum_row(_entity(top_article=None))
    assert row is not None
    assert row["top_article"]["sentiment"] == "neutral"
    assert row["top_article"]["title"] is None


# ── Route behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_signals_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/ai")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_momentum_payload_shape(authed_app, authed_mock_clients) -> None:
    """Happy path: S6 trending entities → momentum rows under the ``signals`` key."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _payload(
                [
                    _entity(ticker="NVDA", name="Nvidia", delta_pct=200.0),
                    _entity(
                        entity_id="22222222-2222-2222-2222-222222222222",
                        ticker="TSLA",
                        name="Tesla Inc",
                        count=4,
                        prior_count=0,
                        delta=4,
                        delta_pct=400.0,
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
    assert sigs[0]["ticker"] == "NVDA"
    assert sigs[0]["delta_pct"] == 200.0
    assert sigs[1]["ticker"] == "TSLA"
    assert sigs[1]["delta_pct"] == 400.0


@pytest.mark.asyncio
async def test_window_selector_allowed_values_pass_through(authed_app, authed_mock_clients) -> None:
    """?hours=24 / 72 / 168 reach S6 verbatim and are echoed in window_hours."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _payload([_entity()])))

    for hours in (24, 72, 168):
        resp = await _call(authed_app, f"?hours={hours}")
        assert resp.json()["window_hours"] == hours
        call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
        assert call_kwargs["params"]["window_hours"] == hours


@pytest.mark.asyncio
async def test_window_selector_out_of_set_snaps_to_default(authed_app, authed_mock_clients) -> None:
    """An arbitrary ?hours=5 degrades to the safe 24h default, not passed through."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _payload([_entity()])))

    resp = await _call(authed_app, "?hours=5")
    assert resp.json()["window_hours"] == _DEFAULT_WINDOW_HOURS
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert call_kwargs["params"]["window_hours"] == _DEFAULT_WINDOW_HOURS


@pytest.mark.asyncio
async def test_rows_without_ticker_are_dropped(authed_app, authed_mock_clients) -> None:
    """Macro noise (no ticker) is dropped even if S6 leaks one through."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _payload(
                [
                    _entity(ticker="AAPL"),
                    _entity(ticker=None),
                ],
            ),
        ),
    )

    resp = await _call(authed_app)
    sigs = resp.json()["signals"]
    assert [s["ticker"] for s in sigs] == ["AAPL"]


@pytest.mark.asyncio
async def test_limit_trims_and_is_forwarded(authed_app, authed_mock_clients) -> None:
    """?limit=2 → returns 2 rows and asks S6 for 2."""
    entities = [_entity(entity_id=f"e{i}", ticker=f"T{i}") for i in range(6)]
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _payload(entities)))

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
    """Registration order: /v1/signals/ai must resolve to routes.signals.ai_signals."""
    for route in authed_app.routes:
        if getattr(route, "path", None) == "/v1/signals/ai":
            assert route.endpoint.__module__ == "api_gateway.routes.signals"
            break
    else:
        pytest.fail("/v1/signals/ai route not found")
