"""Unit tests for GetEntityIntelligenceUseCase (PRD-0074 Wave D, T-D-01).

Tests:
  - 404 when entity not found (returns None)
  - Full happy path with all data
  - Source distribution pct sums to ~1.0
  - Confidence trend has ≤90 data points
  - key_metrics extracted by entity type
  - data_completeness within [0,1]
  - health_score from canonical entity
  - No narrative → current_narrative is None
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
_ENTITY_ID = uuid4()
_VERSION_ID = uuid4()


def _make_canonical_entity(entity_type: str = "company", metadata: dict | None = None):
    """Build a mock CanonicalEntity."""
    from knowledge_graph.domain.models import CanonicalEntity

    return CanonicalEntity(
        entity_id=_ENTITY_ID,
        canonical_name="Apple Inc.",
        entity_type=entity_type,
        ticker="AAPL",
        isin="US0378331005",
        exchange="NASDAQ",
        description="Apple Inc. is a technology company.",
        data_completeness=0.7,
        enriched_at=_NOW,
        metadata=metadata or {"sector": "Technology", "ticker": "AAPL", "market_cap": 3_000_000_000},
        enrichment_attempts=0,
        health_score=0.82,
    )


def _make_narrative_version():
    from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

    return EntityNarrativeVersion(
        version_id=_VERSION_ID,
        entity_id=_ENTITY_ID,
        narrative_text="Apple Inc. is a major technology company known for iPhone and Mac.",
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        generation_reason=NarrativeGenerationReason.INITIAL,
        generated_at=_NOW,
        is_current=True,
        word_count=12,  # "Apple Inc. is a major technology company known for iPhone and Mac." = 12 words
        quality_score=0.8,
    )


def _make_breakdown_data():
    return {
        "mean_support": 0.75,
        "mean_corroboration": 0.12,
        "mean_contradiction": 0.08,
        "latest_evidence_at": _NOW,
        "relation_count": 15,
    }


def _make_source_rows():
    return [
        {"source_type": "news", "source_name": "Reuters", "count": 6, "pct": 0.6},
        {"source_type": "news", "source_name": "Bloomberg", "count": 4, "pct": 0.4},
    ]


def _make_trend_rows(n: int = 30):
    """Generate n daily trend rows (uses timedelta to span month boundaries)."""
    start = date(2026, 1, 1)
    return [{"date": start + timedelta(days=d), "avg_confidence": 0.7} for d in range(n)]


async def _make_uc():
    """Build a use case with mocked repositories."""
    from knowledge_graph.application.use_cases.get_entity_intelligence import (
        GetEntityIntelligenceUseCase,
    )

    entity_repo = AsyncMock()
    narrative_repo = AsyncMock()
    aggregates_repo = AsyncMock()

    return (
        GetEntityIntelligenceUseCase(
            entity_repo=entity_repo,
            narrative_repo=narrative_repo,
            aggregates_repo=aggregates_repo,
        ),
        entity_repo,
        narrative_repo,
        aggregates_repo,
    )


class TestGetEntityIntelligenceUseCase:
    async def test_returns_none_when_entity_not_found(self) -> None:
        """Use case returns None when entity_repo returns None (404 case)."""
        uc, entity_repo, _narrative_repo, _aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=None)

        result = await uc.execute(entity_id=_ENTITY_ID)
        assert result is None

    async def test_happy_path_full_response(self) -> None:
        """Happy path: entity + narrative + breakdown all populated."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=_make_canonical_entity())
        narrative_repo.find_current = AsyncMock(return_value=_make_narrative_version())
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=_make_source_rows())
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=_make_trend_rows(30))

        result = await uc.execute(entity_id=_ENTITY_ID)

        assert result is not None
        assert result.entity_id == _ENTITY_ID
        assert result.canonical_name == "Apple Inc."
        assert result.entity_type == "company"
        assert result.health_score == 0.82
        assert result.current_narrative is not None
        assert result.current_narrative.version_id == _VERSION_ID
        assert result.confidence_breakdown.relation_count == 15
        assert result.data_completeness == 0.7  # from entity.data_completeness

    async def test_no_narrative_returns_none_current_narrative(self) -> None:
        """When no current narrative exists, current_narrative is None."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=_make_canonical_entity())
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)
        assert result is not None
        assert result.current_narrative is None

    async def test_source_distribution_pcts_sum_to_one(self) -> None:
        """Source distribution percentages should sum to ~1.0."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=_make_canonical_entity())
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=_make_source_rows())
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)

        assert result is not None
        total_pct = sum(s.pct for s in result.confidence_breakdown.source_distribution)
        assert abs(total_pct - 1.0) < 1e-4

    async def test_confidence_trend_within_90_points(self) -> None:
        """Confidence trend should have ≤90 data points."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=_make_canonical_entity())
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=_make_trend_rows(90))

        result = await uc.execute(entity_id=_ENTITY_ID)

        assert result is not None
        assert len(result.confidence_breakdown.confidence_trend) <= 90

    async def test_key_metrics_extracted_for_company(self) -> None:
        """For company entities, key_metrics includes market_cap, sector, ticker."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(
            return_value=_make_canonical_entity(
                entity_type="company",
                metadata={"sector": "Technology", "ticker": "AAPL", "market_cap": 3_000_000},
            )
        )
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)

        assert result is not None
        assert "sector" in result.key_metrics
        assert result.key_metrics["sector"] == "Technology"
        assert "ticker" in result.key_metrics

    async def test_key_metrics_extracted_for_person(self) -> None:
        """For person entities, key_metrics includes role and organization."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(
            return_value=_make_canonical_entity(
                entity_type="person",
                metadata={"role": "CEO", "organization": "Apple Inc."},
            )
        )
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)

        assert result is not None
        assert result.key_metrics.get("role") == "CEO"
        assert result.key_metrics.get("organization") == "Apple Inc."

    async def test_key_metrics_empty_for_unknown_type(self) -> None:
        """For unknown entity types, key_metrics is empty dict."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(
            return_value=_make_canonical_entity(entity_type="location", metadata={"country": "US"})
        )
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)
        assert result is not None
        assert result.key_metrics == {}

    async def test_data_completeness_from_entity(self) -> None:
        """data_completeness comes from entity.data_completeness when set."""
        uc, entity_repo, narrative_repo, aggregates_repo = await _make_uc()
        entity_repo.get_by_id = AsyncMock(return_value=_make_canonical_entity())
        narrative_repo.find_current = AsyncMock(return_value=None)
        aggregates_repo.get_confidence_breakdown = AsyncMock(return_value=_make_breakdown_data())
        aggregates_repo.get_source_distribution = AsyncMock(return_value=[])
        aggregates_repo.get_confidence_trend = AsyncMock(return_value=[])

        result = await uc.execute(entity_id=_ENTITY_ID)
        assert result is not None
        # Entity has data_completeness=0.7
        assert 0.0 <= result.data_completeness <= 1.0
        assert result.data_completeness == pytest.approx(0.7, abs=1e-6)
