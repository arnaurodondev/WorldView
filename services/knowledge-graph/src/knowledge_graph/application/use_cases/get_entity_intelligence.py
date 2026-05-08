"""GetEntityIntelligenceUseCase — aggregate entity intelligence for the Intelligence API.

R25 compliance: this use case wraps all repository access so API route files never
import from the infrastructure layer directly.
R27 compliance: read-only — uses the read-replica session throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.api.schemas_intelligence import EntityIntelligencePublic
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
        IntelligenceAggregatesRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Number of expected metadata fields used to compute data_completeness heuristic.
_EXPECTED_FIELDS = 10


def _extract_key_metrics(entity_type: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract entity-type-specific key metrics from the canonical_entities.metadata JSONB.

    For company / financial_instrument: return market_cap, sector, ticker.
    For person: return role, organization.
    For anything else: return empty dict.
    """
    if entity_type in {"company", "financial_instrument"}:
        return {k: metadata.get(k) for k in ("market_cap", "sector", "ticker") if metadata.get(k) is not None}
    if entity_type == "person":
        return {k: metadata.get(k) for k in ("role", "organization") if metadata.get(k) is not None}
    return {}


def _compute_data_completeness(metadata: dict[str, Any]) -> float:
    """Compute data_completeness as populated_field_count / _EXPECTED_FIELDS.

    Counts the number of non-None/non-empty values across a fixed set of 10
    expected metadata fields.  Returns a float in [0.0, 1.0].
    """
    _watched_fields = (
        "sector",
        "industry",
        "country",
        "exchange",
        "ticker",
        "currency_code",
        "employee_count",
        "founded_year",
        "headquarters_city",
        "role",
    )
    populated = sum(1 for f in _watched_fields if metadata.get(f) not in (None, ""))
    return min(populated / _EXPECTED_FIELDS, 1.0)


class GetEntityIntelligenceUseCase:
    """Aggregate entity intelligence for GET /entities/{entity_id}/intelligence.

    Args:
        entity_repo:   CanonicalEntityRepository bound to the read-only session.
        narrative_repo: NarrativeRepository bound to the read-only session.
        aggregates_repo: IntelligenceAggregatesRepository for evidence aggregates.
    """

    def __init__(
        self,
        entity_repo: CanonicalEntityRepository,
        narrative_repo: NarrativeRepository,
        aggregates_repo: IntelligenceAggregatesRepository,
    ) -> None:
        self._entity_repo = entity_repo
        self._narrative_repo = narrative_repo
        self._aggregates_repo = aggregates_repo

    async def execute(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
    ) -> EntityIntelligencePublic | None:
        """Build and return EntityIntelligencePublic, or None if entity not found.

        Steps:
          1. Load canonical entity (404 → None).
          2. Load current narrative via NarrativeRepository.find_current.
          3. Load confidence breakdown (AVG components + latest_evidence_at + count).
          4. Load source distribution (top-10 shares).
          5. Load 90-day confidence trend.
          6. Compute data_completeness and key_metrics from entity metadata.
          7. Assemble and return EntityIntelligencePublic.
        """
        # Deferred import to satisfy R12 (no infra imports at module level in use cases)
        from knowledge_graph.api.schemas_intelligence import (
            ConfidenceBreakdownPublic,
            ConfidenceTrendPoint,
            EntityIntelligencePublic,
            NarrativeVersionPublic,
            SourceSharePublic,
        )

        # Step 1: Load canonical entity
        entity = await self._entity_repo.get_by_id(entity_id)
        if entity is None:
            return None

        # Step 2: Load current narrative
        current_narrative: NarrativeVersionPublic | None = None
        narrative_version = await self._narrative_repo.find_current(entity_id, tenant_id)
        if narrative_version is not None:
            current_narrative = NarrativeVersionPublic(
                version_id=narrative_version.version_id,
                narrative_text=narrative_version.narrative_text,
                model_id=narrative_version.model_id,
                generation_reason=narrative_version.generation_reason.value,
                generated_at=narrative_version.generated_at,
                word_count=narrative_version.word_count,
                quality_score=narrative_version.quality_score,
            )

        # Step 3: Load confidence breakdown
        breakdown_data = await self._aggregates_repo.get_confidence_breakdown(entity_id)

        # Step 4: Load source distribution
        source_rows = await self._aggregates_repo.get_source_distribution(entity_id)
        source_distribution = [
            SourceSharePublic(
                source_type=row["source_type"],
                source_name=row["source_name"],
                count=row["count"],
                pct=row["pct"],
            )
            for row in source_rows
        ]

        # Step 5: Load 90-day confidence trend
        trend_rows = await self._aggregates_repo.get_confidence_trend(entity_id, days=90)
        confidence_trend = [
            ConfidenceTrendPoint(date=row["date"], avg_confidence=row["avg_confidence"]) for row in trend_rows
        ]

        confidence_breakdown = ConfidenceBreakdownPublic(
            mean_support=breakdown_data["mean_support"],
            mean_corroboration=breakdown_data["mean_corroboration"],
            mean_contradiction=breakdown_data["mean_contradiction"],
            latest_evidence_at=breakdown_data["latest_evidence_at"],
            relation_count=breakdown_data["relation_count"],
            source_distribution=source_distribution,
            confidence_trend=confidence_trend,
        )

        # Step 6: Derive metadata-based fields
        metadata: dict[str, Any] = entity.metadata if isinstance(entity.metadata, dict) else {}
        data_completeness = entity.data_completeness
        if data_completeness is None:
            data_completeness = _compute_data_completeness(metadata)

        key_metrics = _extract_key_metrics(entity.entity_type, metadata)

        logger.info(  # type: ignore[no-any-return]
            "entity_intelligence_assembled",
            entity_id=str(entity_id),
            relation_count=breakdown_data["relation_count"],
            has_narrative=current_narrative is not None,
        )

        return EntityIntelligencePublic(
            entity_id=entity.entity_id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            health_score=getattr(entity, "health_score", None),
            current_narrative=current_narrative,
            confidence_breakdown=confidence_breakdown,
            key_metrics=key_metrics,
            data_completeness=float(data_completeness),
        )
