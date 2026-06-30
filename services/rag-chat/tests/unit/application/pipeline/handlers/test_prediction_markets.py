"""Chat prediction-market tool — handler + canonical Polymarket URL construction.

Covers the new ``get_prediction_markets`` tool (MarketHandler):

  * ``_build_polymarket_url`` mirrors the frontend ``buildPolymarketUrl`` helper
    (clean slug → ``/event/<slug>``; empty/whitespace → title-search fallback;
    malformed numeric-tail slug → title-search fallback).
  * The handler returns ONE RetrievedItem per market, each carrying a clickable
    ``citation_meta.url``, ``source_name="polymarket"``, the question as title,
    and a parsed ``published_at`` from ``updated_at``.
  * R9 safe degradation: missing port / upstream error / empty result → [].
  * Input normalisation: bad ``status`` → "open"; ``limit`` clamped to 1-50;
    blank ``query``/``category`` dropped before the upstream call.
"""

from __future__ import annotations

from typing import Any

import pytest
from rag_chat.application.pipeline.handlers.market import (
    MarketHandler,
    _build_polymarket_url,
)
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


# ── Fake S3BriefPort double ───────────────────────────────────────────────────


class _FakeS3Brief:
    """Records the kwargs it was called with and returns a canned market list."""

    def __init__(self, markets: list[dict[str, Any]] | Exception) -> None:
        self._markets = markets
        self.calls: list[dict[str, Any]] = []

    async def get_prediction_markets(
        self,
        query: str | None,
        category: str | None,
        status: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append({"query": query, "category": category, "status": status, "limit": limit})
        if isinstance(self._markets, Exception):
            raise self._markets
        return self._markets


def _market(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "market_id": "0xabc123",
        "question": "Will the Fed cut rates in March 2026?",
        "outcomes": [
            {"name": "Yes", "token_id": "t1", "price": 0.63},
            {"name": "No", "token_id": "t2", "price": 0.37},
        ],
        "volume_24h": 1_250_000.0,
        "close_time": "2026-03-20T00:00:00Z",
        "resolution_status": "open",
        "market_slug": "will-the-fed-cut-rates-in-march-2026",
        "category": "macro",
        "updated_at": "2026-06-28T12:00:00Z",
    }
    base.update(overrides)
    return base


def _handler(brief: Any) -> MarketHandler:
    return MarketHandler(s3=None, s3_brief=brief, timeout=5.0)


# ── URL builder (mirrors apps/worldview-web/lib/prediction-markets.ts) ─────────


def test_url_clean_slug_builds_event_deep_link() -> None:
    url = _build_polymarket_url("will-the-fed-cut-rates", "Will the Fed cut rates?")
    assert url == "https://polymarket.com/event/will-the-fed-cut-rates"


@pytest.mark.parametrize("slug", [None, "", "   "])
def test_url_empty_slug_falls_back_to_title_search(slug: str | None) -> None:
    url = _build_polymarket_url(slug, "Fed rate cut?")
    assert url == "https://polymarket.com/markets?_q=Fed%20rate%20cut%3F"


def test_url_malformed_numeric_tail_slug_falls_back_to_search() -> None:
    # Three+ trailing numeric segments = the corruption pattern → /event/ 404s.
    url = _build_polymarket_url("some-market-143-229-513-574", "Some Market")
    assert url == "https://polymarket.com/markets?_q=Some%20Market"


def test_url_single_trailing_number_is_kept_as_deep_link() -> None:
    # A legitimate slug ending in one year/number must NOT be misclassified.
    url = _build_polymarket_url("election-winner-by-2024", "Election winner by 2024")
    assert url == "https://polymarket.com/event/election-winner-by-2024"


# ── Handler happy path ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_returns_one_item_per_market_with_clickable_url() -> None:
    brief = _FakeS3Brief([_market()])
    items = await _handler(brief)._handle_get_prediction_markets(query="Fed rate cut")

    assert len(items) == 1
    item = items[0]
    assert item.item_type is ItemType.financial
    # Canonical deep link from market_slug.
    assert item.citation_meta.url == "https://polymarket.com/event/will-the-fed-cut-rates-in-march-2026"
    assert item.citation_meta.source_name == "polymarket"
    assert item.citation_meta.title == "Will the Fed cut rates in March 2026?"
    # published_at parsed from updated_at (tz-aware UTC).
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None
    # Implied odds rendered into the LLM-facing text.
    assert "Yes 63%" in item.text
    assert "No 37%" in item.text
    assert "Polymarket" in item.text


@pytest.mark.asyncio
async def test_handler_null_slug_market_uses_search_fallback_url() -> None:
    brief = _FakeS3Brief([_market(market_slug=None, question="Mystery market")])
    items = await _handler(brief)._handle_get_prediction_markets()
    assert items[0].citation_meta.url == "https://polymarket.com/markets?_q=Mystery%20market"


@pytest.mark.asyncio
async def test_handler_normalises_status_and_clamps_limit_and_drops_blank_query() -> None:
    brief = _FakeS3Brief([_market()])
    await _handler(brief)._handle_get_prediction_markets(
        query="   ",
        category="  ",
        status="bogus",
        limit=999,
    )
    assert brief.calls == [{"query": None, "category": None, "status": "open", "limit": 50}]


# ── R9 safe degradation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_missing_port_returns_empty() -> None:
    items = await _handler(None)._handle_get_prediction_markets(query="x")
    assert items == []


@pytest.mark.asyncio
async def test_handler_upstream_error_returns_empty() -> None:
    brief = _FakeS3Brief(RuntimeError("upstream 500"))
    items = await _handler(brief)._handle_get_prediction_markets(query="x")
    assert items == []


@pytest.mark.asyncio
async def test_handler_no_markets_returns_empty() -> None:
    brief = _FakeS3Brief([])
    items = await _handler(brief)._handle_get_prediction_markets(query="x")
    assert items == []
