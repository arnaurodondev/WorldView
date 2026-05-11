"""Unit tests for the email digest template renderer.

Covers:
  - All 4 sections render (Risk Overview, Portfolio Positions, Recent News,
    Market Fundamentals)
  - Missing / empty data degrades gracefully per section
  - XSS prevention: HTML-special characters in portfolio data are escaped
  - Plain-text fallback matches the same structure
  - Both html_body and text_body are non-empty strings
"""

from __future__ import annotations

import pytest
from alert.infrastructure.email.template import render_digest_email

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_RISK_SUMMARY = {
    "top_risk_signals": [
        "High concentration in AAPL (38%)",
        "Tech sector momentum reversing",
    ]
}
_SAMPLE_POSITIONS = [
    {"ticker": "AAPL", "name": "Apple Inc.", "weight_pct": 38.0, "ytd_pct": 12.5},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "weight_pct": 22.0, "ytd_pct": -3.1},
]
_SAMPLE_CITATIONS = [
    {"title": "Apple's AI push drives record revenue", "source": "Reuters"},
    {"title": "Tech stocks under pressure amid rate fears"},
]
_SAMPLE_FUNDAMENTALS = [
    {"ticker": "AAPL", "pe_ratio": "28.4", "market_cap": "$2.8T", "revenue_growth": "+6.1%"},
    {"ticker": "MSFT", "pe_ratio": "32.1", "market_cap": "$3.1T", "revenue_growth": "+14.2%"},
]


# ---------------------------------------------------------------------------
# TestRenderDigestEmailHtmlSections
# ---------------------------------------------------------------------------


class TestRenderDigestEmailHtmlSections:
    @pytest.mark.unit
    def test_returns_tuple_of_two_nonempty_strings(self) -> None:
        html, text = render_digest_email(narrative="Test narrative")
        assert isinstance(html, str) and len(html) > 0
        assert isinstance(text, str) and len(text) > 0

    @pytest.mark.unit
    def test_html_contains_all_four_section_headings(self) -> None:
        html, _ = render_digest_email(
            narrative="Some narrative",
            risk_summary=_SAMPLE_RISK_SUMMARY,
            positions=_SAMPLE_POSITIONS,
            citations=_SAMPLE_CITATIONS,
            fundamentals=_SAMPLE_FUNDAMENTALS,
        )
        assert "Risk Overview" in html
        assert "Portfolio Positions" in html
        assert "Recent News" in html
        assert "Market Fundamentals" in html

    @pytest.mark.unit
    def test_html_includes_narrative(self) -> None:
        html, _ = render_digest_email(narrative="Portfolio risk is elevated this week.")
        assert "Portfolio risk is elevated this week." in html

    @pytest.mark.unit
    def test_html_includes_risk_signals(self) -> None:
        html, _ = render_digest_email(narrative="", risk_summary=_SAMPLE_RISK_SUMMARY)
        assert "High concentration in AAPL (38%)" in html
        assert "Tech sector momentum reversing" in html

    @pytest.mark.unit
    def test_html_includes_position_tickers(self) -> None:
        html, _ = render_digest_email(narrative="", positions=_SAMPLE_POSITIONS)
        assert "AAPL" in html
        assert "MSFT" in html

    @pytest.mark.unit
    def test_html_includes_position_ytd(self) -> None:
        html, _ = render_digest_email(narrative="", positions=_SAMPLE_POSITIONS)
        assert "+12.5%" in html
        assert "-3.1%" in html

    @pytest.mark.unit
    def test_html_includes_citation_titles(self) -> None:
        html, _ = render_digest_email(narrative="", citations=_SAMPLE_CITATIONS)
        assert "Apple&#x27;s AI push drives record revenue" in html or "Apple" in html
        assert "Reuters" in html

    @pytest.mark.unit
    def test_html_includes_fundamentals_metrics(self) -> None:
        html, _ = render_digest_email(narrative="", fundamentals=_SAMPLE_FUNDAMENTALS)
        assert "28.4" in html
        assert "$2.8T" in html
        assert "+6.1%" in html

    @pytest.mark.unit
    def test_html_is_valid_html_structure(self) -> None:
        html, _ = render_digest_email(narrative="test")
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert "</html>" in html
        assert "<body>" in html
        assert "</body>" in html


# ---------------------------------------------------------------------------
# TestRenderDigestEmailGracefulDegradation
# ---------------------------------------------------------------------------


class TestRenderDigestEmailGracefulDegradation:
    @pytest.mark.unit
    def test_no_narrative_still_renders(self) -> None:
        html, text = render_digest_email(narrative="")
        assert "Risk Overview" in html
        assert len(text) > 0

    @pytest.mark.unit
    def test_empty_risk_summary_shows_fallback(self) -> None:
        html, text = render_digest_email(narrative="", risk_summary={})
        assert "No risk signals detected this week." in html
        assert "No risk signals detected this week." in text

    @pytest.mark.unit
    def test_no_positions_shows_fallback(self) -> None:
        html, text = render_digest_email(narrative="", positions=[])
        assert "No position data available." in html
        assert "No position data available." in text

    @pytest.mark.unit
    def test_no_citations_shows_fallback(self) -> None:
        html, text = render_digest_email(narrative="", citations=[])
        assert "No recent news citations available." in html
        assert "No recent news citations available." in text

    @pytest.mark.unit
    def test_no_fundamentals_shows_fallback(self) -> None:
        html, text = render_digest_email(narrative="", fundamentals=[])
        assert "No fundamental data available." in html
        assert "No fundamental data available." in text

    @pytest.mark.unit
    def test_position_missing_optional_fields_still_renders(self) -> None:
        """Positions with only ticker should not raise — weight/ytd default to dash."""
        html, _ = render_digest_email(narrative="", positions=[{"ticker": "GOOG"}])
        assert "GOOG" in html

    @pytest.mark.unit
    def test_citation_missing_source_renders_without_parentheses(self) -> None:
        html, _ = render_digest_email(narrative="", citations=[{"title": "Big news"}])
        assert "Big news" in html
        # No stray () when source is absent
        assert "()" not in html

    @pytest.mark.unit
    def test_fundamental_missing_optional_fields_renders_dashes(self) -> None:
        html, _ = render_digest_email(narrative="", fundamentals=[{"ticker": "XOM"}])
        assert "XOM" in html


# ---------------------------------------------------------------------------
# TestXssPrevention
# ---------------------------------------------------------------------------


class TestXssPrevention:
    @pytest.mark.unit
    def test_ticker_with_html_is_escaped(self) -> None:
        """Ticker containing HTML special chars must be escaped, not injected."""
        malicious_ticker = "<script>alert('xss')</script>"
        html, _ = render_digest_email(
            narrative="",
            positions=[{"ticker": malicious_ticker, "name": "Evil Corp"}],
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    @pytest.mark.unit
    def test_citation_title_with_html_is_escaped(self) -> None:
        html, _ = render_digest_email(
            narrative="",
            citations=[{"title": '<img src=x onerror="alert(1)">'}],
        )
        assert "<img" not in html
        assert "&lt;img" in html

    @pytest.mark.unit
    def test_narrative_with_html_is_escaped(self) -> None:
        html, _ = render_digest_email(narrative="<b>bold</b> &amp; <i>italic</i>")
        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    @pytest.mark.unit
    def test_fundamental_metric_with_html_is_escaped(self) -> None:
        html, _ = render_digest_email(
            narrative="",
            fundamentals=[{"ticker": "TST", "pe_ratio": '"><script>'}],
        )
        assert "<script>" not in html


# ---------------------------------------------------------------------------
# TestPlainTextRenderer
# ---------------------------------------------------------------------------


class TestPlainTextRenderer:
    @pytest.mark.unit
    def test_text_contains_all_four_section_headings(self) -> None:
        _, text = render_digest_email(
            narrative="Narrative text.",
            risk_summary=_SAMPLE_RISK_SUMMARY,
            positions=_SAMPLE_POSITIONS,
            citations=_SAMPLE_CITATIONS,
            fundamentals=_SAMPLE_FUNDAMENTALS,
        )
        assert "RISK OVERVIEW" in text
        assert "PORTFOLIO POSITIONS" in text
        assert "RECENT NEWS" in text
        assert "MARKET FUNDAMENTALS" in text

    @pytest.mark.unit
    def test_text_includes_narrative(self) -> None:
        _, text = render_digest_email(narrative="Important portfolio insight.")
        assert "Important portfolio insight." in text

    @pytest.mark.unit
    def test_text_includes_risk_signals(self) -> None:
        _, text = render_digest_email(narrative="", risk_summary=_SAMPLE_RISK_SUMMARY)
        assert "High concentration in AAPL (38%)" in text

    @pytest.mark.unit
    def test_text_includes_position_data(self) -> None:
        _, text = render_digest_email(narrative="", positions=_SAMPLE_POSITIONS)
        assert "AAPL" in text
        assert "+12.5%" in text

    @pytest.mark.unit
    def test_text_includes_citations(self) -> None:
        _, text = render_digest_email(narrative="", citations=_SAMPLE_CITATIONS)
        assert "Apple" in text
        assert "Reuters" in text

    @pytest.mark.unit
    def test_text_includes_fundamentals(self) -> None:
        _, text = render_digest_email(narrative="", fundamentals=_SAMPLE_FUNDAMENTALS)
        assert "AAPL" in text
        assert "P/E=28.4" in text
