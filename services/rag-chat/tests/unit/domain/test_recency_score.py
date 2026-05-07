"""Unit tests for source-aware compute_recency_score — PLAN-0063 W5-4 T-W5-4-01."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit


class TestSourceSpecificRecencyScore:
    def test_sec_filing_1_year_old_above_0_83(self) -> None:
        """SEC filing 365 days old → recency_score ≥ 0.83 (rate=0.0005 keeps filings relevant for years)."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC) - timedelta(days=365)
        score = compute_recency_score(published, source_type="sec_filing")
        assert score >= 0.83, f"expected ≥0.83, got {score:.4f}"

    def test_news_30_days_old_below_0_55(self) -> None:
        """eodhd_news 30 days old → recency_score < 0.55 (rate=0.02 decays news quickly)."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC) - timedelta(days=30)
        score = compute_recency_score(published, source_type="eodhd_news")
        assert score < 0.55, f"expected <0.55, got {score:.4f}"

    def test_unknown_source_uses_default_rate(self) -> None:
        """source_type=None or unknown string → falls back to default 0.005 rate."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC) - timedelta(days=100)
        expected = math.exp(-0.005 * 100)

        assert abs(compute_recency_score(published, source_type=None) - expected) < 1e-6
        assert abs(compute_recency_score(published, source_type="totally_unknown") - expected) < 1e-6

    def test_zero_days_old_returns_1(self) -> None:
        """Freshly published document (same day) → score == 1.0."""
        from rag_chat.domain.entities.chat import compute_recency_score

        # Use now() directly — days_old = 0 → exp(0) = 1.0
        score = compute_recency_score(datetime.now(tz=UTC), source_type="eodhd_news")
        assert score == pytest.approx(1.0)

    def test_published_at_none_returns_half(self) -> None:
        """None published_at → neutral 0.5 regardless of source_type."""
        from rag_chat.domain.entities.chat import compute_recency_score

        assert compute_recency_score(None) == 0.5
        assert compute_recency_score(None, source_type="sec_filing") == 0.5
        assert compute_recency_score(None, source_type="eodhd_news") == 0.5

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetime (no tzinfo) is treated as UTC — no exception raised."""
        from rag_chat.domain.entities.chat import compute_recency_score

        naive = datetime.now() - timedelta(days=10)  # noqa: DTZ005
        assert naive.tzinfo is None
        score = compute_recency_score(naive, source_type="finnhub_news")
        expected = math.exp(-0.02 * 10)
        assert abs(score - expected) < 1e-4

    def test_future_dated_doc_clamped_to_zero_days(self) -> None:
        """published_at in the future → days_old clamped to 0 → score == 1.0."""
        from rag_chat.domain.entities.chat import compute_recency_score

        future = datetime.now(tz=UTC) + timedelta(days=30)
        score = compute_recency_score(future, source_type="press_release")
        assert score == pytest.approx(1.0)

    def test_earnings_transcript_decays_faster_than_sec_filing(self) -> None:
        """Same age: earnings_transcript score < sec_filing score (0.001 > 0.0005 rate)."""
        from rag_chat.domain.entities.chat import compute_recency_score

        published = datetime.now(tz=UTC) - timedelta(days=180)
        sec_score = compute_recency_score(published, source_type="sec_filing")
        transcript_score = compute_recency_score(published, source_type="earnings_transcript")
        assert (
            transcript_score < sec_score
        ), f"transcript ({transcript_score:.4f}) should be < sec_filing ({sec_score:.4f})"
