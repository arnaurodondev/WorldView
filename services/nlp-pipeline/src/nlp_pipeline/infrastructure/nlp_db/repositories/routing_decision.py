"""Routing decision repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.infrastructure.nlp_db.models import RoutingDecisionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import RoutingDecision


class RoutingDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, decision: RoutingDecision) -> None:
        """Insert a routing decision row.

        PLAN-0084 B-3 (T-B-3-02): uses ``ON CONFLICT (decision_id) DO NOTHING``
        so that Kafka replays that produce the same deterministic ``decision_id``
        (via ``uuid5_from_parts``) are silently idempotent at the DB level.
        """
        stmt = (
            pg_insert(RoutingDecisionModel)
            .values(
                decision_id=decision.decision_id,
                doc_id=decision.doc_id,
                routing_tier=str(decision.routing_tier),
                final_routing_tier=(str(decision.final_routing_tier) if decision.final_routing_tier else None),
                # PLAN-0057 A-1 (F-CRIT-06): persist Block 6 suppression-gate output.
                processing_path=(str(decision.processing_path) if decision.processing_path else None),
                composite_score=decision.composite_score,
                feature_scores_json=decision.feature_scores,
            )
            .on_conflict_do_nothing(index_elements=["decision_id"])
        )
        await self._session.execute(stmt)

    async def get_by_doc(self, doc_id: UUID) -> RoutingDecisionModel | None:
        result = await self._session.execute(select(RoutingDecisionModel).where(RoutingDecisionModel.doc_id == doc_id))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def set_final_tier(self, doc_id: UUID, final_tier: str) -> None:
        """Update routing_decisions.final_routing_tier after Stage 2 novelty correction."""
        await self._session.execute(
            update(RoutingDecisionModel)
            .where(RoutingDecisionModel.doc_id == doc_id)
            .values(final_routing_tier=final_tier),
        )
