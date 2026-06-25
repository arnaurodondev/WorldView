"""Unit tests for GetTrendingEntitiesUseCase (NEWS MOMENTUM ranking, PLAN-0099 W4).

Covers the use-case logic that the SQL layer does NOT: the cross-database
ticker join, the macro-noise (no-ticker) filter, the min-count floor, and the
momentum (delta_pct) ranking + tie-break.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from nlp_pipeline.application.ports.trending_entities import TrendingEntityRow
from nlp_pipeline.application.use_cases.trending_entities import GetTrendingEntitiesUseCase

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _row(entity_id, count, prior_count, *, relevance=0.5) -> TrendingEntityRow:
    return TrendingEntityRow(
        entity_id=entity_id,
        count=count,
        prior_count=prior_count,
        top_article_id=uuid4(),
        top_article_title="Headline",
        top_article_url="https://finance.yahoo.com/news/x",
        top_article_published_at=_NOW,
        top_article_sentiment="positive",
        top_article_relevance=relevance,
    )


def _canonical(entity_id, ticker, name="Co"):
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "entity_type": "financial_instrument",
        "isin": None,
        "ticker": ticker,
        "exchange": None,
    }


async def _run(rows, canonical, *, window_hours=24, limit=30, min_count=2):
    trending_repo = AsyncMock()
    trending_repo.get_trending_entities = AsyncMock(return_value=rows)
    canonical_repo = AsyncMock()
    canonical_repo.batch_get = AsyncMock(return_value=canonical)
    return await GetTrendingEntitiesUseCase().execute(
        trending_repo=trending_repo,
        canonical_repo=canonical_repo,
        window_hours=window_hours,
        limit=limit,
        min_count=min_count,
    )


@pytest.mark.asyncio
async def test_drops_entities_without_ticker() -> None:
    """Macro noise (no ticker) must be filtered out — only tradeable names remain."""
    e_ticker, e_noise = uuid4(), uuid4()
    rows = [_row(e_ticker, 5, 1), _row(e_noise, 9, 1)]
    canonical = {
        e_ticker: _canonical(e_ticker, "NVDA", "Nvidia"),
        e_noise: _canonical(e_noise, None, "NASDAQ"),  # no ticker -> dropped
    }
    out = await _run(rows, canonical)
    assert [r.ticker for r in out] == ["NVDA"]


@pytest.mark.asyncio
async def test_drops_empty_string_ticker() -> None:
    """An empty-string ticker is treated as no ticker (data hygiene)."""
    e = uuid4()
    out = await _run([_row(e, 5, 1)], {e: _canonical(e, "  ")})
    assert out == []


@pytest.mark.asyncio
async def test_min_count_floor_excludes_blips() -> None:
    """An entity below the min-count floor is excluded even with a huge surge."""
    e = uuid4()
    rows = [_row(e, 1, 0)]  # 0->1: +100% surge but only 1 article
    out = await _run(rows, {e: _canonical(e, "AAPL")}, min_count=2)
    assert out == []


@pytest.mark.asyncio
async def test_ranks_by_delta_pct_then_count() -> None:
    """Surge (delta_pct) ranks first; ties break by raw count DESC."""
    big_surge, small_surge, tie_a, tie_b = uuid4(), uuid4(), uuid4(), uuid4()
    rows = [
        _row(big_surge, 6, 1),  # delta_pct = 500
        _row(small_surge, 3, 2),  # delta_pct = 50
        _row(tie_a, 4, 1),  # delta_pct = 300, count 4
        _row(tie_b, 8, 2),  # delta_pct = 300, count 8 -> ranks above tie_a
    ]
    canonical = {
        big_surge: _canonical(big_surge, "A"),
        small_surge: _canonical(small_surge, "B"),
        tie_a: _canonical(tie_a, "C"),
        tie_b: _canonical(tie_b, "D"),
    }
    out = await _run(rows, canonical)
    assert [r.ticker for r in out] == ["A", "D", "C", "B"]
    # Verify delta/delta_pct math on the leader.
    leader = out[0]
    assert leader.delta == 5
    assert leader.delta_pct == 500.0


@pytest.mark.asyncio
async def test_zero_prior_uses_floor_denominator() -> None:
    """A 0->N jump yields N*100% (denominator floored at 1), never +inf."""
    e = uuid4()
    out = await _run([_row(e, 4, 0)], {e: _canonical(e, "TSLA")})
    assert out[0].delta_pct == 400.0
    assert out[0].prior_count == 0


@pytest.mark.asyncio
async def test_limit_truncates() -> None:
    """The result is truncated to ``limit`` after ranking."""
    rows, canonical = [], {}
    for i in range(5):
        e = uuid4()
        rows.append(_row(e, 5 + i, 1))
        canonical[e] = _canonical(e, f"T{i}")
    out = await _run(rows, canonical, limit=3)
    assert len(out) == 3


@pytest.mark.asyncio
async def test_empty_aggregation_returns_empty() -> None:
    """No candidate rows -> empty result, no canonical lookup needed."""
    out = await _run([], {})
    assert out == []
