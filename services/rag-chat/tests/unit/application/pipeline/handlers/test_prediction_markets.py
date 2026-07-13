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
async def test_handler_sets_non_null_entity_name_from_category() -> None:
    """BUG-1: entity_name MUST be non-null (BP-604/605) so entity-grounding does not refuse.

    The market's category is used as a stable subject label (title-cased).
    """
    brief = _FakeS3Brief([_market(category="politics")])
    items = await _handler(brief)._handle_get_prediction_markets(query="election")
    cm = items[0].citation_meta
    assert cm.entity_name is not None, "prediction-market entity_name must not be null (BP-604/605)"
    assert cm.entity_name == "Politics"


@pytest.mark.asyncio
async def test_handler_entity_name_non_null_when_category_missing() -> None:
    # The handler defaults a missing category to "uncategorized" upstream, so the
    # label is "Uncategorized" — the key BP-604/605 invariant is that it is NON-NULL.
    brief = _FakeS3Brief([_market(category=None)])
    items = await _handler(brief)._handle_get_prediction_markets(query="mystery")
    assert items[0].citation_meta.entity_name is not None
    assert items[0].citation_meta.entity_name == "Uncategorized"


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


# ── PLAN-0056 Wave E3: grounding_fields on the odds + volume ──────────────────


@pytest.mark.asyncio
async def test_grounding_fields_populated_with_odds_and_volume() -> None:
    """A 2-outcome market emits yes/no probability + volume_24h grounding entries.

    The probability values MUST match the integer-percent written in the prose
    (``Yes 63%``, ``No 37%``) — not the raw 0.63/0.37 fraction — so the value-
    substantiation gate can verify the cited odds.
    """
    brief = _FakeS3Brief([_market()])
    items = await _handler(brief)._handle_get_prediction_markets(query="Fed rate cut")
    gf = dict(items[0].grounding_fields)
    assert gf["yes_probability"] == "63"
    assert gf["no_probability"] == "37"
    assert gf["volume_24h"] == "1250000"
    assert gf["market_id"] == "0xabc123"


@pytest.mark.asyncio
async def test_grounding_probability_matches_percentage_in_text() -> None:
    """The grounding value is the SAME integer the ``NN%`` text cites (0.63 -> "63")."""
    brief = _FakeS3Brief([_market()])
    items = await _handler(brief)._handle_get_prediction_markets(query="Fed rate cut")
    item = items[0]
    gf = dict(item.grounding_fields)
    # The text renders "Yes 63%"; the grounding value is the bare "63".
    assert "Yes 63%" in item.text
    assert gf["yes_probability"] == "63"
    assert "No 37%" in item.text
    assert gf["no_probability"] == "37"


@pytest.mark.asyncio
async def test_grounding_fields_empty_safe_when_outcomes_missing() -> None:
    """A market with no usable outcomes must not crash — minimal grounding only."""
    brief = _FakeS3Brief([_market(outcomes=[], volume_24h=None)])
    items = await _handler(brief)._handle_get_prediction_markets(query="x")
    gf = dict(items[0].grounding_fields)
    # No probability / volume entries; only the market_id survives (non-crash).
    assert "yes_probability" not in gf
    assert "volume_24h" not in gf
    assert gf.get("market_id") == "0xabc123"


@pytest.mark.asyncio
async def test_grounding_fields_no_volume_entry_when_volume_absent() -> None:
    """Missing 24h volume → no ``volume_24h`` grounding entry (never a phantom 0)."""
    brief = _FakeS3Brief([_market(volume_24h=None)])
    items = await _handler(brief)._handle_get_prediction_markets(query="Fed rate cut")
    gf = dict(items[0].grounding_fields)
    assert "volume_24h" not in gf
    # Odds still grounded.
    assert gf["yes_probability"] == "63"


@pytest.mark.asyncio
async def test_grounding_fields_fully_empty_market_does_not_crash() -> None:
    """A market with neither outcomes, volume, nor id yields an empty tuple safely."""
    brief = _FakeS3Brief([_market(outcomes=None, volume_24h=None, market_id="")])
    items = await _handler(brief)._handle_get_prediction_markets(query="x")
    # Empty grounding tuple, no exception.
    assert items[0].grounding_fields == ()


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
