"""S7 Knowledge Graph HTTP client adapter (T-E-3-02).

Endpoints:
  POST /api/v1/search/relations         → ANN relation search
  GET  /api/v1/entities/{id}/graph      → egocentric sub-graph
  POST /api/v1/claims/search            → temporal claims
  POST /api/v1/events/search            → structured events
  GET  /api/v1/entities/{id}/contradictions → active contradictions
  POST /api/v1/graph/cypher/neighborhood → multi-hop Cypher (feature-flagged)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rag_chat.application.ports.upstream_clients import (
    ClaimResult,
    ContradictionResult,
    EgocentricGraph,
    EventResult,
    RelationResult,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S7Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S7 Knowledge Graph."""

    # ── Relation search ────────────────────────────────────────────────────────

    async def search_relations(
        self,
        embedding: list[float],
        entity_ids: list[UUID],
        top_k: int = 15,
        min_confidence: float = 0.30,
    ) -> list[RelationResult]:
        """POST /api/v1/search/relations → ANN relation results.

        Returns empty list on timeout or HTTP error.
        """
        payload: dict = {
            "query_embedding": embedding,
            "top_k": top_k,
            "min_confidence": min_confidence,
            "entity_ids": [str(eid) for eid in entity_ids],
        }
        raw = await self._post("/api/v1/search/relations", payload)
        results: list[RelationResult] = []
        for item in raw.get("relations", []):
            try:
                results.append(
                    RelationResult(
                        relation_id=item["relation_id"],
                        subject=item.get("subject", ""),
                        relation_type=item.get("relation_type", ""),
                        object=item.get("object", ""),
                        summary=item.get("summary", ""),
                        confidence=float(item.get("confidence", 0.0)),
                        summary_authority=item.get("summary_authority"),
                        evidence_count=int(item.get("evidence_count", 0)),
                        latest_evidence_at=item.get("latest_evidence_at"),
                        semantic_mode=item.get("semantic_mode"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Egocentric graph ───────────────────────────────────────────────────────

    async def get_egocentric_graph(
        self,
        entity_id: UUID,
        min_confidence: float,
        limit: int,
    ) -> EgocentricGraph:
        """GET /api/v1/entities/{id}/graph → egocentric sub-graph.

        WHY MAPPING: S7 returns {center, relations, entities} format (S7 native format).
        S9 transforms this to {nodes, edges} before sending to the frontend. Here we
        perform the same transformation so BriefingContextGatherer.gather_instrument_context()
        gets a populated EgocentricGraph instead of always receiving empty nodes/edges.

        Returns an empty graph on timeout or HTTP error.
        """
        raw = await self._get(
            f"/api/v1/entities/{entity_id}/graph",
            params={"min_confidence": min_confidence, "limit": limit},
        )
        if not raw:
            return EgocentricGraph(entity_id=str(entity_id))

        # ── Map S7 native format → EgocentricGraph ──────────────────────────────
        # S7 returns: {center: dict, relations: list[dict], entities: dict[str, dict]}
        # S7 native field names differ from the frontend-facing S9 transformation:
        #   - relations use "object_entity_id" (not "target_entity_id")
        #   - relations use "canonical_type" (not "relation_type")
        #   - entity names must be looked up from the "entities" dict by UUID key
        # EgocentricGraph expects: nodes=list[dict], edges=list[dict]

        nodes: list[dict] = []

        # Center entity — always include it as a node
        center = raw.get("center")
        if isinstance(center, dict):
            nodes.append(center)

        # All neighbouring entities (keyed by entity_id string)
        entities_by_id: dict[str, dict] = {}
        for _eid, entity_data in raw.get("entities", {}).items():
            if isinstance(entity_data, dict):
                entities_by_id[_eid] = entity_data
                if entity_data not in nodes:
                    nodes.append(entity_data)

        # Relations → edges
        # S7 native format: {relation_id, subject_entity_id, object_entity_id,
        #   canonical_type, confidence, ...}
        # BriefingContextGatherer._map_entity_graph() reads: relation_type, confidence,
        # target (or object), target_name (or object_name)
        edges: list[dict] = []
        for rel in raw.get("relations", []):
            if not isinstance(rel, dict):
                continue
            target_id = str(rel.get("object_entity_id", ""))
            # Look up the canonical name from the entities dict
            target_entity = entities_by_id.get(target_id, {})
            target_name = target_entity.get("canonical_name", "")
            edges.append(
                {
                    # Map S7 native field names to keys expected by _map_entity_graph()
                    "relation_type": rel.get("canonical_type", rel.get("relation_type", "")),
                    "confidence": float(rel.get("confidence", 0.0)),
                    "target": target_id,
                    "object": target_id,
                    "target_name": target_name,
                    "object_name": target_name,
                }
            )

        return EgocentricGraph(
            entity_id=raw.get("entity_id", str(entity_id)),
            nodes=nodes,
            edges=edges,
        )

    # ── Claims search ──────────────────────────────────────────────────────────

    async def search_claims(
        self,
        entity_ids: list[UUID],
        claim_types: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        top_k: int = 20,
        min_confidence: float = 0.45,
    ) -> list[ClaimResult]:
        """POST /api/v1/claims/search → temporal claims for entities.

        Returns empty list on timeout or HTTP error.
        """
        payload: dict = {
            "entity_ids": [str(eid) for eid in entity_ids],
            "top_k": top_k,
            "min_confidence": min_confidence,
            "claim_types": claim_types or [],
        }
        if date_from is not None:
            payload["date_from"] = date_from.date().isoformat()
        if date_to is not None:
            payload["date_to"] = date_to.date().isoformat()

        raw = await self._post("/api/v1/claims/search", payload)
        results: list[ClaimResult] = []
        for item in raw.get("claims", []):
            try:
                results.append(
                    ClaimResult(
                        claim_id=item["claim_id"],
                        subject_entity_id=item.get("subject_entity_id", ""),
                        claim_type=item.get("claim_type", ""),
                        polarity=item.get("polarity", ""),
                        claim_text=item.get("claim_text", ""),
                        extraction_confidence=float(item.get("extraction_confidence", 0.0)),
                        doc_id=item.get("doc_id"),
                        created_at=item.get("created_at"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Events search ──────────────────────────────────────────────────────────

    async def search_events(
        self,
        entity_ids: list[UUID],
        event_types: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        top_k: int = 20,
    ) -> list[EventResult]:
        """POST /api/v1/events/search → structured events for entities.

        Returns empty list on timeout or HTTP error.
        """
        payload: dict = {
            "entity_ids": [str(eid) for eid in entity_ids],
            "top_k": top_k,
            "event_types": event_types or [],
        }
        if date_from is not None:
            payload["date_from"] = date_from.date().isoformat()
        if date_to is not None:
            payload["date_to"] = date_to.date().isoformat()

        raw = await self._post("/api/v1/events/search", payload)
        results: list[EventResult] = []
        for item in raw.get("events", []):
            try:
                results.append(
                    EventResult(
                        event_id=item["event_id"],
                        event_type=item.get("event_type", ""),
                        event_text=item.get("event_text", ""),
                        subject_entity_id=item.get("subject_entity_id"),
                        event_subtype=item.get("event_subtype"),
                        event_date=item.get("event_date"),
                        structured_data=item.get("structured_data"),
                        extraction_confidence=float(item.get("extraction_confidence", 0.0)),
                        doc_id=item.get("doc_id"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Contradictions ─────────────────────────────────────────────────────────

    async def get_contradictions(
        self,
        entity_id: UUID,
        top_k: int = 5,
    ) -> list[ContradictionResult]:
        """GET /api/v1/entities/{id}/contradictions → active contradiction pairs.

        Returns empty list on timeout or HTTP error.
        """
        raw = await self._get(
            f"/api/v1/entities/{entity_id}/contradictions",
            params={"top_k": top_k},
        )
        results: list[ContradictionResult] = []
        for item in raw.get("contradictions", []):
            try:
                results.append(
                    ContradictionResult(
                        claim_type=item.get("claim_type", ""),
                        strength=float(item.get("strength", 0.0)),
                        detected_at=item.get("detected_at", ""),
                        sides=item.get("sides", []),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Cypher traversal (feature-flagged) ────────────────────────────────────

    async def cypher_traverse(
        self,
        cypher: str,
        params: dict,
        max_results: int = 50,
    ) -> list[dict]:
        """POST /api/v1/graph/cypher/neighborhood → egocentric multi-hop results.

        The ``params`` dict is expected to contain an ``"id"`` key with the
        entity UUID string (set by the caller in ``_fetch_cypher``).

        Returns empty list when feature is disabled (503) or on any error.
        This method NEVER raises; callers treat an empty list as unavailable.
        """
        entity_id = params.get("id", "")
        limit = min(max_results, 200)  # CypherNeighborhoodRequest.limit max=200
        raw = await self._post(
            "/api/v1/graph/cypher/neighborhood",
            {
                "entity_id": entity_id,
                "max_hops": 2,
                "min_confidence": 0.4,
                "include_temporal_events": False,
                "limit": limit,
            },
        )
        # Response shape: {center, relations, entities, temporal_events}
        # Flatten relations into a list of dicts for the caller
        results: list[dict] = raw.get("relations", [])  # type: ignore[assignment]
        return results
