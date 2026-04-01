"""Unit tests for build_fundamentals_narrative() utility (T-D-3-12)."""

from __future__ import annotations

import pytest
from knowledge_graph.application.utils.fundamentals_narrative import (
    _gross_margin_word,
    _net_margin_word,
    _pe_word,
    _price_position_word,
    _revenue_size,
    build_fundamentals_narrative,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Deterministic output test
# ---------------------------------------------------------------------------


class TestBuildFundamentalsNarrativeDeterminism:
    def test_same_input_same_output(self) -> None:
        """Same inputs must always produce identical output (deterministic)."""
        kwargs = {
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "revenue_usd_millions": 390_000.0,
            "gross_margin_pct": 44.5,
            "net_margin_pct": 25.3,
            "pe_ratio": 28.0,
            "price": 189.0,
            "week_52_high": 200.0,
            "week_52_low": 130.0,
        }
        result1 = build_fundamentals_narrative(**kwargs)
        result2 = build_fundamentals_narrative(**kwargs)
        assert result1 == result2

    def test_header_always_present(self) -> None:
        result = build_fundamentals_narrative("Foo Corp", "financial_instrument")
        assert "Foo Corp" in result
        assert "financial_instrument" in result

    def test_no_financial_data_fallback(self) -> None:
        result = build_fundamentals_narrative("X", "org")
        assert "No financial data available" in result

    def test_full_narrative_contains_all_sections(self) -> None:
        result = build_fundamentals_narrative(
            "Test Corp",
            "financial_instrument",
            revenue_usd_millions=50_000.0,
            gross_margin_pct=35.0,
            net_margin_pct=8.0,
            pe_ratio=20.0,
            price=50.0,
            week_52_high=60.0,
            week_52_low=40.0,
        )
        assert "Revenue" in result
        assert "Gross Margin" in result
        assert "Net Margin" in result
        assert "P/E" in result
        assert "Price" in result
        assert "52-week" in result

    def test_description_included_when_provided(self) -> None:
        result = build_fundamentals_narrative(
            "Tech Co", "financial_instrument", description="Leading software company."
        )
        assert "Leading software company." in result

    def test_price_without_range(self) -> None:
        result = build_fundamentals_narrative("X", "org", price=42.5)
        assert "42.50" in result


# ---------------------------------------------------------------------------
# Interpretive word helpers
# ---------------------------------------------------------------------------


class TestRevenueSize:
    def test_large_cap(self) -> None:
        assert _revenue_size(150.0) == "large-cap"

    def test_mid_cap(self) -> None:
        assert _revenue_size(25.0) == "mid-cap"

    def test_small_cap(self) -> None:
        assert _revenue_size(2.0) == "small-cap"

    def test_micro_cap(self) -> None:
        assert _revenue_size(0.5) == "micro-cap"


class TestGrossMarginWord:
    def test_strong(self) -> None:
        assert _gross_margin_word(50.0) == "strong"

    def test_moderate(self) -> None:
        assert _gross_margin_word(30.0) == "moderate"

    def test_weak(self) -> None:
        assert _gross_margin_word(10.0) == "weak"

    def test_boundary_strong(self) -> None:
        assert _gross_margin_word(40.0) == "strong"

    def test_boundary_moderate(self) -> None:
        assert _gross_margin_word(20.0) == "moderate"


class TestNetMarginWord:
    def test_highly_profitable(self) -> None:
        assert _net_margin_word(25.0) == "highly profitable"

    def test_profitable(self) -> None:
        assert _net_margin_word(15.0) == "profitable"

    def test_marginally_profitable(self) -> None:
        assert _net_margin_word(5.0) == "marginally profitable"

    def test_zero_margin(self) -> None:
        assert _net_margin_word(0.0) == "marginally profitable"

    def test_unprofitable(self) -> None:
        assert _net_margin_word(-5.0) == "unprofitable"


class TestPeWord:
    def test_negative_earnings(self) -> None:
        assert _pe_word(-10.0) == "negative earnings"

    def test_expensive(self) -> None:
        assert _pe_word(35.0) == "expensive"

    def test_fairly_valued(self) -> None:
        assert _pe_word(20.0) == "fairly valued"

    def test_cheap(self) -> None:
        assert _pe_word(10.0) == "cheap"

    def test_boundary_expensive(self) -> None:
        assert _pe_word(30.0) == "fairly valued"  # not > 30


class TestPricePositionWord:
    def test_near_highs(self) -> None:
        assert _price_position_word(195.0, 100.0, 200.0) == "near highs"

    def test_near_lows(self) -> None:
        assert _price_position_word(105.0, 100.0, 200.0) == "near lows"

    def test_mid_range(self) -> None:
        assert _price_position_word(150.0, 100.0, 200.0) == "mid-range"

    def test_degenerate_range(self) -> None:
        # high == low → mid-range (no ZeroDivisionError)
        assert _price_position_word(100.0, 100.0, 100.0) == "mid-range"
