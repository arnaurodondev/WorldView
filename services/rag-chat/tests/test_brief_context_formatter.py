"""Unit tests for BriefContextFormatter (PLAN-0089 C-3).

Covers: format_portfolio_morning, format_news, format_events, format_alerts,
format_market_overview, format_entity_context, format_fundamentals,
format_relationships, build_morning_risk_summary, build_citations,
extract_entity_mentions, and None/empty input handling.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from rag_chat.application.use_cases.brief_context_formatter import BriefContextFormatter

pytestmark = pytest.mark.unit


def _make_formatter() -> BriefContextFormatter:
    return BriefContextFormatter()


# ── 1. test_format_with_all_data ──────────────────────────────────────────────


def test_format_news_with_articles() -> None:
    """format_news emits [c1] prefixes and article title for each article."""
    formatter = _make_formatter()

    article = MagicMock()
    article.title = "Apple beats Q4"
    article.published_at = date(2026, 5, 10)
    article.display_relevance_score = 0.9
    article.url = "https://example.com/apple"

    ctx = MagicMock()
    ctx.news_articles = [article]

    result = formatter.format_news(ctx, citation_offset=0)
    assert "[c1]" in result
    assert "Apple beats Q4" in result
    assert "2026-05-10" in result


def test_format_events_with_citation_offset() -> None:
    """format_events uses citation_offset to continue numbering from news."""
    formatter = _make_formatter()

    ev = MagicMock()
    ev.event_type = "EARNINGS"
    ev.event_text = "EPS beat by 12%"
    ev.event_date = date(2026, 5, 9)

    ctx = MagicMock()
    ctx.recent_events = [ev]

    result = formatter.format_events(ctx, citation_offset=3)
    # Should start at c4 (offset 3 + index 0 + 1)
    assert "[c4]" in result
    assert "EARNINGS" in result


def test_format_with_all_data_portfolio_morning() -> None:
    """format_portfolio_morning produces lines for holdings and watchlist."""
    formatter = _make_formatter()

    holding = MagicMock()
    holding.canonical_name = "Apple Inc."
    holding.ticker = "AAPL"
    holding.quantity = 100
    holding.current_weight = 0.25

    watchlist_item = MagicMock()
    watchlist_item.canonical_name = "Tesla Inc."
    watchlist_item.ticker = "TSLA"

    portfolio = MagicMock()
    portfolio.holdings = [holding]
    portfolio.watchlist = [watchlist_item]
    portfolio.total_positions = 1

    ctx = MagicMock()
    ctx.portfolio = portfolio

    result = formatter.format_portfolio_morning(ctx)
    assert "Apple Inc." in result
    assert "25.0%" in result
    assert "Tesla Inc." in result


# ── 2. test_format_with_missing_fundamentals ──────────────────────────────────


def test_format_with_missing_fundamentals_returns_empty() -> None:
    """format_fundamentals returns '' when ctx.fundamentals is None."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.fundamentals = None
    assert formatter.format_fundamentals(ctx) == ""


def test_format_fundamentals_with_data() -> None:
    """format_fundamentals formats market cap and margins correctly."""
    formatter = _make_formatter()

    data = {
        "MarketCapitalization": 2_800_000_000_000,  # $2.8T
        "ProfitMargin": 0.2543,
        "PERatio": 28.5,
    }
    fundamentals = MagicMock()
    fundamentals.data = data

    ctx = MagicMock()
    ctx.fundamentals = fundamentals

    result = formatter.format_fundamentals(ctx)
    assert "$2.80T" in result
    assert "25.4%" in result
    assert "28.5" in result


# ── 3. test_format_context_truncation ─────────────────────────────────────────


def test_format_news_caps_at_8_articles() -> None:
    """format_news renders at most get_news_limit() (default 12) articles.

    PLAN-0099 Wave B raised the cap from 8 to 12 and made it env-var
    overridable (RAG_CHAT_BRIEF_NEWS_LIMIT). Test name kept stable to
    preserve git history; assertion bumped to the new default.
    """
    formatter = _make_formatter()

    articles = []
    # Distinct titles so _dedupe_news doesn't collapse them.
    for i in range(20):
        a = MagicMock()
        a.title = f"Distinct article number {i} about company {i}"
        a.published_at = date(2026, 5, 1)
        a.display_relevance_score = 0.5
        a.url = None
        articles.append(a)

    ctx = MagicMock()
    ctx.news_articles = articles

    result = formatter.format_news(ctx, citation_offset=0)
    # Default cap is 12 → [c1]..[c12] but not [c13].
    assert "[c12]" in result
    assert "[c13]" not in result


def test_format_events_caps_at_6_events() -> None:
    """format_events renders at most get_events_limit() (default 10) events.

    PLAN-0099 Wave B raised the cap from 6 to 10. Test name kept stable to
    preserve git history; assertion bumped to the new default.
    """
    formatter = _make_formatter()

    events = []
    for i in range(15):
        ev = MagicMock()
        ev.event_type = f"TYPE_{i}"
        ev.event_text = "text"
        ev.event_date = date(2026, 5, 1)
        events.append(ev)

    ctx = MagicMock()
    ctx.recent_events = events

    result = formatter.format_events(ctx, citation_offset=0)
    assert "[c10]" in result
    assert "[c11]" not in result


# ── 4. test_format_empty_articles ─────────────────────────────────────────────


def test_format_empty_articles_returns_empty_string() -> None:
    """format_news returns '' when news_articles list is empty."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.news_articles = []
    assert formatter.format_news(ctx) == ""


def test_format_news_none_ctx_returns_empty() -> None:
    """format_news returns '' when ctx is None."""
    formatter = _make_formatter()
    assert formatter.format_news(None) == ""


# ── 5. test_format_missing_entity_data ────────────────────────────────────────


def test_format_entity_context_no_graph_returns_empty() -> None:
    """format_entity_context returns '' when ctx.entity_graph is None."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.entity_graph = None
    assert formatter.format_entity_context(ctx) == ""


def test_format_relationships_no_relationships_returns_empty() -> None:
    """format_relationships returns '' when entity_graph has no relationships."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.entity_graph = MagicMock()
    ctx.entity_graph.relationships = []
    assert formatter.format_relationships(ctx) == ""


def test_format_entity_context_with_data() -> None:
    """format_entity_context produces entity name, type, and ticker lines."""
    formatter = _make_formatter()
    eg = MagicMock()
    eg.canonical_name = "Apple Inc."
    eg.entity_type = "company"
    eg.ticker = "AAPL"

    ctx = MagicMock()
    ctx.entity_graph = eg

    result = formatter.format_entity_context(ctx)
    assert "Apple Inc." in result
    assert "company" in result
    assert "AAPL" in result


# ── 6. test_format_market_context_included ────────────────────────────────────


def test_format_market_context_included() -> None:
    """format_market_overview includes sector performance data."""
    formatter = _make_formatter()
    mo = MagicMock()
    mo.sector_performance = {"Technology": 0.025, "Energy": -0.012}

    ctx = MagicMock()
    ctx.market_overview = mo

    result = formatter.format_market_overview(ctx)
    assert "Sector performance" in result
    assert "Technology" in result
    assert "Energy" in result


def test_format_market_overview_none_returns_empty() -> None:
    """format_market_overview returns '' when ctx.market_overview is None."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.market_overview = None
    assert formatter.format_market_overview(ctx) == ""


# ── 7. build_citations ────────────────────────────────────────────────────────


def test_build_citations_none_ctx_returns_empty() -> None:
    """build_citations returns [] when ctx is None."""
    formatter = _make_formatter()
    assert formatter.build_citations(None) == []


def test_build_citations_includes_source_id_and_document_id() -> None:
    """build_citations emits both source_id (legacy) and document_id (canonical)."""
    formatter = _make_formatter()

    article = MagicMock()
    article.article_id = "art-abc"
    article.title = "Article Title"
    article.url = "https://example.com"
    article.summary = "Summary"

    ctx = MagicMock()
    ctx.news_articles = [article]
    ctx.recent_events = []
    ctx.active_alerts = []

    citations = formatter.build_citations(ctx)
    assert len(citations) == 1
    assert citations[0]["source_id"] == "art-abc"
    assert citations[0]["document_id"] == "art-abc"
    assert citations[0]["source_type"] == "article"


# ── 8. extract_entity_mentions ────────────────────────────────────────────────


def test_extract_entity_mentions_none_ctx() -> None:
    """extract_entity_mentions returns [] when ctx is None."""
    formatter = _make_formatter()
    assert formatter.extract_entity_mentions(None) == []


def test_extract_entity_mentions_deduplicates() -> None:
    """extract_entity_mentions deduplicates by entity_id (first occurrence wins)."""
    formatter = _make_formatter()

    h1 = MagicMock()
    h1.entity_id = "eid-1"
    h1.canonical_name = "Apple Inc."
    h1.ticker = "AAPL"

    h2 = MagicMock()
    h2.entity_id = "eid-1"  # same entity_id — should be deduped
    h2.canonical_name = "Apple Inc."
    h2.ticker = "AAPL"

    portfolio = MagicMock()
    portfolio.holdings = [h1, h2]
    portfolio.watchlist = []

    ctx = MagicMock()
    ctx.portfolio = portfolio
    ctx.entity_graph = None

    mentions = formatter.extract_entity_mentions(ctx)
    assert len(mentions) == 1
    assert mentions[0]["entity_id"] == "eid-1"


# ── 9. build_morning_risk_summary ─────────────────────────────────────────────


def test_build_morning_risk_summary_no_portfolio_returns_zero() -> None:
    """build_morning_risk_summary returns 0.0 concentration when no portfolio."""
    formatter = _make_formatter()
    ctx = MagicMock()
    ctx.portfolio = None
    result = formatter.build_morning_risk_summary(ctx)
    assert result["concentration_score"] == 0.0


def test_build_morning_risk_summary_single_holding_max_concentration() -> None:
    """A portfolio with one holding at 100% weight should yield HHI = 1.0."""
    formatter = _make_formatter()

    holding = MagicMock()
    holding.current_weight = 1.0  # 100% in one position

    portfolio = MagicMock()
    portfolio.holdings = [holding]

    ctx = MagicMock()
    ctx.portfolio = portfolio

    result = formatter.build_morning_risk_summary(ctx)
    assert result["concentration_score"] == 1.0


# ── 10. _fmt_usd_billions and _fmt_percent helpers ───────────────────────────


def test_fmt_usd_billions_trillions() -> None:
    """_fmt_usd_billions formats values ≥ 1T as '$X.XXT'."""
    formatter = _make_formatter()
    assert formatter._fmt_usd_billions(2_800_000_000_000) == "$2.80T"


def test_fmt_usd_billions_billions() -> None:
    """_fmt_usd_billions formats values in the billions range as '$X.XXB'."""
    formatter = _make_formatter()
    assert formatter._fmt_usd_billions(5_000_000_000) == "$5.00B"


def test_fmt_percent_formats_correctly() -> None:
    """_fmt_percent converts decimal ratio to percentage string."""
    formatter = _make_formatter()
    assert formatter._fmt_percent(0.2543) == "25.4%"
    assert formatter._fmt_percent(-0.05) == "-5.0%"


def test_fmt_percent_invalid_returns_str() -> None:
    """_fmt_percent handles non-numeric input gracefully."""
    formatter = _make_formatter()
    result = formatter._fmt_percent("not-a-number")
    assert result == "not-a-number"
