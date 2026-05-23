"""GetEntitySentimentTimeseriesUseCase — PLAN-0091 Wave E-1, T-E-1-02."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from nlp_pipeline.application.ports.repositories import DocumentSourceMetadataRepository

log = structlog.get_logger(__name__)


class GetEntitySentimentTimeseriesUseCase:
    """Return daily sentiment aggregates for an entity over the last N days.

    Queries document_source_metadata JOIN entity_mentions grouped by calendar
    day (UTC).  Each row contains article_count, avg_relevance, positive_ratio,
    negative_ratio, and avg_impact_score.

    This is a read-only use case — no writes, no UoW needed.
    """

    async def execute(
        self,
        repo: DocumentSourceMetadataRepository,
        entity_id: UUID,
        days: int,
    ) -> list[dict[str, object]]:
        log.debug("get_entity_sentiment_timeseries", entity_id=str(entity_id), days=days)
        return await repo.get_entity_sentiment_timeseries(entity_id=entity_id, days=days)
