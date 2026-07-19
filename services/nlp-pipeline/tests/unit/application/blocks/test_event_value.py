"""Unit tests for the deterministic event-type VALUE signal (2026-07-18).

Verifies the signal:
  * detects the real gated-out examples (earnings / M&A / analyst / contract /
    ownership titles) that motivated the change,
  * does NOT fire on genuinely thin docs (promos, listicles, market colour),
  * honours the enable flag, category restriction, and min-hits threshold.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.blocks.event_value import (
    ALL_EVENT_CATEGORIES,
    detect_event_categories,
    has_high_value_event,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestDetectEventCategories:
    # Real / representative substantive-event titles → must fire, tagged by category.
    @pytest.mark.parametrize(
        ("title", "expected_category"),
        [
            # Earnings (the PulteGroup Q1 miss archetype).
            ("PulteGroup Q1 profit misses estimates on weaker orders", "earnings"),
            ("Netflix reports first-quarter earnings, beats revenue expectations", "earnings"),
            ("Acme Corp raises full-year guidance after strong quarterly results", "earnings"),
            ("Widget Inc EPS tops consensus, lifts outlook", "earnings"),
            # M&A / stake (the Nebius stake archetype).
            ("Nebius discloses 5% stake in AI startup", "m_and_a"),
            ("BigCo agrees to acquire SmallCo in $4 billion deal", "m_and_a"),
            ("Investor launches takeover bid for Target Ltd", "m_and_a"),
            ("Parent to spin-off its logistics unit", "m_and_a"),
            # Analyst.
            ("Morgan Stanley upgrades Tesla to overweight, raises price target", "analyst"),
            ("Analyst initiates coverage at buy rating", "analyst"),
            ("Goldman cuts target on Boeing, maintains hold", "analyst"),
            # Contract / award (the $186M Army contract archetype).
            ("Palantir wins $186M Army contract for data platform", "contract"),
            ("Lockheed awarded a contract worth $2 billion by the Pentagon", "contract"),
            # Ownership / insider.
            ("Activist investor files 13D, reports 8.2% stake", "ownership"),
            ("CEO insider buying disclosed in latest filing", "ownership"),
        ],
    )
    def test_substantive_events_detected(self, title: str, expected_category: str) -> None:
        matched = detect_event_categories(title)
        assert expected_category in matched, f"{title!r} → {matched}"

    # Thin / promo / listicle titles → must NOT fire (would be gated, correctly).
    @pytest.mark.parametrize(
        "title",
        [
            "10 Best Dividend Stocks to Buy Now",
            "3 Growth Stocks to Watch This Week",
            "Why I'm Bullish on the Market Right Now",
            "Top 5 Cheap Stocks Under $10",
            "Stock Market Today: Dow slips as investors weigh the week ahead",
            "How to Invest $1,000 in 2026",
            "The Ultimate Guide to Passive Income",
        ],
    )
    def test_thin_docs_not_detected(self, title: str) -> None:
        assert detect_event_categories(title) == frozenset()

    def test_empty_text_returns_empty(self) -> None:
        assert detect_event_categories("") == frozenset()
        assert detect_event_categories("   ") == frozenset()

    def test_category_restriction(self) -> None:
        title = "BigCo agrees to acquire SmallCo in $4 billion deal"
        # Full catalogue: M&A fires.
        assert "m_and_a" in detect_event_categories(title)
        # Restrict to only 'earnings' → the M&A signal is suppressed.
        assert detect_event_categories(title, categories=frozenset({"earnings"})) == frozenset()

    def test_unknown_categories_ignored(self) -> None:
        title = "Netflix reports first-quarter earnings"
        assert detect_event_categories(title, categories=frozenset({"earnings", "bogus"})) == frozenset({"earnings"})

    def test_all_categories_constant_matches_patterns(self) -> None:
        assert ALL_EVENT_CATEGORIES == frozenset({"earnings", "m_and_a", "analyst", "contract", "ownership"})


@pytest.mark.unit
class TestHasHighValueEvent:
    def test_disabled_always_false(self) -> None:
        assert has_high_value_event("Netflix reports Q1 earnings", None, enabled=False) is False

    def test_title_only_event(self) -> None:
        assert has_high_value_event("Palantir wins $186M Army contract", None, enabled=True) is True

    def test_body_head_event_when_title_thin(self) -> None:
        # Title is generic; the event lives in the lede body.
        assert (
            has_high_value_event(
                "Company update",
                "The board agreed to acquire a rival in an all-cash deal announced today.",
                enabled=True,
            )
            is True
        )

    def test_thin_doc_false(self) -> None:
        assert has_high_value_event("10 Best Stocks to Buy Now", "Here are our top picks.", enabled=True) is False

    def test_none_inputs_false(self) -> None:
        assert has_high_value_event(None, None, enabled=True) is False

    def test_scan_chars_limits_body(self) -> None:
        # The event keyword sits beyond the scan window → not seen.
        body = ("x" * 50) + " agrees to acquire a rival"
        assert has_high_value_event("Update", body, enabled=True, scan_chars=10) is False
        # Widen the window → seen.
        assert has_high_value_event("Update", body, enabled=True, scan_chars=200) is True

    def test_min_hits_threshold(self) -> None:
        # Single-category title.
        title = "Netflix reports first-quarter earnings"
        assert has_high_value_event(title, None, enabled=True, min_hits=1) is True
        # Requiring 2 distinct categories → the single-category doc no longer qualifies.
        assert has_high_value_event(title, None, enabled=True, min_hits=2) is False
        # A doc spanning earnings + M&A satisfies min_hits=2.
        multi = "AcquirerCo to acquire Target after reporting Q1 earnings beat"
        assert has_high_value_event(multi, None, enabled=True, min_hits=2) is True
