"""RetrievalPlanBuilder — maps QueryIntent to a RetrievalPlan (T-E-2-02).

The builder encodes the intent→source mapping from PRD §6.7 Step 3. The
``use_cypher`` flag is ANDed with ``cypher_enabled`` at build time so Cypher
queries remain gated even if the base plan includes them (feature flag AD-06).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from rag_chat.domain.entities.chat import RetrievalPlan
from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from rag_chat.domain.value_objects import DateRange


@dataclass(frozen=True)
class _PlanFlags:
    """Boolean source flags for a single intent (no entity/date context yet)."""

    use_chunks: bool
    use_relations: bool
    use_graph: bool
    use_claims: bool
    use_events: bool
    use_contradictions: bool
    use_financial: bool
    use_portfolio: bool
    use_cypher: bool  # base — ANDed with cypher_enabled at build time


# Intent → retrieval source matrix (PRD §6.7 / plan T-E-2-02 spec)
_INTENT_TO_FLAGS: dict[QueryIntent, _PlanFlags] = {
    QueryIntent.FACTUAL_LOOKUP: _PlanFlags(
        use_chunks=True,
        use_relations=True,
        use_graph=True,
        use_claims=True,
        use_events=False,
        use_contradictions=True,
        use_financial=False,
        use_portfolio=False,
        use_cypher=False,
    ),
    QueryIntent.RELATIONSHIP: _PlanFlags(
        use_chunks=False,
        use_relations=True,
        use_graph=True,
        use_claims=False,
        use_events=False,
        use_contradictions=False,
        use_financial=False,
        use_portfolio=False,
        use_cypher=True,
    ),
    QueryIntent.SIGNAL_INTEL: _PlanFlags(
        use_chunks=True,
        use_relations=False,
        use_graph=False,
        use_claims=True,
        use_events=True,
        use_contradictions=True,
        use_financial=False,
        use_portfolio=False,
        use_cypher=False,
    ),
    QueryIntent.FINANCIAL_DATA: _PlanFlags(
        use_chunks=False,
        use_relations=False,
        use_graph=False,
        use_claims=True,
        use_events=True,
        use_contradictions=False,
        use_financial=True,
        use_portfolio=False,
        use_cypher=False,
    ),
    QueryIntent.COMPARISON: _PlanFlags(
        use_chunks=True,
        use_relations=True,
        use_graph=False,
        use_claims=True,
        use_events=True,
        use_contradictions=True,
        use_financial=True,
        use_portfolio=False,
        use_cypher=False,
    ),
    QueryIntent.REASONING: _PlanFlags(
        use_chunks=True,
        use_relations=True,
        use_graph=True,
        use_claims=True,
        use_events=True,
        use_contradictions=True,
        use_financial=True,
        use_portfolio=False,
        use_cypher=True,
    ),
    QueryIntent.PORTFOLIO: _PlanFlags(
        use_chunks=True,
        use_relations=True,
        use_graph=True,
        use_claims=True,
        use_events=True,
        use_contradictions=True,
        use_financial=True,
        use_portfolio=True,
        use_cypher=False,
    ),
    QueryIntent.GENERAL: _PlanFlags(
        use_chunks=True,
        use_relations=False,
        use_graph=False,
        use_claims=False,
        use_events=False,
        use_contradictions=False,
        use_financial=False,
        use_portfolio=False,
        use_cypher=False,
    ),
}


class RetrievalPlanBuilder:
    """Build a ``RetrievalPlan`` from a classified intent and request context.

    Args:
        cypher_enabled: Feature flag — when ``False``, ``use_cypher`` is always
                        ``False`` regardless of the intent's base plan.
    """

    def __init__(self, cypher_enabled: bool = False) -> None:
        self._cypher_enabled = cypher_enabled

    def build(
        self,
        intent: QueryIntent,
        entity_ids: tuple[UUID, ...] = (),
        date_filter: DateRange | None = None,
    ) -> RetrievalPlan:
        """Return a ``RetrievalPlan`` for *intent* with entity and date context applied."""
        flags = _INTENT_TO_FLAGS[intent]
        return RetrievalPlan(
            use_chunks=flags.use_chunks,
            use_relations=flags.use_relations,
            use_graph=flags.use_graph,
            use_claims=flags.use_claims,
            use_events=flags.use_events,
            use_contradictions=flags.use_contradictions,
            use_financial=flags.use_financial,
            use_portfolio=flags.use_portfolio,
            use_cypher=flags.use_cypher and self._cypher_enabled,
            entity_ids=entity_ids,
            date_filter=date_filter,
        )
