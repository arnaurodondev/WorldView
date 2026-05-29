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
    SectorLabel,
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
                    # WHY `or 0.0` (not default arg): dict.get("confidence", 0.0) returns
                    # None when the key exists with value null (stale/unscored relations).
                    # The default only fires for absent keys. `or 0.0` converts both
                    # None and missing to 0.0 — prevents float(None) TypeError (BP-375).
                    "confidence": float(rel.get("confidence") or 0.0),
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

    # ── Entity name resolution (PLAN-0078) ────────────────────────────────────

    async def resolve_entity_by_name(
        self,
        name: str,
        limit: int = 5,
    ) -> list[dict]:
        """GET /api/v1/entities/resolve → fuzzy alias match for a plain-text entity name.

        Returns a list of candidates [{entity_id, alias_text, alias_type, similarity}]
        ordered by trigram similarity descending. Empty list on error or no match.
        """
        raw = await self._get(
            "/api/v1/entities/resolve",
            params={"name": name, "limit": limit},
        )
        if not raw:
            return []
        result: list[dict] = raw.get("candidates", [])
        return result

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
        """Two-entity path query or egocentric traversal via KG Cypher endpoints.

        BP-459-B FIX: The old implementation always called the single-entity
        ``/api/v1/graph/cypher/neighborhood`` endpoint, which returned egocentric
        relations rather than inter-entity paths.  This made two-entity queries
        (e.g. "Apple → Anthropic") always return [] because the neighborhood of
        Apple never explicitly surfaces the path to Anthropic.

        Resolution:
        - When ``params`` contains both ``"source_id"`` and ``"target_id"``, call
          the two-entity path endpoint POST /api/v1/graph/cypher/path.  The response
          shape is ``{source_entity_id, target_entity_id, paths, paths_found, ...}``.
          We flatten each path's nodes + edges into a list of dicts for the caller.
        - When only ``"source_id"`` is present (no target), fall back to the
          egocentric POST /api/v1/graph/cypher/neighborhood endpoint (unchanged).

        Returns empty list when feature is disabled (503) or on any error.
        This method NEVER raises; callers treat an empty list as unavailable.

        ``cypher`` is accepted for forward-compatibility logging but not forwarded
        to either endpoint — both endpoints construct Cypher server-side from the
        validated UUID parameters (BP-459-C / BP-450 security patterns).
        """
        source_id = params.get("source_id", params.get("id", ""))
        target_id = params.get("target_id")
        max_hops = int(params.get("max_hops", 2))

        if target_id:
            # ── Two-entity path query → /api/v1/graph/cypher/path ─────────────
            raw = await self._post(
                "/api/v1/graph/cypher/path",
                {
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "max_hops": min(max_hops, 5),  # CypherPathRequest.max_hops le=5
                    "min_confidence": 0.3,
                    "all_paths": True,  # return up to 5 shortest paths
                },
            )
            # Response shape: {source_entity_id, target_entity_id, paths, paths_found, ...}
            # Each path: {hops, nodes: [{entity_id, canonical_name, entity_type}],
            #             edges: [{from_entity_id, to_entity_id, canonical_type, confidence}]}
            # Flatten into a list of path dicts so the caller can iterate them.
            results: list[dict] = raw.get("paths", [])  # type: ignore[assignment]
            return results
        else:
            # ── Single-entity egocentric traversal → /api/v1/graph/cypher/neighborhood ─
            limit = min(max_results, 200)  # CypherNeighborhoodRequest.limit max=200
            raw = await self._post(
                "/api/v1/graph/cypher/neighborhood",
                {
                    "entity_id": source_id,
                    "max_hops": min(max_hops, 3),  # CypherNeighborhoodRequest.max_hops le=3
                    "min_confidence": 0.4,
                    "include_temporal_events": False,
                    "limit": limit,
                },
            )
            # Response shape: {center, relations, entities, temporal_events}
            # Flatten relations into a list of dicts for the caller.
            results = raw.get("relations", [])  # type: ignore[assignment]
            return results

    # ── PLAN-0102 W2 T-W2-03 — batch sector/industry lookup ────────────────────

    async def get_sectors_for_entities(
        self,
        entity_ids: list[UUID],
    ) -> dict[UUID, SectorLabel]:
        """GET /internal/v1/entities/sectors → ``{entity_id: SectorLabel}`` map.

        Returns ``{}`` on any HTTP / network error (R9 safe degradation).
        Caller (the morning brief gatherer) treats absent ids as
        "(sector unknown)" so a partial outage doesn't break the brief.
        """
        if not entity_ids:
            return {}
        # FastAPI multi-value query string: ``entity_ids=a&entity_ids=b...``
        # httpx accepts a list under one key — pass it through as a dict whose
        # value is the list of UUID strings.
        params: dict[str, list[str]] = {"entity_ids": [str(e) for e in entity_ids]}
        raw = await self._get("/internal/v1/entities/sectors", params=params)  # type: ignore[arg-type]
        results = raw.get("results", [])
        out: dict[UUID, SectorLabel] = {}
        for row in results:
            try:
                eid = UUID(str(row["entity_id"]))
            except (KeyError, ValueError):
                continue
            out[eid] = SectorLabel(
                entity_id=eid,
                sector=row.get("sector"),
                industry=row.get("industry"),
            )
        return out
