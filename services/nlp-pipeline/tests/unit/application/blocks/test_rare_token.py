"""Unit tests for the pure rare-token analyzer (PLAN-0063 W5-3 T-02).

The analyzer is purely functional — these tests pass literal strings in,
get a `RareTokenAnalysis` out, and never need a Valkey or DB fixture.
"""

from __future__ import annotations

from nlp_pipeline.application.blocks.rare_token import analyze


def test_analyze_detects_prd_id() -> None:
    """PRD/PLAN/FR/BP/OQ/ADR/REQ/SEC IDs always count as rare."""
    result = analyze("What does PRD-0034 say about retrieval?")
    assert result.has_rare_token is True
    assert "prd_id" in result.classes_matched
    assert result.rare_token_count >= 1


def test_analyze_detects_filing_type() -> None:
    """SEC filing types like ``8-K`` are rare regardless of context."""
    result = analyze("Show 8-K filings for Apple")
    assert result.has_rare_token is True
    assert "filing_type" in result.classes_matched


def test_analyze_ticker_uses_predicate() -> None:
    """When a predicate is supplied, only tokens it confirms count as tickers."""

    def is_aapl(sym: str) -> bool:
        return sym == "AAPL"

    matched = analyze("Tell me about AAPL", is_known_ticker=is_aapl)
    assert matched.has_rare_token is True
    assert "ticker" in matched.classes_matched

    # Predicate returns False → no ticker class. The query has no other rare
    # token shape so the result is "no rare tokens".
    not_matched = analyze("Tell me about AAPL", is_known_ticker=lambda _s: False)
    assert "ticker" not in not_matched.classes_matched


def test_analyze_stop_list_excludes_common_uppercase() -> None:
    """Without a predicate, the stop-list filters out CEO/IPO/USA/...."""
    result = analyze("Talk to the CEO about IPO timing in the USA")
    # None of CEO/IPO/USA should count as a ticker → result has no ticker class.
    assert "ticker" not in result.classes_matched
    # And, importantly, the analyzer does not raise.


def test_analyze_no_rare_tokens() -> None:
    """A plain English question with no identifiers → no rare tokens."""
    result = analyze("What is the gross margin?")
    assert result.has_rare_token is False
    assert result.rare_token_count == 0
    assert result.classes_matched == []


def test_analyze_traceback_fragment() -> None:
    """A python error name in the query should fire `python_error`."""
    result = analyze("I see a TypeError in the logs")
    assert result.has_rare_token is True
    assert "python_error" in result.classes_matched


def test_analyze_pure_no_globals() -> None:
    """Same input → same output regardless of call order."""
    inputs = [
        "What is the gross margin?",
        "PRD-0034 design",
        "Tell me about AAPL",
        "Just plain English here",
    ]
    first_pass = [analyze(q) for q in inputs]
    second_pass = [analyze(q) for q in reversed(inputs)]
    second_pass.reverse()
    assert first_pass == second_pass


def test_analyze_camelcase() -> None:
    """Multi-hump CamelCase identifiers count as rare (likely a class name)."""
    result = analyze("How does ParallelRetrievalOrchestrator work?")
    assert result.has_rare_token is True
    assert "camelcase" in result.classes_matched


def test_analyze_screaming_snake_constant() -> None:
    """SCREAMING_SNAKE constants of length ≥ 4 are rare."""
    result = analyze("DEFAULT_TIMEOUT seems wrong")
    assert result.has_rare_token is True
    assert "screaming_snake" in result.classes_matched


def test_analyze_iso_date_and_quarter() -> None:
    """ISO dates and quarter labels both count."""
    result = analyze("What changed between 2024-Q3 and 2024-09-30?")
    assert result.has_rare_token is True
    assert "quarter" in result.classes_matched
    assert "iso_date" in result.classes_matched


def test_analyze_isin_pattern() -> None:
    """A 12-char ISIN like US0378331005 (Apple) fires the isin class."""
    result = analyze("What about US0378331005?")
    assert result.has_rare_token is True
    assert "isin" in result.classes_matched


def test_analyze_empty_string() -> None:
    """Empty input must not raise; returns the all-False result."""
    result = analyze("")
    assert result.has_rare_token is False
    assert result.rare_token_count == 0
