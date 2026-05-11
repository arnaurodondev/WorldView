"""AGE Cypher graph endpoints (PRD-0018 §6.3).

  POST /api/v1/graph/cypher/path          — shortest path between two entities
  POST /api/v1/graph/cypher/neighborhood  — egocentric multi-hop neighborhood

Both endpoints are feature-flagged by ``KNOWLEDGE_GRAPH_CYPHER_ENABLED`` (default false).
Returns 503 when the flag is off; 504 on AGE query timeout (5 s).

Uses the write DB session (DbSessionDep) because AGE requires ``LOAD 'age'``
which is a session-level command that may not be supported on read replicas.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from knowledge_graph.api.dependencies import CypherBundleDep
from knowledge_graph.api.schemas import (
    CypherEdgeItem,
    CypherNeighborhoodRequest,
    CypherNeighborhoodResponse,
    CypherNodeItem,
    CypherPathItem,
    CypherPathRequest,
    CypherPathResponse,
    EntitySummary,
    RelationResponse,
    TemporalEventResponse,
)
from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase
from knowledge_graph.application.use_cases.cypher_path import (
    CypherDisabledError,
    CypherEntityNotFoundError,
    CypherPathUseCase,
    CypherTimeoutError,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1/graph/cypher", tags=["cypher"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _summary_authority(confidence: float | None, evidence_count: int) -> float:
    if confidence is None:
        return 0.0
    return round(confidence * math.log1p(evidence_count), 6)


def _entity_summary(row: dict[str, Any]) -> EntitySummary:
    return EntitySummary(
        entity_id=row["entity_id"],  # type: ignore[arg-type]
        canonical_name=str(row["canonical_name"]),
        entity_type=str(row["entity_type"]),
        isin=str(row["isin"]) if row.get("isin") else None,
        ticker=str(row["ticker"]) if row.get("ticker") else None,
        exchange=str(row["exchange"]) if row.get("exchange") else None,
    )


def _relation_response(row: dict[str, Any]) -> RelationResponse:
    evidence_count = int(row["evidence_count"])  # type: ignore[call-overload]
    confidence = float(row["confidence"]) if row.get("confidence") is not None else None  # type: ignore[arg-type]
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


def _lifecycle_phase(
    active_from: datetime,
    active_until: datetime | None,
    residual_impact_days: int,
) -> str:
    now = datetime.now(UTC)
    if now < active_from:
        return "PENDING_ACTIVE"
    if active_until is None or now <= active_until:
        return "ACTIVE"
    days_since_end = (now - active_until).days
    return "RESIDUAL" if days_since_end <= residual_impact_days else "EXPIRED"


def _temporal_event_response(row: dict[str, Any]) -> TemporalEventResponse:
    return TemporalEventResponse(
        event_id=row["event_id"],  # type: ignore[arg-type]
        event_type=str(row["event_type"]),
        scope=str(row["scope"]),
        region=str(row["region"]) if row.get("region") else None,
        title=str(row["title"]),
        description=str(row["description"]) if row.get("description") else None,
        active_from=row["active_from"],  # type: ignore[arg-type]
        active_until=row.get("active_until"),  # type: ignore[arg-type]
        residual_impact_days=int(row["residual_impact_days"]),  # type: ignore[call-overload]
        lifecycle_phase=_lifecycle_phase(
            active_from=row["active_from"],  # type: ignore[arg-type]
            active_until=row.get("active_until"),  # type: ignore[arg-type]
            residual_impact_days=int(row["residual_impact_days"]),  # type: ignore[call-overload]
        ),
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        exposed_entity_count=int(row["exposed_entity_count"]),  # type: ignore[call-overload]
        created_at=row["created_at"],  # type: ignore[arg-type]
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/path", response_model=CypherPathResponse)
async def cypher_path(
    body: CypherPathRequest,
    bundle: CypherBundleDep,
) -> CypherPathResponse:
    """Find shortest path(s) between two entities using Apache AGE Cypher.

    Returns 503 when ``KNOWLEDGE_GRAPH_CYPHER_ENABLED=false``.
    Returns 504 when the AGE query exceeds the 5 s statement_timeout.
    Returns 404 when source or target entity does not exist.
    Returns 422 when ``source_entity_id == target_entity_id`` or ``max_hops > 5``.
    """
    try:
        result = await CypherPathUseCase().execute(
            bundle.session,
            bundle.entity_repo,
            cypher_enabled=bundle.cypher_enabled,
            source_entity_id=body.source_entity_id,
            target_entity_id=body.target_entity_id,
            max_hops=body.max_hops,
            min_confidence=body.min_confidence,
            relation_types=body.relation_types,
            all_paths=body.all_paths,
        )
    except CypherDisabledError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "CYPHER_DISABLED", "message": "AGE Cypher is not enabled on this instance"},
        ) from exc
    except CypherEntityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "entity_not_found", "entity_id": str(exc.entity_id)},
        ) from exc
    except CypherTimeoutError as exc:
        _log.warning("cypher_path_timeout")
        raise HTTPException(
            status_code=504,
            detail={"error": "AGE_TIMEOUT", "message": "AGE Cypher query exceeded the 5 s statement_timeout"},
        ) from exc

    return CypherPathResponse(
        source_entity_id=result.source_entity_id,
        target_entity_id=result.target_entity_id,
        paths=[
            CypherPathItem(
                hops=p.hops,
                nodes=[
                    CypherNodeItem(entity_id=n.entity_id, canonical_name=n.canonical_name, entity_type=n.entity_type)
                    for n in p.nodes
                ],
                edges=[
                    CypherEdgeItem(
                        from_entity_id=e.from_entity_id,
                        to_entity_id=e.to_entity_id,
                        canonical_type=e.canonical_type,
                        confidence=e.confidence,
                        direction=e.direction,
                    )
                    for e in p.edges
                ],
                path_confidence=p.path_confidence,
            )
            for p in result.paths
        ],
        paths_found=result.paths_found,
        query_time_ms=result.query_time_ms,
    )


@router.post("/neighborhood", response_model=CypherNeighborhoodResponse)
async def cypher_neighborhood(
    body: CypherNeighborhoodRequest,
    bundle: CypherBundleDep,
) -> CypherNeighborhoodResponse:
    """Get egocentric neighborhood using Cypher (multi-hop, up to max_hops=3).

    Returns 503 when ``KNOWLEDGE_GRAPH_CYPHER_ENABLED=false``.
    Returns 504 when the AGE query exceeds the 5 s statement_timeout.
    Returns 404 when the entity does not exist.
    """
    try:
        result = await CypherNeighborhoodUseCase().execute(
            bundle.session,
            bundle.entity_repo,
            bundle.relation_repo,
            bundle.temporal_event_repo if body.include_temporal_events else None,
            cypher_enabled=bundle.cypher_enabled,
            entity_id=body.entity_id,
            max_hops=body.max_hops,
            min_confidence=body.min_confidence,
            include_temporal_events=body.include_temporal_events,
            limit=body.limit,
        )
    except CypherDisabledError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "CYPHER_DISABLED", "message": "AGE Cypher is not enabled on this instance"},
        ) from exc
    except CypherEntityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "entity_not_found", "entity_id": str(exc.entity_id)},
        ) from exc
    except CypherTimeoutError as exc:
        _log.warning("cypher_neighborhood_timeout")
        raise HTTPException(
            status_code=504,
            detail={"error": "AGE_TIMEOUT", "message": "AGE Cypher query exceeded the 5 s statement_timeout"},
        ) from exc

    center = _entity_summary(result.center_row)
    relations = [_relation_response(r) for r in result.relation_rows]
    entities: dict[str, EntitySummary] = {eid: _entity_summary(row) for eid, row in result.neighbor_rows.items()}
    temporal_events = [_temporal_event_response(r) for r in result.temporal_event_rows]

    return CypherNeighborhoodResponse(
        center=center,
        relations=relations,
        entities=entities,
        temporal_events=temporal_events,
    )
