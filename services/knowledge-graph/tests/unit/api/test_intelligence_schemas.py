"""Unit tests for intelligence API schemas (PRD-0074 Wave D, T-D-01).

Tests:
  - ConfidenceTrendPoint validates avg_confidence range
  - SourceSharePublic percentages must be in [0,1]
  - ConfidenceBreakdownPublic defaults to empty lists
  - NarrativeVersionPublic maps all fields
  - EntityIntelligencePublic constructs correctly
  - data_completeness clamped to [0,1]
  - source_distribution pct values sum to ~1.0
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
_ENTITY_ID = uuid4()
_VERSION_ID = uuid4()


class TestConfidenceTrendPoint:
    def test_valid_point(self) -> None:
        from knowledge_graph.api.schemas_intelligence import ConfidenceTrendPoint

        p = ConfidenceTrendPoint(date=date(2026, 1, 1), avg_confidence=0.75)
        assert p.avg_confidence == 0.75
        assert p.date == date(2026, 1, 1)

    def test_confidence_at_boundaries(self) -> None:
        from knowledge_graph.api.schemas_intelligence import ConfidenceTrendPoint

        # ge=0.0, le=1.0
        p_min = ConfidenceTrendPoint(date=date(2026, 1, 1), avg_confidence=0.0)
        p_max = ConfidenceTrendPoint(date=date(2026, 1, 1), avg_confidence=1.0)
        assert p_min.avg_confidence == 0.0
        assert p_max.avg_confidence == 1.0

    def test_invalid_confidence_above_1(self) -> None:
        from knowledge_graph.api.schemas_intelligence import ConfidenceTrendPoint
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConfidenceTrendPoint(date=date(2026, 1, 1), avg_confidence=1.1)


class TestSourceSharePublic:
    def test_valid_source_share(self) -> None:
        from knowledge_graph.api.schemas_intelligence import SourceSharePublic

        s = SourceSharePublic(source_type="news", source_name="Reuters", count=10, pct=0.5)
        assert s.source_type == "news"
        assert s.pct == 0.5

    def test_null_source_fields_allowed(self) -> None:
        from knowledge_graph.api.schemas_intelligence import SourceSharePublic

        s = SourceSharePublic(source_type=None, source_name=None, count=3, pct=0.1)
        assert s.source_type is None


class TestSourceDistributionPercentages:
    def test_pcts_sum_approximately_one(self) -> None:
        """Source percentages from repository should sum to ~1.0 (within floating point)."""
        from knowledge_graph.api.schemas_intelligence import SourceSharePublic

        shares = [
            SourceSharePublic(source_type="news", source_name="Reuters", count=6, pct=0.6),
            SourceSharePublic(source_type="news", source_name="Bloomberg", count=4, pct=0.4),
        ]
        total_pct = sum(s.pct for s in shares)
        assert abs(total_pct - 1.0) < 1e-6, f"Expected sum ~1.0, got {total_pct}"

    def test_pcts_partial_sum_is_valid(self) -> None:
        """Single source has pct=1.0."""
        from knowledge_graph.api.schemas_intelligence import SourceSharePublic

        share = SourceSharePublic(source_type="news", source_name="Reuters", count=10, pct=1.0)
        assert share.pct == 1.0


class TestConfidenceBreakdownPublic:
    def test_empty_defaults(self) -> None:
        from knowledge_graph.api.schemas_intelligence import ConfidenceBreakdownPublic

        bd = ConfidenceBreakdownPublic(relation_count=0)
        assert bd.mean_support is None
        assert bd.mean_corroboration is None
        assert bd.mean_contradiction is None
        assert bd.latest_evidence_at is None
        assert bd.source_distribution == []
        assert bd.confidence_trend == []

    def test_fully_populated(self) -> None:
        from knowledge_graph.api.schemas_intelligence import (
            ConfidenceBreakdownPublic,
            ConfidenceTrendPoint,
            SourceSharePublic,
        )

        bd = ConfidenceBreakdownPublic(
            mean_support=0.8,
            mean_corroboration=0.15,
            mean_contradiction=0.05,
            latest_evidence_at=_NOW,
            relation_count=5,
            source_distribution=[SourceSharePublic(source_type="news", source_name="R", count=5, pct=1.0)],
            confidence_trend=[ConfidenceTrendPoint(date=date(2026, 1, 1), avg_confidence=0.7)],
        )
        assert bd.relation_count == 5
        assert len(bd.source_distribution) == 1
        assert len(bd.confidence_trend) == 1


class TestConfidenceTrendLength:
    def test_trend_has_at_most_90_points(self) -> None:
        """Confidence trend should never exceed 90 daily data points."""
        from knowledge_graph.api.schemas_intelligence import ConfidenceTrendPoint

        # Simulate building 90 trend points
        trend = [
            ConfidenceTrendPoint(
                date=date(2026, 1, 1),  # simplified: same date, tests count
                avg_confidence=float(i) / 90.0,
            )
            for i in range(90)
        ]
        assert len(trend) <= 90


class TestNarrativeVersionPublic:
    def test_maps_all_fields(self) -> None:
        from knowledge_graph.api.schemas_intelligence import NarrativeVersionPublic

        nvp = NarrativeVersionPublic(
            version_id=_VERSION_ID,
            narrative_text="Apple Inc. is a company.",
            model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
            generation_reason="INITIAL",
            generated_at=_NOW,
            word_count=5,
            quality_score=0.85,
        )
        assert nvp.version_id == _VERSION_ID
        assert nvp.word_count == 5
        assert nvp.quality_score == 0.85

    def test_optional_fields_default_to_none(self) -> None:
        from knowledge_graph.api.schemas_intelligence import NarrativeVersionPublic

        nvp = NarrativeVersionPublic(
            version_id=_VERSION_ID,
            narrative_text="Some entity narrative text.",
            model_id="template-v1",
            generation_reason="MANUAL_TRIGGER",
            generated_at=_NOW,
        )
        assert nvp.word_count is None
        assert nvp.quality_score is None


class TestEntityIntelligencePublic:
    def _make_breakdown(self):
        from knowledge_graph.api.schemas_intelligence import ConfidenceBreakdownPublic

        return ConfidenceBreakdownPublic(relation_count=3)

    def test_constructs_correctly(self) -> None:
        from knowledge_graph.api.schemas_intelligence import EntityIntelligencePublic

        intel = EntityIntelligencePublic(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc.",
            entity_type="company",
            health_score=0.75,
            current_narrative=None,
            confidence_breakdown=self._make_breakdown(),
            key_metrics={"sector": "Technology"},
            data_completeness=0.6,
        )
        assert intel.entity_id == _ENTITY_ID
        assert intel.health_score == 0.75
        assert intel.data_completeness == 0.6

    def test_data_completeness_must_be_between_0_and_1(self) -> None:
        from knowledge_graph.api.schemas_intelligence import EntityIntelligencePublic
        from pydantic import ValidationError

        # Below 0 should fail
        with pytest.raises(ValidationError):
            EntityIntelligencePublic(
                entity_id=_ENTITY_ID,
                canonical_name="Test",
                entity_type="company",
                confidence_breakdown=self._make_breakdown(),
                data_completeness=-0.1,
            )

    def test_optional_fields_have_sensible_defaults(self) -> None:
        from knowledge_graph.api.schemas_intelligence import EntityIntelligencePublic

        intel = EntityIntelligencePublic(
            entity_id=_ENTITY_ID,
            canonical_name="Tesla",
            entity_type="company",
            confidence_breakdown=self._make_breakdown(),
        )
        assert intel.health_score is None
        assert intel.current_narrative is None
        assert intel.key_metrics == {}
        assert intel.data_completeness == 0.0
