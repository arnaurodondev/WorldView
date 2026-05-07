"""Unit tests for TrustScorer (PLAN-0079 Wave A)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from rag_chat.application.pipeline.trust_scorer import _DEFAULT_CORROBORATION, TrustScorer
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem, compute_recency_score
from rag_chat.domain.enums import ItemType

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_scorer(**kwargs: float) -> TrustScorer:
    """Build a TrustScorer, optionally overriding weights."""
    return TrustScorer(**kwargs)  # type: ignore[arg-type]


def _make_item(
    source_type: str,
    published_at: datetime,
    trust_weight: float,
    score: float = 0.8,
    extraction_confidence: float | None = None,
) -> RetrievedItem:
    """Create a RetrievedItem using the factory."""
    return RetrievedItem.create(
        item_id="test-id",
        item_type=ItemType.chunk,
        text="Sample text",
        score=score,
        trust_weight=trust_weight,
        citation_meta=CitationMeta(
            title=None,
            url=None,
            source_name=source_type,
            published_at=published_at,
            entity_name=None,
        ),
        published_at=published_at,
        source_type=source_type,
        extraction_confidence=extraction_confidence,
    )


# ── test cases ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sec_10k_beats_general_news() -> None:
    """SEC 10-K should score higher than general news for same evidence and confidence."""
    scorer = _make_scorer()
    sec_score = scorer.score("sec_10k", extraction_confidence=0.7, evidence_count=0)
    news_score = scorer.score("eodhd_news", extraction_confidence=0.7, evidence_count=0)
    assert sec_score > news_score, f"Expected sec_10k ({sec_score:.4f}) > eodhd_news ({news_score:.4f})"


@pytest.mark.unit
def test_unknown_source_gets_default() -> None:
    """source_type not in SOURCE_AUTHORITY should fall back to default authority (0.5)."""
    scorer = _make_scorer()
    score_unknown = scorer.score("totally_unknown_source_xyz", extraction_confidence=0.5, evidence_count=0)
    score_default = scorer.score("default", extraction_confidence=0.5, evidence_count=0)
    assert score_unknown == pytest.approx(
        score_default, abs=1e-9
    ), "Unknown source type must use the same authority as 'default'"


@pytest.mark.unit
def test_high_extraction_confidence_beats_low() -> None:
    """Higher extraction_confidence should produce a higher trust score, all else equal."""
    scorer = _make_scorer()
    high = scorer.score("eodhd_news", extraction_confidence=0.9, evidence_count=3)
    low = scorer.score("eodhd_news", extraction_confidence=0.3, evidence_count=3)
    assert high > low, f"Expected high conf ({high:.4f}) > low conf ({low:.4f})"


@pytest.mark.unit
def test_corroboration_factor_zero_evidence() -> None:
    """evidence_count=0 should yield the _DEFAULT_CORROBORATION factor (0.5)."""
    # We can verify this by calling the static method directly.
    factor = TrustScorer._corroboration_factor(0)
    assert factor == pytest.approx(
        _DEFAULT_CORROBORATION, abs=1e-9
    ), f"Expected default corroboration {_DEFAULT_CORROBORATION} but got {factor}"


@pytest.mark.unit
def test_corroboration_factor_saturates() -> None:
    """evidence_count=15 should produce a corroboration factor close to 1.0 (saturation)."""
    factor = TrustScorer._corroboration_factor(15)
    expected = 1.0 - math.exp(-15 / 3.0)
    assert factor == pytest.approx(expected, abs=1e-9)
    assert factor > 0.99, f"Expected saturation near 1.0 at count=15, got {factor:.4f}"


@pytest.mark.unit
def test_score_clamped_to_unit_interval() -> None:
    """TrustScorer.score must always return a value in [0, 1]."""
    scorer = TrustScorer(w_source=2.0, w_corroboration=2.0, w_extraction=2.0)
    # Extreme weights could push above 1 — must be clamped
    result = scorer.score("sec_10k", extraction_confidence=1.0, evidence_count=100)
    assert 0.0 <= result <= 1.0, f"Score {result} outside [0, 1]"

    # Edge: very low weights
    scorer_low = TrustScorer(w_source=0.0, w_corroboration=0.0, w_extraction=0.0)
    result_low = scorer_low.score("sec_10k", extraction_confidence=0.0, evidence_count=0)
    assert 0.0 <= result_low <= 1.0, f"Score {result_low} outside [0, 1]"


@pytest.mark.unit
def test_none_source_type() -> None:
    """source_type=None should be treated the same as 'default'."""
    scorer = _make_scorer()
    score_none = scorer.score(None, extraction_confidence=0.5, evidence_count=0)
    score_default = scorer.score("default", extraction_confidence=0.5, evidence_count=0)
    assert score_none == pytest.approx(score_default, abs=1e-9), "None source_type must yield same trust as 'default'"


@pytest.mark.unit
def test_custom_weights() -> None:
    """Non-default weights should change the trust score compared to default weights."""
    source_type = "sec_10k"
    extraction_confidence = 0.7
    evidence_count = 0

    default_scorer = TrustScorer()
    custom_scorer = TrustScorer(w_source=0.8, w_corroboration=0.05, w_extraction=0.05)

    default_score = default_scorer.score(source_type, extraction_confidence, evidence_count)
    custom_score = custom_scorer.score(source_type, extraction_confidence, evidence_count)

    # Custom scorer has much higher w_source (0.8 vs 0.4) → higher score for a
    # high-authority source like sec_10k
    assert custom_score > default_score, (
        f"Custom scorer ({custom_score:.4f}) should beat default ({default_score:.4f}) "
        "for sec_10k with higher w_source"
    )


@pytest.mark.unit
def test_recent_sec_10k_beats_old_sec_10k_via_recency() -> None:
    """A recent 10-K should produce a higher composed score (score * recency * trust) than a 5-year-old one.

    This validates the composition of TrustScorer with the existing recency pipeline
    (compute_recency_score from PLAN-0063 W5-4). Both items receive identical trust_weight
    from TrustScorer; the recent item wins via the recency_score factor.
    """
    scorer = TrustScorer()
    trust_weight = scorer.score("sec_10k", extraction_confidence=None, evidence_count=0)

    now = datetime.now(tz=UTC)
    yesterday = now - timedelta(days=1)
    five_years_ago = now - timedelta(days=365 * 5)

    # Compute how the pipeline produces the final fusion value:
    #   fusion_score = score * recency_score * trust_weight
    # (RetrievedItem.create() does this automatically — we replicate the logic here
    #  to show the composed behavior without storing to DB or needing full fixtures.)
    base_score = 0.8

    recent_recency = compute_recency_score(yesterday, source_type="sec_10k")
    old_recency = compute_recency_score(five_years_ago, source_type="sec_10k")

    recent_fusion = base_score * recent_recency * trust_weight
    old_fusion = base_score * old_recency * trust_weight

    assert recent_fusion > old_fusion, (
        f"Recent 10-K fusion ({recent_fusion:.6f}) should beat 5-year-old " f"10-K fusion ({old_fusion:.6f})"
    )


@pytest.mark.unit
def test_extraction_confidence_field_on_retrieved_item() -> None:
    """extraction_confidence propagates through RetrievedItem.create() without altering fusion_score."""
    now = datetime.now(tz=UTC)
    item_with_conf = _make_item("sec_10k", now, trust_weight=0.8, extraction_confidence=0.9)
    item_no_conf = _make_item("sec_10k", now, trust_weight=0.8, extraction_confidence=None)

    # Both items should have same fusion_score since extraction_confidence is informational only
    assert item_with_conf.fusion_score == pytest.approx(
        item_no_conf.fusion_score, abs=1e-9
    ), "extraction_confidence must not affect fusion_score (informational field only)"
    assert item_with_conf.extraction_confidence == pytest.approx(0.9, abs=1e-9)
    assert item_no_conf.extraction_confidence is None
