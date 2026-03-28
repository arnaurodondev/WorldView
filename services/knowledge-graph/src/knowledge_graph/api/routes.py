"""REST API endpoints for the Knowledge Graph service (S7).

Endpoints:
  GET /api/v1/entities/{entity_id}/graph  — egocentric graph neighbourhood
  GET /api/v1/relations                   — paginated, filtered relation list
  GET /api/v1/graph/stats                 — aggregate graph statistics

``summary_authority()`` is computed at query time as:
    confidence * log1p(evidence_count)

It is NOT a cached column in the database.
"""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from knowledge_graph.api.schemas import (
    EntitySummary,
    GraphNeighborhoodResponse,
    GraphStatsResponse,
    RelationResponse,
    RelationsListResponse,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
    RelationRepository,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["graph"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


def _summary_authority(confidence: float | None, evidence_count: int) -> float:
    """Compute summary_authority at query time.

    Formula: confidence * log1p(evidence_count)
    Returns 0.0 when confidence is unknown (stale/null).
    """
    if confidence is None:
        return 0.0
    return round(confidence * math.log1p(evidence_count), 6)


def _entity_summary(row: dict[str, object]) -> EntitySummary:
    return EntitySummary(
        entity_id=row["entity_id"],  # type: ignore[arg-type]
        canonical_name=str(row["canonical_name"]),
        entity_type=str(row["entity_type"]),
        isin=str(row["isin"]) if row.get("isin") else None,
        ticker=str(row["ticker"]) if row.get("ticker") else None,
        exchange=str(row["exchange"]) if row.get("exchange") else None,
    )


def _relation_response(row: dict[str, object]) -> RelationResponse:
    evidence_count = int(row["evidence_count"])  # type: ignore[call-overload]
    confidence = float(row["confidence"]) if row.get("confidence") is not None else None  # type: ignore[call-overload, arg-type]
    return RelationResponse(
        relation_id=row["relation_id"],  # type: ignore[arg-type]
        subject_entity_id=row["subject_entity_id"],  # type: ignore[arg-type]
        object_entity_id=row["object_entity_id"],  # type: ignore[arg-type]
        canonical_type=str(row["canonical_type"]),
        semantic_mode=str(row["semantic_mode"]),
        decay_class=str(row["decay_class"]),
        confidence=confidence,
        confidence_stale=bool(row["confidence_stale"]),
        summary_authority=_summary_authority(confidence, evidence_count),
        evidence_count=evidence_count,
        first_evidence_at=row["first_evidence_at"],  # type: ignore[arg-type]
        latest_evidence_at=row["latest_evidence_at"],  # type: ignore[arg-type]
    )


# ── Neighbourhood query ───────────────────────────────────────────────────────


@router.get("/entities/{entity_id}/graph", response_model=GraphNeighborhoodResponse)
async def get_entity_graph(
    entity_id: UUID,
    request: Request,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    semantic_mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> GraphNeighborhoodResponse:
    """Return the egocentric graph neighbourhood for *entity_id*.

    Relations are filtered by ``min_confidence`` and optional ``semantic_mode``.
    ``summary_authority`` is computed at query time — NOT a cached column.
    """
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        entity_repo = CanonicalEntityRepository(session)
        entity_row = await entity_repo.get(entity_id)
        if entity_row is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        relation_repo = RelationRepository(session)
        relation_rows = await relation_repo.list_for_entity(
            entity_id=entity_id,
            min_confidence=min_confidence,
            semantic_mode=semantic_mode,
            limit=limit,
        )

        # Collect all referenced entity_ids (excluding center)
        referenced_ids: set[UUID] = set()
        for r in relation_rows:
            sub = r["subject_entity_id"]
            obj = r["object_entity_id"]
            if isinstance(sub, UUID) and sub != entity_id:
                referenced_ids.add(sub)
            if isinstance(obj, UUID) and obj != entity_id:
                referenced_ids.add(obj)

        # Fetch all referenced entities
        entities_map: dict[str, EntitySummary] = {}
        for ref_id in referenced_ids:
            ref_row = await entity_repo.get(ref_id)
            if ref_row is not None:
                entities_map[str(ref_id)] = _entity_summary(ref_row)

    return GraphNeighborhoodResponse(
        center=_entity_summary(entity_row),
        relations=[_relation_response(r) for r in relation_rows],
        entities=entities_map,
    )


# ── Relations list ────────────────────────────────────────────────────────────


@router.get("/relations", response_model=RelationsListResponse)
async def list_relations(
    request: Request,
    subject_entity_id: UUID | None = Query(default=None),
    object_entity_id: UUID | None = Query(default=None),
    canonical_type: str | None = Query(default=None),
    semantic_mode: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> RelationsListResponse:
    """Paginated, filtered relation list."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        relation_repo = RelationRepository(session)
        rows, total = await relation_repo.list_filtered(
            subject_entity_id=subject_entity_id,
            object_entity_id=object_entity_id,
            canonical_type=canonical_type,
            semantic_mode=semantic_mode,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )

    return RelationsListResponse(
        items=[_relation_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Graph statistics ──────────────────────────────────────────────────────────


@router.get("/graph/stats", response_model=GraphStatsResponse)
async def get_graph_stats(request: Request) -> GraphStatsResponse:
    """Return aggregate knowledge graph statistics."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        relation_repo = RelationRepository(session)
        stats = await relation_repo.get_stats()

    return GraphStatsResponse(
        entity_count=int(stats["entity_count"]),  # type: ignore[call-overload]
        relation_count=int(stats["relation_count"]),  # type: ignore[call-overload]
        evidence_count=int(stats["evidence_count"]),  # type: ignore[call-overload]
        stale_confidence_count=int(stats["stale_confidence_count"]),  # type: ignore[call-overload]
        contradiction_link_count=int(stats["contradiction_link_count"]),  # type: ignore[call-overload]
        relations_by_semantic_mode=stats["relations_by_semantic_mode"],  # type: ignore[arg-type]
    )
