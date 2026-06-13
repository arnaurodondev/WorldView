"""PathInsight repository — bulk replace and query operations (T-E1-02).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

``replace_for_anchor`` deletes existing insights and bulk-inserts the new
list in a single transaction — no N+1 queries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.path_insight_repository import (
    PathInsightRepositoryPort,
)
from knowledge_graph.domain.entities.path_insight import (
    PathEdge,
    PathInsight,
    PathNode,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _nodes_to_json(nodes: tuple[PathNode, ...]) -> str:
    return json.dumps(
        [
            {
                "entity_id": str(n.entity_id),
                "name": n.name,
                "entity_type": n.entity_type,
            }
            for n in nodes
        ]
    )


def _edges_to_json(edges: tuple[PathEdge, ...]) -> str:
    return json.dumps([{"relation_type": e.relation_type, "confidence": e.confidence} for e in edges])


def _parse_nodes(raw: object) -> tuple[PathNode, ...]:
    data = raw if isinstance(raw, list) else json.loads(str(raw))
    return tuple(
        PathNode(
            entity_id=UUID(str(item["entity_id"])),
            name=str(item["name"]),
            entity_type=str(item["entity_type"]),
        )
        for item in data
    )


def _parse_edges(raw: object) -> tuple[PathEdge, ...]:
    data = raw if isinstance(raw, list) else json.loads(str(raw))
    return tuple(
        PathEdge(
            relation_type=str(item["relation_type"]),
            confidence=float(item["confidence"]),
        )
        for item in data
    )


class PathInsightRepository(PathInsightRepositoryPort):
    """Concrete implementation of PathInsightRepositoryPort using asyncpg."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_anchor(
        self,
        anchor_entity_id: UUID,
        insights: list[PathInsight],
    ) -> None:
        """Delete all existing insights for the anchor, then bulk-insert the new list.

        Executes as a single transaction (no N+1).  The delete + insert pair is
        atomic because both run in the same session transaction.
        """
        await self._session.execute(
            text("DELETE FROM path_insights WHERE anchor_entity_id = CAST(:anchor AS UUID)"),
            {"anchor": str(anchor_entity_id)},
        )
        if not insights:
            return

        # Bulk INSERT using VALUES parameters.
        # Build a single multi-row INSERT statement.
        rows_sql_parts: list[str] = []
        params: dict[str, object] = {}
        for i, insight in enumerate(insights):
            suffix = f"_{i}"
            # asyncpg / SQLAlchemy text() treats ``:name::type`` as a conflict
            # between the named-param ``:name`` and the Postgres cast ``::type``.
            # Use explicit CAST(:name AS type) for all typed columns to avoid
            # the parse ambiguity (BP-180 pattern).
            # PLAN-0112 W3 (T-3-04): persist the new weirdness columns alongside
            # the legacy ones.  dst_entity_id is nullable (CAST handles None).
            rows_sql_parts.append(
                f"(CAST(:insight_id{suffix} AS UUID), "
                f"CAST(:anchor{suffix} AS UUID), "
                f"CAST(:path_nodes{suffix} AS jsonb), "
                f"CAST(:path_edges{suffix} AS jsonb), "
                f":hop_count{suffix}, "
                f":harmonic{suffix}, "
                f":diversity{suffix}, "
                f":surprise{suffix}, "
                f":template{suffix}, "
                f":composite{suffix}, "
                f":llm_exp{suffix}, "
                f":exp_model{suffix}, "
                f"CAST(:computed_at{suffix} AS TIMESTAMPTZ), "
                f"CAST(:dst{suffix} AS UUID), "
                f":reliability{suffix}, "
                f":unexpectedness{suffix}, "
                f":semantic{suffix}, "
                f":novelty{suffix}, "
                f":weirdness{suffix}, "
                f":scorer_version{suffix})"
            )
            params[f"insight_id{suffix}"] = str(insight.insight_id)
            params[f"anchor{suffix}"] = str(insight.anchor_entity_id)
            params[f"path_nodes{suffix}"] = _nodes_to_json(insight.path_nodes)
            params[f"path_edges{suffix}"] = _edges_to_json(insight.path_edges)
            params[f"hop_count{suffix}"] = insight.hop_count
            params[f"harmonic{suffix}"] = insight.harmonic_score
            params[f"diversity{suffix}"] = insight.diversity_score
            params[f"surprise{suffix}"] = insight.surprise_score
            params[f"template{suffix}"] = insight.template_match
            params[f"composite{suffix}"] = insight.composite_score
            params[f"llm_exp{suffix}"] = insight.llm_explanation
            params[f"exp_model{suffix}"] = insight.explanation_model
            params[f"computed_at{suffix}"] = insight.computed_at
            params[f"dst{suffix}"] = str(insight.dst_entity_id) if insight.dst_entity_id else None
            params[f"reliability{suffix}"] = insight.reliability
            params[f"unexpectedness{suffix}"] = insight.unexpectedness
            params[f"semantic{suffix}"] = insight.semantic_distance
            params[f"novelty{suffix}"] = insight.novelty
            params[f"weirdness{suffix}"] = insight.weirdness
            params[f"scorer_version{suffix}"] = insight.scorer_version

        sql = (
            "INSERT INTO path_insights "
            "(insight_id, anchor_entity_id, path_nodes, path_edges, hop_count, "
            "harmonic_score, diversity_score, surprise_score, template_match, "
            "composite_score, llm_explanation, explanation_model, computed_at, "
            "dst_entity_id, reliability, unexpectedness, semantic_distance, "
            "novelty, weirdness, scorer_version) "
            f"VALUES {', '.join(rows_sql_parts)}"
        )
        await self._session.execute(text(sql), params)

    async def list_by_anchor(
        self,
        anchor_entity_id: UUID,
        *,
        limit: int = 50,
        min_score: float = 0.0,
        min_hops: int = 2,
        max_hops: int = 5,
    ) -> list[PathInsight]:
        """Return insights ordered by weirdness DESC with optional filters.

        PLAN-0112 W3: ranking switches to ``weirdness`` (mirrored into
        ``composite_score``).  ``COALESCE(weirdness, composite_score)`` keeps
        pre-W3 rows (weirdness IS NULL) ordered by their legacy composite_score
        so an un-backfilled deployment still returns sensibly-ranked paths.
        """
        result = await self._session.execute(
            text("""
SELECT insight_id, anchor_entity_id, hop_count, path_nodes, path_edges,
       harmonic_score, diversity_score, surprise_score, template_match,
       composite_score, llm_explanation, explanation_model, computed_at,
       dst_entity_id, reliability, unexpectedness, semantic_distance,
       novelty, weirdness, scorer_version
FROM path_insights
WHERE anchor_entity_id = CAST(:anchor AS UUID)
  AND composite_score >= :min_score
  AND hop_count >= :min_hops
  AND hop_count <= :max_hops
ORDER BY COALESCE(weirdness, composite_score) DESC
LIMIT :lim
"""),
            {
                "anchor": str(anchor_entity_id),
                "min_score": min_score,
                "min_hops": min_hops,
                "max_hops": max_hops,
                "lim": limit,
            },
        )
        rows = result.fetchall()
        insights: list[PathInsight] = []
        for row in rows:
            nodes = _parse_nodes(row[3])
            edges = _parse_edges(row[4])
            insights.append(
                PathInsight(
                    insight_id=UUID(str(row[0])),
                    anchor_entity_id=UUID(str(row[1])),
                    hop_count=int(row[2]),
                    path_nodes=nodes,
                    path_edges=edges,
                    harmonic_score=float(row[5]),
                    diversity_score=float(row[6]),
                    surprise_score=float(row[7]),
                    template_match=str(row[8]) if row[8] else None,
                    composite_score=float(row[9]),
                    llm_explanation=str(row[10]) if row[10] else None,
                    explanation_model=str(row[11]) if row[11] else None,
                    computed_at=row[12],
                    # PLAN-0112 W3 weirdness columns.  All NULLable: old rows
                    # written before the migration deserialize to the entity
                    # defaults (None / 0.0), keeping the in-range invariant.
                    dst_entity_id=UUID(str(row[13])) if row[13] else None,
                    reliability=float(row[14]) if row[14] is not None else 0.0,
                    unexpectedness=float(row[15]) if row[15] is not None else 0.0,
                    semantic_distance=float(row[16]) if row[16] is not None else 0.0,
                    novelty=float(row[17]) if row[17] is not None else 0.0,
                    weirdness=float(row[18]) if row[18] is not None else 0.0,
                    scorer_version=str(row[19]) if row[19] else None,
                )
            )
        return insights

    async def update_explanation(
        self,
        insight_id: UUID,
        llm_explanation: str,
        explanation_model: str,
    ) -> None:
        """Persist LLM explanation for an insight (Wave E2)."""
        await self._session.execute(
            text("""
UPDATE path_insights
SET llm_explanation   = :llm_explanation,
    explanation_model = :explanation_model,
    explanation_at    = NOW()
WHERE insight_id = CAST(:insight_id AS UUID)
"""),
            {
                "insight_id": str(insight_id),
                "llm_explanation": llm_explanation,
                "explanation_model": explanation_model,
            },
        )
