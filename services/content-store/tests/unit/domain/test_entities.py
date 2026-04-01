"""Unit tests for domain entities."""

from __future__ import annotations

import pytest
from content_store.domain.entities import (
    CanonicalDocument,
    CorroborationPolicy,
    DeduplicationDecision,
    DedupThresholds,
    EntityMention,
    MinHashSignature,
    get_thresholds,
)
from content_store.domain.enums import DedupOutcome, DocumentStatus, SourceType

pytestmark = pytest.mark.unit


# ── DedupThresholds ────────────────────────────────────────────────────────────


class TestDedupThresholds:
    def test_valid_thresholds(self) -> None:
        t = DedupThresholds(hard=0.85, soft=0.70)
        assert t.hard == 0.85
        assert t.soft == 0.70

    def test_equal_thresholds(self) -> None:
        t = DedupThresholds(hard=0.80, soft=0.80)
        assert t.hard == t.soft

    def test_invalid_soft_greater_than_hard(self) -> None:
        with pytest.raises(ValueError, match="Invalid thresholds"):
            DedupThresholds(hard=0.50, soft=0.70)

    def test_frozen(self) -> None:
        t = DedupThresholds(hard=0.85, soft=0.70)
        with pytest.raises(AttributeError):
            t.hard = 0.90  # type: ignore[misc]

    def test_get_thresholds_news(self) -> None:
        t = get_thresholds(SourceType.EODHD)
        assert t.hard == 0.72
        assert t.soft == 0.55

    def test_get_thresholds_filings(self) -> None:
        t = get_thresholds(SourceType.SEC_EDGAR)
        assert t.hard == 0.85
        assert t.soft == 0.70

    def test_get_thresholds_finnhub(self) -> None:
        t = get_thresholds(SourceType.FINNHUB)
        assert t.hard == 0.75
        assert t.soft == 0.60

    def test_get_thresholds_unknown_defaults_to_news(self) -> None:
        t = get_thresholds("unknown_source")
        assert t.hard == 0.72
        assert t.soft == 0.55


# ── CorroborationPolicy ───────────────────────────────────────────────────────


class TestCorroborationPolicy:
    """Tests the decision matrix from PRD §6.7 Block 2."""

    @pytest.fixture
    def news_thresholds(self) -> DedupThresholds:
        return DedupThresholds(hard=0.72, soft=0.55)

    @pytest.fixture
    def filings_thresholds(self) -> DedupThresholds:
        return DedupThresholds(hard=0.85, soft=0.70)

    def test_same_source_above_hard_is_duplicate(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.80, same_source=True, thresholds=news_thresholds)
        assert result == DedupOutcome.SAME_SOURCE_DUPLICATE

    def test_different_source_above_hard_is_corroborating(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.80, same_source=False, thresholds=news_thresholds)
        assert result == DedupOutcome.CORROBORATING

    def test_between_soft_and_hard_is_semantic_near_dup(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.60, same_source=True, thresholds=news_thresholds)
        assert result == DedupOutcome.SEMANTIC_NEAR_DUPLICATE

    def test_below_soft_is_unique(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.40, same_source=False, thresholds=news_thresholds)
        assert result == DedupOutcome.UNIQUE

    def test_exact_hard_threshold_same_source(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.72, same_source=True, thresholds=news_thresholds)
        assert result == DedupOutcome.SAME_SOURCE_DUPLICATE

    def test_exact_soft_threshold(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.55, same_source=False, thresholds=news_thresholds)
        assert result == DedupOutcome.SEMANTIC_NEAR_DUPLICATE

    def test_just_below_soft_is_unique(self, news_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.5499, same_source=False, thresholds=news_thresholds)
        assert result == DedupOutcome.UNIQUE

    def test_filings_higher_hard_threshold(self, filings_thresholds: DedupThresholds) -> None:
        # 0.80 is below filings hard (0.85) but above soft (0.70)
        result = CorroborationPolicy.classify(0.80, same_source=False, thresholds=filings_thresholds)
        assert result == DedupOutcome.SEMANTIC_NEAR_DUPLICATE

    def test_filings_above_hard_corroborating(self, filings_thresholds: DedupThresholds) -> None:
        result = CorroborationPolicy.classify(0.90, same_source=False, thresholds=filings_thresholds)
        assert result == DedupOutcome.CORROBORATING


# ── DeduplicationDecision ──────────────────────────────────────────────────────


class TestDeduplicationDecision:
    def test_frozen(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_a")
        with pytest.raises(AttributeError):
            d.outcome = DedupOutcome.CORROBORATING  # type: ignore[misc]

    def test_suppressed_exact_dup(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.DUPLICATE_EXACT, stage="stage_a")
        assert d.is_suppressed is True

    def test_suppressed_normalized_dup(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.DUPLICATE_NORMALIZED, stage="stage_b")
        assert d.is_suppressed is True

    def test_suppressed_same_source(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.SAME_SOURCE_DUPLICATE, stage="stage_c")
        assert d.is_suppressed is True

    def test_not_suppressed_unique(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")
        assert d.is_suppressed is False

    def test_not_suppressed_corroborating(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.CORROBORATING, jaccard_score=0.85, stage="stage_c")
        assert d.is_suppressed is False

    def test_not_suppressed_semantic_near_dup(self) -> None:
        d = DeduplicationDecision(outcome=DedupOutcome.SEMANTIC_NEAR_DUPLICATE, stage="stage_c")
        assert d.is_suppressed is False


# ── CanonicalDocument ──────────────────────────────────────────────────────────


class TestCanonicalDocument:
    def test_defaults(self) -> None:
        doc = CanonicalDocument()
        assert doc.id is not None
        assert doc.status == DocumentStatus.PROCESSING
        assert doc.dedup_result == DedupOutcome.UNIQUE
        assert doc.language == "en"
        assert doc.is_backfill is False
        assert doc.corroborates_doc_id is None
        assert doc.minio_silver_key is None

    def test_custom_values(self) -> None:
        doc = CanonicalDocument(
            source_type="eodhd",
            title="Test Article",
            content_hash="abc123",
            normalized_hash="def456",
            word_count=500,
        )
        assert doc.source_type == "eodhd"
        assert doc.title == "Test Article"
        assert doc.word_count == 500


# ── MinHashSignature ───────────────────────────────────────────────────────────


class TestMinHashSignature:
    def test_signature_must_be_list_int(self) -> None:
        sig = MinHashSignature(signature=[1, 2, 3, 4])
        assert all(isinstance(v, int) for v in sig.signature)

    def test_invalid_signature_type_raises(self) -> None:
        with pytest.raises(TypeError, match="must contain only int"):
            MinHashSignature(signature=[1.5, 2.5])  # type: ignore[list-item]

    def test_frozen(self) -> None:
        sig = MinHashSignature(signature=[1, 2, 3])
        with pytest.raises(AttributeError):
            sig.shingle_type = "other"  # type: ignore[misc]

    def test_default_shingle_type(self) -> None:
        sig = MinHashSignature()
        assert sig.shingle_type == "word_bigram_char3gram"

    def test_empty_signature_allowed(self) -> None:
        sig = MinHashSignature(signature=[])
        assert sig.signature == []


# ── EntityMention ──────────────────────────────────────────────────────────────


class TestEntityMention:
    def test_frozen(self) -> None:
        m = EntityMention(mention_text_hash=12345, mention_text="Apple Inc.")
        with pytest.raises(AttributeError):
            m.mention_text = "other"  # type: ignore[misc]

    def test_entity_id_defaults_to_none(self) -> None:
        m = EntityMention()
        assert m.entity_id is None
        assert m.resolution_status == "UNRESOLVED"

    def test_no_fk_constraint_on_entity_id(self) -> None:
        """entity_id is a logical FK — no Postgres constraint."""
        m = EntityMention(entity_id=None)
        assert m.entity_id is None
