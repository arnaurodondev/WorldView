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

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import EntityGraphReposDep
from knowledge_graph.api.schemas import (
    EntitySummary,
    GraphNeighborhoodResponse,
    GraphStatsResponse,
    RelationResponse,
    RelationsListResponse,
)
from knowledge_graph.application.use_cases.graph_query import (
    GetEntityGraphUseCase,
    GetGraphStatsUseCase,
    ListRelationsUseCase,
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


# ── Entity ticker lookup ──────────────────────────────────────────────────────


@router.get("/entities/lookup")
async def get_entity_by_ticker(
    ticker: str = Query(..., min_length=1, max_length=20),
    repos: EntityGraphReposDep = ...,  # type: ignore[assignment]
) -> dict[str, str]:
    """Resolve a ticker symbol to its KG entity_id.

    Used by the gateway to enrich company overview responses with the authoritative
    KG entity_id. Instrument IDs (market-data UUIDs) differ from KG entity_ids
    (canonical_entities UUIDs) — ADR-F-12.

    Returns {"entity_id": "<uuid>", "ticker": "<ticker>"} or 404 if not found.
    """
    row = await repos.entity_repo.find_by_ticker(ticker)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No entity found for ticker: {ticker}")
    return {"entity_id": str(row["entity_id"]), "ticker": str(row.get("ticker") or ticker)}


# ── Neighbourhood query ───────────────────────────────────────────────────────


@router.get("/entities/{entity_id}/graph", response_model=GraphNeighborhoodResponse)
async def get_entity_graph(
    entity_id: UUID,
    repos: EntityGraphReposDep,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    semantic_mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> GraphNeighborhoodResponse:
    """Return the egocentric graph neighbourhood for *entity_id*.

    Relations are filtered by ``min_confidence`` and optional ``semantic_mode``.
    ``summary_authority`` is computed at query time — NOT a cached column.
    """
    entity_row, relation_rows, entities_map_data = await GetEntityGraphUseCase().execute(
        entity_repo=repos.entity_repo,  # type: ignore[arg-type]
        relation_repo=repos.relation_repo,  # type: ignore[arg-type]
        entity_id=entity_id,
        min_confidence=min_confidence,
        semantic_mode=semantic_mode,
        limit=limit,
    )

    if entity_row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return GraphNeighborhoodResponse(
        center=_entity_summary(entity_row),
        relations=[_relation_response(r) for r in relation_rows],
        entities={k: _entity_summary(v) for k, v in entities_map_data.items()},
    )


# ── Relations list ────────────────────────────────────────────────────────────


@router.get("/relations", response_model=RelationsListResponse)
async def list_relations(
    repos: EntityGraphReposDep,
    subject_entity_id: UUID | None = Query(default=None),
    object_entity_id: UUID | None = Query(default=None),
    canonical_type: str | None = Query(default=None),
    semantic_mode: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> RelationsListResponse:
    """Paginated, filtered relation list."""
    rows, total = await ListRelationsUseCase().execute(
        relation_repo=repos.relation_repo,  # type: ignore[arg-type]
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
async def get_graph_stats(repos: EntityGraphReposDep) -> GraphStatsResponse:
    """Return aggregate knowledge graph statistics."""
    stats = await GetGraphStatsUseCase().execute(relation_repo=repos.relation_repo)  # type: ignore[arg-type]

    return GraphStatsResponse(
        entity_count=int(stats["entity_count"]),  # type: ignore[call-overload]
        relation_count=int(stats["relation_count"]),  # type: ignore[call-overload]
        evidence_count=int(stats["evidence_count"]),  # type: ignore[call-overload]
        stale_confidence_count=int(stats["stale_confidence_count"]),  # type: ignore[call-overload]
        contradiction_link_count=int(stats["contradiction_link_count"]),  # type: ignore[call-overload]
        relations_by_semantic_mode=stats["relations_by_semantic_mode"],  # type: ignore[arg-type]
    )
