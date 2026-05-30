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
    # No sector_exposure → falls back to holdings-level HHI
    ctx.sector_exposure = None

    result = formatter.build_morning_risk_summary(ctx)
    assert result["concentration_score"] == 1.0


# FQA-03 / BP-627 regression — build_morning_risk_summary must surface the
# sector aggregates the gatherer already computed (was previously hardcoded
# to {} so every morning brief reported concentration_score=0.0 with empty
# sector_breakdown even when sector data was present in canonical_entities).


def test_build_morning_risk_summary_populates_sector_breakdown() -> None:
    """sector_breakdown must mirror ctx.sector_exposure.by_sector."""
    formatter = _make_formatter()

    sector_exposure = MagicMock()
    sector_exposure.by_sector = {"Technology": 0.65, "Energy": 0.20, "Financials": 0.15}

    ctx = MagicMock()
    ctx.portfolio = None  # sector path doesn't need portfolio
    ctx.sector_exposure = sector_exposure

    result = formatter.build_morning_risk_summary(ctx)
    # Sectors surfaced verbatim (cast to float)
    assert result["sector_breakdown"] == {
        "Technology": 0.65,
        "Energy": 0.20,
        "Financials": 0.15,
    }
    # Concentration is sector-HHI: 0.65² + 0.20² + 0.15² = 0.4225 + 0.04 + 0.0225
    assert result["concentration_score"] == pytest.approx(0.485, abs=1e-3)


def test_build_morning_risk_summary_sector_hhi_preferred_over_holdings_hhi() -> None:
    """When sectors are available, sector-HHI overrides holdings-HHI.

    10 holdings each at 10% weight across 10 different sectors should
    report a LOW concentration_score even though every position is
    individually 10% — what matters is sector concentration.
    """
    formatter = _make_formatter()

    # Holdings-level HHI of 10 equal weights = 0.1 (10 * 0.1²)
    holdings = []
    for _ in range(10):
        h = MagicMock()
        h.current_weight = 0.1
        holdings.append(h)
    portfolio = MagicMock()
    portfolio.holdings = holdings

    # Sectors equally split across 10 buckets → sector-HHI also = 0.1
    sector_exposure = MagicMock()
    sector_exposure.by_sector = {f"Sector{i}": 0.1 for i in range(10)}

    ctx = MagicMock()
    ctx.portfolio = portfolio
    ctx.sector_exposure = sector_exposure

    result = formatter.build_morning_risk_summary(ctx)
    # Sector-level HHI selected (10 equal sectors → 0.1)
    assert result["concentration_score"] == pytest.approx(0.1, abs=1e-3)
    assert len(result["sector_breakdown"]) == 10


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


# ── 11. PLAN-0102 W1 T-W1-01 / T-W1-02 — market overview renders tape + holdings


def test_format_market_overview_renders_tape_and_holdings() -> None:
    """format_market_overview must render BOTH indices (Tape) and holdings.

    PLAN-0102 W1 T-W1-01 (BP-614): the old formatter only rendered
    ``sector_performance`` and silently dropped per-holding quotes that the
    gatherer paid to fetch. The fix populates ``MarketOverview.indices``
    (SPY/QQQ/VIX) AND ``MarketOverview.holdings`` (per-holding quotes) — both
    must surface in the rendered string so the prompt can see them.
    """
    formatter = _make_formatter()

    # Each QuoteSummary stores the TICKER SYMBOL in instrument_id (the
    # gatherer remaps the UUID → ticker before construction).
    def _q(symbol: str, last: str) -> Any:
        q = MagicMock()
        q.instrument_id = symbol
        q.last = last
        return q

    mo = MagicMock()
    mo.indices = [_q("SPY", "485.20"), _q("QQQ", "418.10"), _q("VIX", "14.2")]
    mo.holdings = [_q("AAPL", "195.30"), _q("MSFT", "412.80")]
    mo.sector_performance = {}  # legacy field empty — assert it doesn't break

    ctx = MagicMock()
    ctx.market_overview = mo

    result = formatter.format_market_overview(ctx)
    # All 5 symbols from the synthetic batch must appear (this is the explicit
    # acceptance test from PLAN-0102 W1 T-W1-01).
    for symbol in ("SPY", "QQQ", "VIX", "AAPL", "MSFT"):
        assert symbol in result, f"expected {symbol} in formatter output, got:\n{result}"
    assert "Tape:" in result
    assert "Your Portfolio Today:" in result


def test_format_market_overview_holdings_only_no_tape_section() -> None:
    """When ``indices`` is empty, the formatter must NOT emit the Tape header.

    Quiet-day / degraded-tape path: if tape resolution failed upstream the
    holdings section should still render without a stray empty "Tape:" line.
    """
    formatter = _make_formatter()
    q = MagicMock()
    q.instrument_id = "AAPL"
    q.last = "195.30"

    mo = MagicMock()
    mo.indices = []
    mo.holdings = [q]
    mo.sector_performance = {}
    ctx = MagicMock()
    ctx.market_overview = mo

    result = formatter.format_market_overview(ctx)
    assert "Tape:" not in result
    assert "Your Portfolio Today:" in result
    assert "AAPL" in result


# ── PLAN-0102 W3 follow-up (T-W3-FU-03): tape + earnings formatters ──────────


def test_format_market_tape_renders_premkt_pct_and_vix_level() -> None:
    """T-W3-FU-03: synthetic MarketTapeResult renders 'SPY +0.20%, QQQ +0.45%, VIX 14.2'.

    Verifies the three primary code paths in a single shot:
      * premkt_pct present -> "SYM +X.XX%"
      * VIX-style (last_close only, no pct) -> "VIX 14.20"
      * any header markers ("Tape:") prefix the line so the LLM can route.
    """
    from datetime import UTC, datetime

    from rag_chat.application.ports.upstream_clients import MarketTapeItem, MarketTapeResult

    formatter = _make_formatter()

    tape = MarketTapeResult(
        as_of=datetime(2026, 5, 29, 12, 0, tzinfo=UTC),
        tickers=[
            MarketTapeItem(
                symbol="SPY",
                last_close=485.0,
                premkt_price=486.0,
                premkt_pct=0.20,
                session="pre-mkt",
            ),
            MarketTapeItem(
                symbol="QQQ",
                last_close=420.0,
                premkt_price=421.9,
                premkt_pct=0.45,
                session="pre-mkt",
            ),
            MarketTapeItem(
                symbol="VIX",
                last_close=14.2,
                premkt_price=None,
                premkt_pct=None,
                session="closed",
            ),
        ],
    )
    ctx = MagicMock()
    ctx.market_tape = tape
    ctx.gathered_at = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)

    result = formatter.format_market_tape(ctx)
    # WHY each substring: locks the per-row contract so a refactor that
    # silently drops one of the three rendering paths breaks loudly.
    assert "Tape:" in result, result
    assert "SPY +0.20%" in result, result
    assert "QQQ +0.45%" in result, result
    assert "VIX 14.20" in result, result


def test_format_market_tape_all_unavailable_renders_placeholder() -> None:
    """T-W3-FU-03: every row session='unavailable' -> graceful 'Tape data unavailable' placeholder.

    The placeholder MUST include the gathered_at date so on-call can spot
    stale-cache regressions.  No real ticker numbers leak through.
    """
    from datetime import UTC, datetime

    from rag_chat.application.ports.upstream_clients import MarketTapeItem, MarketTapeResult

    formatter = _make_formatter()
    tape = MarketTapeResult(
        as_of=datetime(2026, 5, 29, 12, 0, tzinfo=UTC),
        tickers=[
            MarketTapeItem(
                symbol="SPY",
                last_close=None,
                premkt_price=None,
                premkt_pct=None,
                session="unavailable",
            ),
            MarketTapeItem(
                symbol="QQQ",
                last_close=None,
                premkt_price=None,
                premkt_pct=None,
                session="unavailable",
            ),
        ],
    )
    ctx = MagicMock()
    ctx.market_tape = tape
    ctx.gathered_at = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)

    result = formatter.format_market_tape(ctx)
    assert result.startswith("Tape data unavailable"), result
    assert "2026-05-29" in result, result
    # Defensive: no ticker symbol bled through despite being in input rows.
    assert "SPY" not in result, result


def test_format_earnings_calendar_renders_event_in_window() -> None:
    """T-W3-FU-03: NVDA earnings next-Tuesday AMC renders under 'Macro Today'.

    Builds a fake event two days from "today" (UTC) so the 2-day window
    in format_earnings_calendar accepts it, then asserts the header,
    ticker, AMC marker, and consensus EPS all surface verbatim.
    """
    from datetime import UTC, date, datetime, timedelta

    from rag_chat.application.ports.upstream_clients import EarningsCalendarResult, EarningsEvent

    formatter = _make_formatter()
    today = datetime.now(tz=UTC).date()
    event_day = today + timedelta(days=2)
    cal = EarningsCalendarResult(
        from_date=today,
        to_date=today + timedelta(days=7),
        events=[
            EarningsEvent(
                symbol="NVDA",
                entity_id=None,
                report_date=event_day,
                when="AMC",
                period="Q1 FY2026",
                consensus_eps=0.74,
                consensus_rev_usd=None,
            )
        ],
    )
    ctx = MagicMock()
    ctx.earnings_calendar = cal
    ctx.gathered_at = datetime.now(tz=UTC)

    result = formatter.format_earnings_calendar(ctx)
    assert "Macro Today" in result, result
    assert "NVDA" in result, result
    assert "AMC" in result, result
    assert "$0.74" in result, result
    # Out-of-window guard — same calendar with the event pushed 30 days out
    # must render NOTHING.
    cal_far = EarningsCalendarResult(
        from_date=today,
        to_date=today + timedelta(days=60),
        events=[
            EarningsEvent(
                symbol="NVDA",
                entity_id=None,
                report_date=today + timedelta(days=30),
                when="AMC",
                period="Q1 FY2026",
                consensus_eps=0.74,
                consensus_rev_usd=None,
            )
        ],
    )
    ctx_far = MagicMock()
    ctx_far.earnings_calendar = cal_far
    ctx_far.gathered_at = datetime.now(tz=UTC)
    assert formatter.format_earnings_calendar(ctx_far) == "", "out-of-window event leaked through"
    _ = date  # silence unused-import linter on platforms where the import is needed only above
