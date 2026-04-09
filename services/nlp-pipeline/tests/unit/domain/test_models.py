"""Unit tests for S6 domain models (T-C-1-05)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome, RoutingTier
from nlp_pipeline.domain.errors import PriceImpactError
from nlp_pipeline.domain.models import (
    ArticlePriceImpact,
    Chunk,
    DocumentEntityStats,
    DocumentSourceMetadata,
    EmbeddingPendingEntry,
    EntityMention,
    MentionResolution,
    NLPDocument,
    RoutingDecision,
    Section,
    SignalEvent,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(tz=UTC)


@pytest.mark.unit
class TestSection:
    def test_construction(self) -> None:
        doc_id = _uuid()
        sec = Section(
            section_id=_uuid(),
            doc_id=doc_id,
            section_index=0,
            char_start=0,
            char_end=100,
            text="Hello world",
            section_type="body",
        )
        assert sec.doc_id == doc_id
        assert sec.section_index == 0
        assert sec.speaker is None

    def test_frozen(self) -> None:
        sec = Section(section_id=_uuid(), doc_id=_uuid(), section_index=0, char_start=0, char_end=10, text="x")
        with pytest.raises(AttributeError):
            sec.section_index = 99  # type: ignore[misc]

    def test_speaker_field(self) -> None:
        sec = Section(
            section_id=_uuid(),
            doc_id=_uuid(),
            section_index=1,
            char_start=0,
            char_end=50,
            text="Transcript text",
            section_type="speaker_turn",
            speaker="CEO",
        )
        assert sec.speaker == "CEO"
        assert sec.section_type == "speaker_turn"


@pytest.mark.unit
class TestChunk:
    def test_construction_with_all_fields(self) -> None:
        chunk = Chunk(
            chunk_id=_uuid(),
            doc_id=_uuid(),
            section_id=_uuid(),
            chunk_index=2,
            char_start=100,
            char_end=350,
            token_count=280,
            text="Financial text here",
            sentence_start_idx=5,
            sentence_end_idx=10,
            heading_path="Item 1A > Risk Factors",
        )
        assert chunk.chunk_index == 2
        assert chunk.heading_path == "Item 1A > Risk Factors"
        assert chunk.token_count == 280

    def test_frozen(self) -> None:
        chunk = Chunk(
            chunk_id=_uuid(),
            doc_id=_uuid(),
            section_id=_uuid(),
            chunk_index=0,
            char_start=0,
            char_end=100,
            token_count=50,
            text="x",
        )
        with pytest.raises(AttributeError):
            chunk.token_count = 99  # type: ignore[misc]


@pytest.mark.unit
class TestEntityMention:
    def test_construction_without_resolution(self) -> None:
        m = EntityMention(
            mention_id=_uuid(),
            doc_id=_uuid(),
            section_id=_uuid(),
            mention_text="Apple Inc.",
            mention_class=MentionClass.ORGANIZATION,
            confidence=0.92,
            char_start=5,
            char_end=15,
        )
        assert m.resolved_entity_id is None
        assert m.resolution_confidence is None
        assert m.resolution_stage is None
        assert m.resolution_outcome is None

    def test_construction_with_resolution(self) -> None:
        entity_id = _uuid()
        m = EntityMention(
            mention_id=_uuid(),
            doc_id=_uuid(),
            section_id=None,
            mention_text="AAPL",
            mention_class=MentionClass.FINANCIAL_INSTRUMENT,
            confidence=0.88,
            char_start=0,
            char_end=4,
            resolved_entity_id=entity_id,
            resolution_confidence=0.95,
            resolution_stage=2,
            resolution_outcome=ResolutionOutcome.AUTO_RESOLVED,
        )
        assert m.resolved_entity_id == entity_id
        assert m.resolution_stage == 2
        assert m.resolution_outcome == ResolutionOutcome.AUTO_RESOLVED

    def test_section_id_can_be_none(self) -> None:
        m = EntityMention(
            mention_id=_uuid(),
            doc_id=_uuid(),
            section_id=None,
            mention_text="CPI",
            mention_class=MentionClass.MACROECONOMIC_INDICATOR,
            confidence=0.80,
            char_start=0,
            char_end=3,
        )
        assert m.section_id is None


@pytest.mark.unit
class TestMentionResolution:
    def test_audit_trail_entry(self) -> None:
        mention_id = _uuid()
        entity_id = _uuid()
        res = MentionResolution(
            mention_id=mention_id,
            stage=1,
            score=1.0,
            is_winner=True,
            candidate_entity_id=entity_id,
            metadata={"alias_text": "apple inc"},
        )
        assert res.stage == 1
        assert res.is_winner is True
        assert res.candidate_entity_id == entity_id

    def test_non_winner_entry(self) -> None:
        res = MentionResolution(mention_id=_uuid(), stage=3, score=0.78, is_winner=False)
        assert res.candidate_entity_id is None
        assert res.metadata is None


@pytest.mark.unit
class TestDocumentEntityStats:
    def test_defaults(self) -> None:
        stats = DocumentEntityStats(doc_id=_uuid())
        assert stats.distinct_mention_count == 0
        assert stats.high_conf_mention_count == 0
        assert stats.type_distribution == {}

    def test_with_counts(self) -> None:
        stats = DocumentEntityStats(
            doc_id=_uuid(),
            distinct_mention_count=12,
            high_conf_mention_count=8,
            type_distribution={"organization": 5, "person": 3},
        )
        assert stats.distinct_mention_count == 12
        assert stats.type_distribution["organization"] == 5


@pytest.mark.unit
class TestRoutingDecision:
    def test_construction(self) -> None:
        decision = RoutingDecision(
            decision_id=_uuid(),
            doc_id=_uuid(),
            routing_tier=RoutingTier.DEEP,
            composite_score=0.82,
            feature_scores={
                "entity_density": 0.90,
                "source_reliability": 0.95,
                "novelty": 0.70,
                "recency": 0.88,
                "watchlist": 1.0,
                "document_type": 0.95,
                "extraction_yield": 0.75,
            },
        )
        assert decision.routing_tier == RoutingTier.DEEP
        assert decision.final_routing_tier is None

    def test_final_tier_can_be_set(self) -> None:
        decision = RoutingDecision(
            decision_id=_uuid(),
            doc_id=_uuid(),
            routing_tier=RoutingTier.DEEP,
            composite_score=0.73,
            feature_scores={},
            final_routing_tier=RoutingTier.LIGHT,  # downgraded by novelty
        )
        assert decision.final_routing_tier == RoutingTier.LIGHT


@pytest.mark.unit
class TestNLPDocument:
    def test_defaults(self) -> None:
        doc = NLPDocument(
            doc_id=_uuid(),
            source_type="eodhd_news",
            published_at=None,
            extracted_at=_now(),
        )
        assert doc.sections == []
        assert doc.chunks == []
        assert doc.mentions == []
        assert doc.routing_decision is None
        assert doc.embedding_failures == []


@pytest.mark.unit
class TestSignalEvent:
    def test_frozen(self) -> None:
        sig = SignalEvent(
            signal_id=_uuid(),
            doc_id=_uuid(),
            entity_id=_uuid(),
            signal_type="earnings_miss",
            confidence=0.90,
            evidence_text="Company missed earnings",
            detected_at=_now(),
        )
        with pytest.raises(AttributeError):
            sig.confidence = 0.5  # type: ignore[misc]


@pytest.mark.unit
class TestEmbeddingPendingEntry:
    def test_construction(self) -> None:
        entry = EmbeddingPendingEntry(
            doc_id=_uuid(),
            chunk_id=_uuid(),
            section_id=None,
            error_detail="OOM during embedding",
            created_at=_now(),
        )
        assert entry.section_id is None
        assert "OOM" in entry.error_detail


@pytest.mark.unit
class TestDocumentSourceMetadata:
    def test_frozen(self) -> None:
        dsm = DocumentSourceMetadata(
            doc_id=_uuid(),
            created_at=_now(),
            title="Q3 Earnings Call",
            url="https://example.com/doc",
            source_name="SEC EDGAR",
            source_type="sec_10q",
            word_count=5000,
        )
        with pytest.raises(AttributeError):
            dsm.title = "other"  # type: ignore[misc]

    def test_none_fields_allowed(self) -> None:
        dsm = DocumentSourceMetadata(
            doc_id=_uuid(),
            created_at=_now(),
        )
        assert dsm.title is None
        assert dsm.url is None
        assert dsm.published_at is None
        assert dsm.source_name is None
        assert dsm.source_type is None
        assert dsm.word_count is None


# ── ArticlePriceImpact tests ──────────────────────────────────────────────────

_PUBLISHED_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_OHLCV_DATE = date(2026, 4, 1)
_ARTICLE_ID = uuid.uuid4()
_ENTITY_ID = uuid.uuid4()
_SYMBOL = "AAPL"
_CAP = Decimal("5.0")


@pytest.mark.unit
class TestArticlePriceImpact:
    def test_impact_score_normalisation_zero(self) -> None:
        """price_open == price_close → price_delta_pct = 0 → impact_score = 0.0."""
        impact = ArticlePriceImpact.compute(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            price_open=Decimal("100"),
            price_close=Decimal("100"),
            normalisation_cap_pct=_CAP,
        )
        assert impact.impact_score == Decimal("0")
        assert impact.price_delta_pct == Decimal("0")

    def test_impact_score_at_cap(self) -> None:
        """abs(price_delta_pct) == 5% == cap → impact_score = 1.0."""
        impact = ArticlePriceImpact.compute(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            price_open=Decimal("100"),
            price_close=Decimal("105"),
            normalisation_cap_pct=_CAP,
        )
        assert impact.impact_score == Decimal("1.0")

    def test_impact_score_exceeds_cap_capped(self) -> None:
        """abs(price_delta_pct) = 10% > 5% cap → impact_score capped at 1.0."""
        impact = ArticlePriceImpact.compute(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            price_open=Decimal("100"),
            price_close=Decimal("110"),
            normalisation_cap_pct=_CAP,
        )
        assert impact.impact_score == Decimal("1.0")

    def test_impact_score_partial(self) -> None:
        """abs(price_delta_pct) = 2.5% → impact_score = 0.5."""
        impact = ArticlePriceImpact.compute(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            price_open=Decimal("100"),
            price_close=Decimal("102.5"),
            normalisation_cap_pct=_CAP,
        )
        assert impact.impact_score == Decimal("0.5")

    def test_negative_delta_uses_abs(self) -> None:
        """price_close < price_open → abs applied → impact_score positive."""
        impact = ArticlePriceImpact.compute(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            price_open=Decimal("100"),
            price_close=Decimal("97"),  # -3%
            normalisation_cap_pct=_CAP,
        )
        assert impact.price_delta_pct < Decimal("0")
        assert impact.impact_score == Decimal("0.6")

    def test_naive_datetime_raises(self) -> None:
        """published_at without tzinfo → PriceImpactError."""
        naive = datetime(2026, 4, 1, 12, 0, 0)  # noqa: DTZ001
        with pytest.raises(PriceImpactError, match="UTC-aware"):
            ArticlePriceImpact.compute(
                article_id=_ARTICLE_ID,
                entity_id=_ENTITY_ID,
                symbol=_SYMBOL,
                published_at=naive,  # type: ignore[arg-type]
                price_open=Decimal("100"),
                price_close=Decimal("105"),
            )

    def test_impact_score_out_of_range_raises(self) -> None:
        """Direct construction with impact_score < 0 → PriceImpactError via __post_init__."""
        with pytest.raises(PriceImpactError, match="impact_score"):
            ArticlePriceImpact(
                article_id=_ARTICLE_ID,
                entity_id=_ENTITY_ID,
                symbol=_SYMBOL,
                published_at=_PUBLISHED_AT,
                ohlcv_date=_OHLCV_DATE,
                price_open=Decimal("100"),
                price_close=Decimal("105"),
                price_delta_pct=Decimal("5"),
                impact_score=Decimal("-0.1"),
            )

    def test_symbol_too_long_raises(self) -> None:
        """symbol > 20 chars → PriceImpactError."""
        with pytest.raises(PriceImpactError, match="symbol"):
            ArticlePriceImpact.compute(
                article_id=_ARTICLE_ID,
                entity_id=_ENTITY_ID,
                symbol="X" * 21,
                published_at=_PUBLISHED_AT,
                price_open=Decimal("100"),
                price_close=Decimal("105"),
            )

    def test_zero_factory(self) -> None:
        """zero() creates entity with impact_score=0.0 and zero prices."""
        impact = ArticlePriceImpact.zero(
            article_id=_ARTICLE_ID,
            entity_id=_ENTITY_ID,
            symbol=_SYMBOL,
            published_at=_PUBLISHED_AT,
            ohlcv_date=_OHLCV_DATE,
        )
        assert impact.impact_score == Decimal("0.0")
        assert impact.price_open == Decimal("0")
        assert impact.price_close == Decimal("0")
        assert impact.ohlcv_date == _OHLCV_DATE
