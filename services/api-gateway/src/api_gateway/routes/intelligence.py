"""Intelligence, knowledge graph, narratives, and prediction market routes.

Handles /v1/entities/{id}/graph, /v1/entities/{id}/intelligence,
/v1/entities/{id}/narratives, /v1/entities/{id}/paths,
/v1/entities/{id}/contradictions, /v1/search/relations, /v1/claims/search,
/v1/signals/prediction-markets/* — proxies to S7 Knowledge Graph and S3 Market Data.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients
from api_gateway.schemas import (
    EntityIntelligenceBundleResponse,
    PredictionMarket,
    PredictionMarketsListResponse,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


# ── Entity Graph + Contradictions (PRD-0028 Wave S9-1) ───────────────────────


def _transform_graph_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Transform S7 GraphNeighborhoodResponse → frontend EntityGraph format.

    S7 returns: {center, relations, entities}
    Frontend expects: {entity_id, nodes, edges}

    WHY transform here (not in S7): S7 owns the domain model; S9 owns the
    presentation contract. This transformation is a BFF (Backend For Frontend)
    concern — S9 is the composition layer whose job is to shape data for the UI.
    Changing S7's response would couple the knowledge-graph domain to a single
    frontend's rendering requirements.

    Resilience: all field accesses use .get() with safe defaults so partial or
    missing fields from S7 never raise KeyError / TypeError in the gateway.
    """
    center = raw.get("center") or {}
    relations = raw.get("relations") or []
    entities = raw.get("entities") or {}

    entity_id = str(center.get("entity_id") or "")

    # Build nodes: center node first (size=2 makes it visually prominent in the
    # Cytoscape.js graph), then all related entities (size=1).
    nodes: list[dict[str, Any]] = []
    if entity_id:
        nodes.append(
            {
                "id": entity_id,
                "label": center.get("canonical_name") or "",
                "type": center.get("entity_type") or "unknown",
                "size": 2,  # Center node rendered larger than neighbors
                # WHY ticker: PeerComparisonPanel needs ticker to look up S3
                # fundamentals (entity_id ≠ instrument_id; resolved by ticker).
                "ticker": center.get("ticker") or "",
                # B-01 (Block I T-25): description and sector are optional fields
                # from S7 EntitySummary. Included here so the frontend type contract
                # is stable — InlineSelectionPanel may render them if present.
                "description": center.get("description") or None,
                "sector": center.get("sector") or None,
                # T-A-1-03 (PLAN-0091): from canonical_entities.metadata JSONB via S7.
                "industry": center.get("industry") or None,
                "market_cap": center.get("market_cap") or None,
            },
        )

    for eid, entity_data in entities.items():
        if eid == entity_id:
            # Skip if S7 also includes the center in the entities dict
            continue
        nodes.append(
            {
                "id": str(entity_data.get("entity_id") or eid),
                "label": entity_data.get("canonical_name") or "",
                "type": entity_data.get("entity_type") or "unknown",
                "size": 1,
                "ticker": entity_data.get("ticker") or "",
                # B-01: description and sector forwarded if S7 provides them.
                "description": entity_data.get("description") or None,
                "sector": entity_data.get("sector") or None,
                # T-A-1-03 (PLAN-0091): industry + market_cap from S7 EntitySummary.
                "industry": entity_data.get("industry") or None,
                "market_cap": entity_data.get("market_cap") or None,
            },
        )

    # Build edges from S7 relations; skip any relation missing required fields
    # (relation_id / subject / object) rather than emitting a malformed edge.
    # WHY .lower(): canonical_type is stored lowercase in the DB for relations
    # created via the NLP pipeline but some seeded relations used uppercase
    # (e.g., "COMPETES_WITH"). Normalising to lowercase here means frontend
    # code can always filter with a single lowercase comparison.
    edges: list[dict[str, Any]] = []
    for rel in relations:
        rel_id = str(rel.get("relation_id") or "")
        src = str(rel.get("subject_entity_id") or "")
        tgt = str(rel.get("object_entity_id") or "")
        if not rel_id or not src or not tgt:
            continue
        # WHY direction: asymmetric relation types (employs, has_executive, acquired_by,
        # subsidiary_of, supplier_of, regulates) are semantically different depending on
        # which entity is the subject vs object. "outbound" = center entity is the
        # subject (the initiating/owning side); "inbound" = center entity is the object
        # (the receiving side); "lateral" = edge between two non-center entities (depth>1).
        if entity_id and src == entity_id:
            direction = "outbound"
        elif entity_id and tgt == entity_id:
            direction = "inbound"
        else:
            direction = "lateral"

        edges.append(
            {
                "id": rel_id,
                "source": src,
                "target": tgt,
                "label": (rel.get("canonical_type") or "").lower(),
                "weight": float(rel.get("confidence") or 0.5),
                # WHY: S7 returns these from relation_summaries (Worker 13C) and
                # relation_evidence_raw respectively. They are forwarded here so
                # the frontend EntitySidebar can render LLM summaries and evidence
                # snippets in the Top Relations panel without a second API call.
                "relation_summary": rel.get("relation_summary"),  # str | None
                "evidence_snippets": rel.get("evidence_snippets") or [],  # list[str]
                # B-02 (Block I T-25): decay_class drives edge opacity in the sigma
                # edgeReducer (PERMANENT/DURABLE=1.0, SLOW/MEDIUM=0.7, FAST/EPHEMERAL=0.4).
                # None when S7 omits it — frontend defaults to MEDIUM opacity.
                "decay_class": rel.get("decay_class") or None,  # str | None
                "direction": direction,  # "outbound" | "inbound" | "lateral"
                # T-A-1-02 (PLAN-0091): temporal validity fields from S7 confidence_breakdown.
                "valid_from": str(rel["valid_from"]) if rel.get("valid_from") else None,
                "valid_to": str(rel["valid_to"]) if rel.get("valid_to") else None,
                "confidence_stale": bool(rel.get("confidence_stale") or False),
            },
        )

    # WHY filter orphan edges: S7 may include relations whose endpoints are not
    # present in the `entities` dict (e.g. entities filtered by confidence threshold
    # or missing from canonical_entities). These produce dangling edges that sigma
    # renders as "orphan" nodes with no visual connections — very confusing.
    # Filter BEFORE filtering orphan nodes so the node filter sees accurate edge data.
    node_id_set = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_id_set and e["target"] in node_id_set]

    # WHY filter orphan nodes: at depth=2 S7's CypherNeighborhoodUseCase correctly
    # discovers depth-2 neighbor_ids via AGE Cypher, but `relation_repo.list_for_entity`
    # only returns direct (depth=1) relations of the center entity. Result: depth-2
    # nodes arrive in `entities` but have no connecting edges in `relations`. These
    # render as isolated floating nodes — worse than not showing them.
    # Keep the center node unconditionally (it is the page anchor).
    edge_endpoints: set[str] = set()
    for e in edges:
        edge_endpoints.add(e["source"])
        edge_endpoints.add(e["target"])
    nodes = [n for n in nodes if n["id"] == entity_id or n["id"] in edge_endpoints]

    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(
    entity_id: UUID,  # WHY UUID not str: enforces 422 on malformed values before any downstream call
    request: Request,
    limit: int = Query(default=40, ge=1, le=200),
    depth: int = Query(default=1, ge=1, le=3),
    confidence_breakdown: bool = Query(default=False),
    focus_node: str | None = Query(default=None, max_length=36),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    semantic_mode: str | None = Query(default=None, max_length=20),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/graph → S7 Knowledge Graph.

    Requires authentication. Forwards query parameters (min_confidence, etc.)
    for entity relationship graph traversal.

    WHY explicit limit param (was pass-through):
    S7's GetEntityGraphUseCase does N+1 DB round-trips — one entity lookup per
    unique entity referenced in the returned relations. With S7's default of
    limit=50 relations and a dense entity graph, this means up to 50 sequential
    entity fetches. By capping at 50 here and defaulting to 40, we bound the
    worst-case DB latency.

    The frontend now sends explicit limits (15 for sidebar depth=1, 40 for
    Intelligence tab depth=2) so the default of 40 is just a safety fallback.

    WHY le=200 (PLAN-0088 P0-8, 2026-05-10 — was le=50): the previous cap of 50
    silently truncated demo entities like AAPL whose entity neighborhood routinely
    exceeds 50 high-confidence relations, and the FE depth slider was unable to
    request more than that no matter what value the analyst dragged it to. Lifting
    the gateway cap to 200 (S7's hard upper bound) lets the slider's "show more"
    extreme actually deliver more edges. Each unit increment in the FE slider now
    bumps `limit` linearly so the slider has visible effect at every step.

    WHY forward depth (ISSUE-5 fix, 2026-05-10 — was silently stripped):
    S7 supports depth=1/2/3 via AGE Cypher multi-hop graph traversal.
    depth=1 uses the standard SQL neighbourhood query (default, fast).
    depth=2/3 require KNOWLEDGE_GRAPH_CYPHER_ENABLED=true in the KG service
    and use AGE Cypher to traverse 2- or 3-hop paths. The previous comment
    claiming "S7 has no depth param" was incorrect — depth is a first-class
    Query param at S7 GET /api/v1/entities/{id}/graph (ge=1, le=3).

    WHY transform instead of raw proxy: S7 returns GraphNeighborhoodResponse
    {center, relations, entities} but the frontend Cytoscape.js renderer
    expects EntityGraph {entity_id, nodes, edges}. _transform_graph_response()
    bridges the mismatch at the BFF layer so neither S7 nor the frontend needs
    to change.

    PLAN-0074 Wave G: ``confidence_breakdown`` and ``focus_node`` are now
    forwarded to S7 (Wave D additions — previously silently ignored).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    # Build params: all forwarded values are typed FastAPI Query params — no raw_params.
    # WHY no raw_params forwarding: unvalidated query strings allow any string (including
    # injection payloads) to reach S7. Typed params get 422 from FastAPI before any I/O.
    s7_params: dict[str, str] = {"limit": str(limit)}
    if min_confidence is not None:
        s7_params["min_confidence"] = str(min_confidence)
    if semantic_mode is not None:
        s7_params["semantic_mode"] = semantic_mode
    # ISSUE-5 (2026-05-10): forward depth to S7 which supports AGE Cypher multi-hop
    # traversal. depth=1 is S7's default (SQL query) so only send when >1 to avoid
    # a redundant param on the common case. depth>1 requires KNOWLEDGE_GRAPH_CYPHER_ENABLED.
    if depth > 1:
        s7_params["depth"] = str(depth)
    # T-A-1-02 (PLAN-0091): always request confidence_breakdown=true so S7
    # populates valid_from/valid_to/confidence_stale on every RelationResponse.
    # Ignore the client-supplied confidence_breakdown param — we always want
    # the full breakdown to forward temporal edge fields to the frontend.
    s7_params["confidence_breakdown"] = "true"
    if focus_node is not None:
        s7_params["focus_node"] = focus_node

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/graph",
        params=s7_params,
        headers=headers,
    )
    # Pass non-2xx responses through unchanged (404 = entity not found, etc.)
    if resp.status_code >= 400:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    raw: dict[str, Any] = resp.json()
    transformed = _transform_graph_response(raw)

    # WHY merge depth=1 when depth>1 (BP-S9-GRAPH-001):
    # S7's CypherNeighborhoodUseCase uses AGE to discover depth-N neighbor IDs,
    # then fetches those entities from SQL. At depth=2, AGE fills its LIMIT with
    # second-order entities, and the `relations` list only contains the center's
    # direct (depth=1) relations. After orphan-filtering, the depth=2 graph ends up
    # with fewer connected nodes than depth=1, which is counter-intuitive and broken.
    # Fix: always re-fetch depth=1 (fast SQL, no AGE) and merge its nodes+edges into
    # the higher-depth result. The union is then orphan-filtered by _transform_graph_response.
    if depth > 1:
        # WHY share filter params (F-205): min_confidence and semantic_mode from
        # the caller apply to all depths — omitting them from the depth=1 merge
        # call would surface lower-quality edges than the primary call filtered out.
        depth1_params: dict[str, str] = {"limit": str(limit)}
        if min_confidence is not None:
            depth1_params["min_confidence"] = str(min_confidence)
        if semantic_mode is not None:
            depth1_params["semantic_mode"] = semantic_mode
        depth1_resp = await clients.knowledge_graph.get(
            f"/api/v1/entities/{entity_id}/graph",
            params=depth1_params,  # no depth param → depth=1 SQL path
            headers=headers,
        )
        if depth1_resp.status_code == 200:
            raw1: dict[str, Any] = depth1_resp.json()
            t1 = _transform_graph_response(raw1)
            # Merge: take union of nodes and edges; deduplicate by id.
            existing_node_ids = {n["id"] for n in transformed["nodes"]}
            existing_edge_ids = {e["id"] for e in transformed["edges"]}
            for n in t1["nodes"]:
                if n["id"] not in existing_node_ids:
                    transformed["nodes"].append(n)
                    existing_node_ids.add(n["id"])
            for e in t1["edges"]:
                if e["id"] not in existing_edge_ids:
                    transformed["edges"].append(e)
                    existing_edge_ids.add(e["id"])
            # Re-apply orphan filter after merge (new edges may validate previously-
            # orphan nodes, and new nodes may validate previously-orphan edges).
            node_id_set2 = {n["id"] for n in transformed["nodes"]}
            transformed["edges"] = [
                e for e in transformed["edges"] if e["source"] in node_id_set2 and e["target"] in node_id_set2
            ]
            edge_eps2: set[str] = set()
            for e in transformed["edges"]:
                edge_eps2.add(e["source"])
                edge_eps2.add(e["target"])
            transformed["nodes"] = [
                n for n in transformed["nodes"] if n["id"] == str(entity_id) or n["id"] in edge_eps2
            ]

    return Response(
        content=json.dumps(transformed).encode(),
        status_code=resp.status_code,
        media_type="application/json",
    )


@router.get("/entities/{entity_id}/contradictions")
async def get_entity_contradictions(entity_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/contradictions → S7 Knowledge Graph.

    Requires authentication. Returns detected contradictions for the entity.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/contradictions",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/search/relations")
async def search_relations(request: Request) -> Any:
    """Proxy POST /api/v1/search/relations → S7 Knowledge Graph.

    ANN search over relation summaries using a query embedding.
    Returns relations ordered by cosine similarity (most similar first).
    Auth required. Forwards X-Internal-JWT to S7.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/search/relations",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/claims/search")
async def search_claims(request: Request) -> Any:
    """Proxy POST /api/v1/claims/search → S7 Knowledge Graph.

    Search analyst claims for a set of entities with optional filters.
    Returns claims ordered by extraction_confidence DESC.
    Auth required. Forwards X-Internal-JWT to S7.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/claims/search",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Entity Intelligence, Narratives, Paths (PLAN-0074 Wave G) ────────────────
#
# All 5 new routes proxy to S7 Knowledge Graph or S8 RAG-Chat.
# Cache keys follow the pattern: <resource>:<tenant_id>:<entity_id>[:<params_hash>]
# BP-200: rate limiting uses set_nx(key, val, ex=N) — NOT set(..., nx=True).
# BP-235: httpx clients are configured with explicit Timeout(N) in app.py lifespan.


@router.get(
    "/entities/{entity_id}/intelligence",
    summary="Entity intelligence aggregate (PLAN-0074 Wave G)",
)
async def get_entity_intelligence(
    entity_id: UUID,
    request: Request,
    confidence_breakdown: bool = Query(default=False),
    focus_node: str | None = Query(default=None, max_length=36),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/intelligence → S7 Knowledge Graph.

    Returns the full entity intelligence aggregate: health score, current
    narrative, confidence breakdown, key metrics, and data completeness.

    Caching strategy:
      - Cache key: ``intel:<tenant_id>:<entity_id>`` (60 s TTL).
      - On hit: return cached JSON directly, skipping the S7 round-trip.
      - On miss: proxy to S7, cache the 200 response, return to caller.
      - Non-2xx responses are never cached (transient errors should not be
        cached; 404 means entity missing — may change soon).
      - Fail-open: Valkey errors are silently swallowed; the request
        proceeds to S7 as if the cache were empty.

    WHY cache at 60 s: intelligence aggregates are computed nightly by the
    KG scheduler; they don't change within a session.  60 s is a safe window
    that avoids thundering-herd on the Intelligence Tab's initial load while
    still refreshing quickly enough for dev/debug cycles.

    Requires authentication.  Forward ``confidence_breakdown`` and
    ``focus_node`` query params to S7 (Wave D additions).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    # Include forwarded params in the cache key so different param combinations
    # are not served the same cached response (e.g. confidence_breakdown=true vs false).
    cache_key = f"intel:{tenant_id}:{entity_id}:{int(confidence_breakdown)}:{focus_node or ''}"
    valkey = getattr(request.app.state, "valkey", None)

    # ── Cache hit check ─────────────────────────────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                return Response(content=cached, status_code=200, media_type="application/json")
        except Exception:
            # Fail-open: Valkey error must not block the request.
            logger.warning("intelligence_cache_read_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)

    # Forward only the known S7 query params; strip unknown ones.
    s7_params: dict[str, str] = {}
    if confidence_breakdown:
        s7_params["confidence_breakdown"] = "true"
    if focus_node is not None:
        s7_params["focus_node"] = focus_node

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/intelligence",
        params=s7_params if s7_params else None,
        headers=headers,
    )

    # ── Cache store (only 2xx) ───────────────────────────────────────────────
    if resp.status_code < 400 and valkey is not None:
        try:
            # WHY ex= (not ttl=): aligns with the ValkeyClient.set() signature.
            await valkey.set(cache_key, resp.content.decode(), ex=60)
        except Exception:
            # Fail-open: caching is best-effort.
            logger.warning("intelligence_cache_write_failed", entity_id=str(entity_id))

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/entities/{entity_id}/narratives",
    summary="Paginated narrative version history (PLAN-0074 Wave G)",
)
async def get_entity_narratives(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/narratives → S7 Knowledge Graph.

    Returns paginated narrative version history for an entity, newest first.
    Supply ``cursor`` from the previous response's ``next_cursor`` field to
    page forward.  No caching — paginated endpoints change frequently.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)

    params: dict[str, str | int] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/narratives",
        params=params,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post(
    "/entities/{entity_id}/narratives/generate",
    status_code=202,
    summary="Manually trigger narrative generation (PLAN-0074 Wave G)",
)
async def trigger_entity_narrative_generation(
    entity_id: UUID,
    request: Request,
) -> Any:
    """Proxy POST /api/v1/entities/{entity_id}/narratives/generate → S7.

    Rate-limited to one request per entity+tenant+user per hour at the S9
    proxy layer (in addition to the identical rate limit enforced by S7).

    Why rate-limit at S9 too: defence-in-depth.  An unauthenticated attacker
    who somehow reaches S7 directly is blocked there, but authenticated callers
    who hammer the gateway are stopped here before the request even reaches S7.

    Rate-limit key: ``narrative_gen_proxy:<tenant_id>:<entity_id>:<user_id>``
    BP-200: uses set_nx(key, "1", ex=3600) — NOT set(..., nx=True).

    On 429: returns ``Retry-After: 3600`` header.
    On Valkey unavailable: proxy proceeds without rate limiting (fail-open).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    user_id: str = str(user.get("user_id") or user.get("sub", "anonymous"))

    # ── Proxy-layer rate limit (BP-200) ─────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        rl_key = f"narrative_gen_proxy:{tenant_id}:{entity_id}:{user_id}"
        try:
            allowed = await valkey.set_nx(rl_key, "1", ex=3600)
            if not allowed:
                # Key already existed → rate limit hit.
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit: one manual generation per hour.",
                    headers={"Retry-After": "3600"},
                )
        except HTTPException:
            raise
        except Exception:
            # Fail-open: Valkey error → allow the request through.
            logger.warning("narrative_gen_proxy_rl_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        f"/api/v1/entities/{entity_id}/narratives/generate",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Entity refresh trigger (REQ-003 / TASK-W0-06) ─────────────────────────────


@router.post(
    "/entities/{entity_id}/refresh",
    status_code=202,
    summary="Manually trigger entity re-enrichment (REQ-003)",
)
async def trigger_entity_refresh(
    entity_id: UUID,
    request: Request,
) -> Any:
    """Proxy ``POST /api/v1/entities/{entity_id}/refresh`` → S7.

    Body (forwarded verbatim)::

        {"refresh_type": "description" | "narrative" | "all"}   (default "all")

    Rate-limited to one request per entity+tenant+user per hour at the S9
    proxy layer (in addition to the identical rate limit enforced by S7).
    Defence-in-depth — same posture as ``trigger_entity_narrative_generation``.

    Rate-limit key: ``entity_refresh_proxy:<tenant_id>:<entity_id>:<user_id>``
    BP-200: uses ``set_nx(key, "1", ex=3600)`` — NOT ``set(..., nx=True)``.

    - 202: refresh queued (job_id returned).
    - 401: missing/invalid authentication.
    - 404: entity_id not found in canonical_entities.
    - 422: invalid refresh_type or malformed UUID.
    - 429: rate limit hit — ``Retry-After: 3600`` header included.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    user_id: str = str(user.get("user_id") or user.get("sub", "anonymous"))

    # ── Proxy-layer rate limit (BP-200) ─────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        rl_key = f"entity_refresh_proxy:{tenant_id}:{entity_id}:{user_id}"
        try:
            allowed = await valkey.set_nx(rl_key, "1", ex=3600)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit: one entity refresh per hour.",
                    headers={"Retry-After": "3600"},
                )
        except HTTPException:
            raise
        except Exception:
            # Fail-open: Valkey error → allow the request through.
            logger.warning("entity_refresh_proxy_rl_failed", entity_id=str(entity_id))

    # ── Forward the JSON body verbatim to S7 ────────────────────────────────
    # Reading the body once (FastAPI accepts None content-type bodies); falling
    # back to an empty dict when the client sent no body — S7 will default
    # refresh_type to "all".
    try:
        body_bytes: bytes = await request.body()
    except Exception:
        body_bytes = b""

    headers = _auth_headers(request)
    # Preserve Content-Type so S7 deserialises the body correctly when present.
    if body_bytes:
        headers.setdefault("Content-Type", request.headers.get("Content-Type", "application/json"))

    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        f"/api/v1/entities/{entity_id}/refresh",
        content=body_bytes if body_bytes else None,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/entities/{entity_id}/paths",
    summary="Multi-hop opportunity paths for an entity (PLAN-0074 Wave G)",
)
async def get_entity_paths(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
    min_hops: int = Query(default=2, ge=2, le=5),
    max_hops: int = Query(default=5, ge=2, le=5),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/paths → S7 Knowledge Graph.

    Returns top-N pre-computed multi-hop opportunity paths originating from
    the entity, ordered by composite_score descending.

    Caching strategy (5-minute TTL):
      - Cache key: ``paths:<tenant_id>:<entity_id>:<limit>:<min_score>:<min_hops>:<max_hops>``
      - Paths are recomputed nightly by the KG scheduler; 5 min is safe.
      - Non-2xx responses are never cached.
      - Fail-open on Valkey errors.

    Query param validation mirrors S7: 422 if min_hops > max_hops.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate hop range here for a clean 422 (S7 also validates).
    if min_hops > max_hops:
        raise HTTPException(
            status_code=422,
            detail=f"min_hops ({min_hops}) must be <= max_hops ({max_hops})",
        )

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    # Build a deterministic cache key from all query params.
    cache_key = f"paths:{tenant_id}:{entity_id}:{limit}:{min_score}:{min_hops}:{max_hops}"
    valkey = getattr(request.app.state, "valkey", None)

    # ── Cache hit ────────────────────────────────────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                return Response(content=cached, status_code=200, media_type="application/json")
        except Exception:
            logger.warning("paths_cache_read_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/paths",
        params={
            "limit": limit,
            "min_score": min_score,
            "min_hops": min_hops,
            "max_hops": max_hops,
        },
        headers=headers,
    )

    # ── Cache store (5 min — paths change nightly) ───────────────────────────
    if resp.status_code < 400 and valkey is not None:
        try:
            await valkey.set(cache_key, resp.content.decode(), ex=300)
        except Exception:
            logger.warning("paths_cache_write_failed", entity_id=str(entity_id))

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Intelligence-tab bundle (PLAN-0099 H) ────────────────────────────────────


# Default graph parameters for the bundle's depth=2 leg. These mirror the
# frontend's GraphColumn cold-start request so the hydrated cache slot matches
# the per-widget query key the GraphColumn issues (qk.instruments.entityGraph(id, 2)).
# WHY limit=40: GraphColumn caps at 40 nodes for sigma.js WebGL comfort
# (knowledge-graph.ts:70). Lower would force a refetch; higher wastes payload.
# WHY min_confidence=0.0: Intelligence-tab full view shows all edges.
_BUNDLE_GRAPH_DEPTH = 2
_BUNDLE_GRAPH_LIMIT = 40
# WHY default paths params: match the PathInsightsBlock's `limit=3` default
# (PathInsightsBlock.tsx:38) and S7's path defaults — these are the values the
# UI fetches on cold start so the cache hydrates the exact same call signature.
# Note: useEntityPaths uses an empty PathFilters object by default — calling
# with no params yields the S9 defaults (limit=10, min_score=0.3, hops 2-5).
_BUNDLE_PATHS_LIMIT = 10
_BUNDLE_PATHS_MIN_SCORE = 0.3
_BUNDLE_PATHS_MIN_HOPS = 2
_BUNDLE_PATHS_MAX_HOPS = 5


async def _bundle_fetch_json(
    client: Any,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    leg: str,
) -> dict[str, Any] | None:
    """Fetch one bundle leg; return None on any failure (typed dict or None).

    WHY swallow Exception broadly: per-leg failures must not poison the whole
    bundle. The frontend renders skeletons / "—" for null legs. Mirrors the
    fail-soft pattern in clients/dashboard_bundle.py.
    """
    try:
        resp = await client.get(path, params=params, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "entity_intelligence_bundle_leg_non2xx",
                leg=leg,
                path=path,
                status=resp.status_code,
            )
            return None
        data: dict[str, Any] = resp.json()
        return data
    except Exception:
        logger.warning("entity_intelligence_bundle_leg_failed", leg=leg, path=path)
        return None


@router.get(
    "/entities/{entity_id}/intelligence-bundle",
    response_model=EntityIntelligenceBundleResponse,
    response_model_exclude_none=False,
    summary="Entity Intelligence tab composite bundle (PLAN-0099 H)",
)
async def get_entity_intelligence_bundle(
    entity_id: UUID,
    request: Request,
) -> Any:
    """Collapse the 4-5 Intelligence-tab queries into one round-trip.

    See ``EntityIntelligenceBundleResponse`` for the field contract. Each leg
    is fetched via ``asyncio.gather(return_exceptions=True)`` and degrades
    independently to None on failure — the page hydrates per-widget caches
    and renders skeletons for null legs.

    Legs:
      detail               : S7 GET /api/v1/entities/{id}
      brief                : S8 GET /api/v1/briefings/instrument/{id}
      graph_d2             : S7 GET /api/v1/entities/{id}/graph?depth=2 (transformed
                             via _transform_graph_response so the shape matches the
                             frontend's getEntityGraph cache slot).
      paths                : S7 GET /api/v1/entities/{id}/paths
      intelligence_summary : S7 GET /api/v1/entities/{id}/intelligence

    Caching strategy (5-minute TTL, cache key v2):
      - Cache key: ``entity:bundle:v2:<entity_id>`` (TTL = 300 s).
      - WHY bundle-level cache even though legs already cache individually:
        the AGE graph traversal (depth=2) is the dominant cost (~2-3 s) and
        is NOT cached at the individual /graph endpoint.  Caching the whole
        serialised bundle avoids 6 fan-out HTTP calls on warm requests,
        cutting p50 from ~5 s to < 50 ms.
      - WHY 300 s: news ingestion runs hourly; entity data changes at most
        once per hour.  5-minute TTL balances freshness with latency reduction.
      - WHY v2 suffix: invalidates any stale v1 keys left from earlier builds.
      - Fail-open: Valkey errors are silently swallowed so the request always
        proceeds to the live backends.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # ── Bundle-level Valkey cache (5 min TTL) ───────────────────────────────
    # WHY entity_id only (no tenant_id): intelligence bundles are public data
    # (no user-private fields) so a per-entity cache key is safe across tenants
    # and maximises cache hit rate.
    cache_key = f"entity:bundle:v2:{entity_id}"
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                return Response(content=cached, status_code=200, media_type="application/json")
        except Exception:
            # Fail-open: Valkey error must not block the request.
            logger.warning("bundle_cache_read_failed", entity_id=str(entity_id))

    headers = _auth_headers(request)
    clients = _clients(request)

    # WHY str(entity_id) once: UUID-to-str repeated under N tasks is cheap but
    # consistent stringification avoids a future refactor accidentally feeding
    # the raw UUID object into f-strings (PYC's `repr` would not match).
    eid = str(entity_id)

    # ── Fan out all 6 legs concurrently via asyncio.gather ───────────────────
    # WHY 6 legs (not 5): the B-2 fix requires a depth=1 graph fetch to merge
    # into the depth=2 result so depth-1 neighbors are never orphaned. The
    # prior implementation fetched this serially AFTER the 5-leg gather, adding
    # a full KG round-trip (~1-2 s) to the critical path. By including it as a
    # 6th concurrent leg the merge fetch overlaps with detail / brief / paths /
    # intelligence — total wall time is bounded by the slowest single leg.
    #
    # WHY return_exceptions=False: _bundle_fetch_json already swallows exceptions
    # and returns None, so no leg will ever raise into gather. Using False (not
    # True) avoids the isinstance(result, BaseException) checks below and keeps
    # the semantics clear: all results are dict | None.
    # WHY wait_for(timeout=20): the gather has no outer deadline. If AGE stalls on
    # a depth=2 Cypher query, all 6 legs complete except graph_t, and the connection
    # hangs open for the full httpx read timeout (30 s by default on the S9 client).
    # 20 s is generous: depth=1 SQL ≈ 500ms, depth=2 warm ≈ 2-4s, depth=2 cold ≈ 8s,
    # depth=3 cold ≈ 12s. Beyond 20 s something is truly stuck. GraphColumn already
    # shows a per-depth timeout UI (GRAPH_TIMEOUT_MS_BY_DEPTH) so a 504 from S9 maps
    # gracefully to the "Graph timed out" empty state. (PLAN-0099 W4 investigation)
    _gather = asyncio.gather(
        _bundle_fetch_json(
            clients.knowledge_graph,
            f"/api/v1/entities/{eid}",
            headers=headers,
            leg="detail",
        ),
        _bundle_fetch_json(
            clients.rag_chat,
            f"/api/v1/briefings/instrument/{eid}",
            headers=headers,
            leg="brief",
        ),
        # graph_d2 — S7 raw. We transform below so the shape matches the
        # frontend cache slot (EntityGraph {entity_id, nodes, edges}).
        _bundle_fetch_json(
            clients.knowledge_graph,
            f"/api/v1/entities/{eid}/graph",
            headers=headers,
            params={
                "limit": _BUNDLE_GRAPH_LIMIT,
                "depth": _BUNDLE_GRAPH_DEPTH,
                "min_confidence": 0.0,
                "confidence_breakdown": "true",
            },
            leg="graph_d2",
        ),
        # graph_d1 — depth=1 SQL path (no AGE). Fetched concurrently so the
        # B-2 merge does not add serial latency. No `depth` param → S7 default.
        # WHY needed: at depth=2 S7 fills the entity LIMIT with depth-2 nodes;
        # depth-1 neighbors may be absent from `entities`, which causes the
        # orphan-edge filter to drop every edge → 0 edges. Merging depth=1 first
        # guarantees center↔neighbor edges survive the orphan filter.
        _bundle_fetch_json(
            clients.knowledge_graph,
            f"/api/v1/entities/{eid}/graph",
            headers=headers,
            params={
                "limit": _BUNDLE_GRAPH_LIMIT,
                "min_confidence": 0.0,
                "confidence_breakdown": "true",
                # No `depth` param → S7 defaults to depth=1 SQL path.
            },
            leg="graph_d2_depth1_merge",
        ),
        _bundle_fetch_json(
            clients.knowledge_graph,
            f"/api/v1/entities/{eid}/paths",
            headers=headers,
            params={
                "limit": _BUNDLE_PATHS_LIMIT,
                "min_score": _BUNDLE_PATHS_MIN_SCORE,
                "min_hops": _BUNDLE_PATHS_MIN_HOPS,
                "max_hops": _BUNDLE_PATHS_MAX_HOPS,
            },
            leg="paths",
        ),
        _bundle_fetch_json(
            clients.knowledge_graph,
            f"/api/v1/entities/{eid}/intelligence",
            headers=headers,
            leg="intelligence_summary",
        ),
        return_exceptions=False,
    )
    try:
        detail_t, brief_t, graph_t, graph_d1_t, paths_t, intel_t = await asyncio.wait_for(_gather, timeout=20.0)
    except TimeoutError:
        logger.warning("intelligence_bundle_outer_timeout", entity_id=eid)
        raise HTTPException(status_code=504, detail="Intelligence bundle timeout")  # noqa: B904

    # WHY transform graph after fetch: _transform_graph_response converts the
    # S7 {center, relations, entities} payload to the frontend's EntityGraph
    # {entity_id, nodes, edges}. Same transform the /graph proxy applies, so
    # the hydrated cache slot is byte-for-byte what a direct call would yield.
    #
    # B-2 fix: graph_d1_t (fetched concurrently above) is merged into the
    # depth=2 result here in-memory — zero extra network latency.
    graph_d2: dict[str, Any] | None = None
    if graph_t is not None:
        try:
            graph_d2 = _transform_graph_response(graph_t)
            # Merge depth=1 result (already fetched concurrently) into depth=2.
            if graph_d1_t is not None:
                t1 = _transform_graph_response(graph_d1_t)
                existing_node_ids = {n["id"] for n in graph_d2["nodes"]}
                existing_edge_ids = {e["id"] for e in graph_d2["edges"]}
                for n in t1["nodes"]:
                    if n["id"] not in existing_node_ids:
                        graph_d2["nodes"].append(n)
                        existing_node_ids.add(n["id"])
                for e in t1["edges"]:
                    if e["id"] not in existing_edge_ids:
                        graph_d2["edges"].append(e)
                        existing_edge_ids.add(e["id"])
                # Re-apply orphan filter after merge (new edges may validate
                # previously-orphan nodes; new nodes may validate orphan edges).
                node_id_set2 = {n["id"] for n in graph_d2["nodes"]}
                graph_d2["edges"] = [
                    e for e in graph_d2["edges"] if e["source"] in node_id_set2 and e["target"] in node_id_set2
                ]
                edge_eps2: set[str] = set()
                for e in graph_d2["edges"]:
                    edge_eps2.add(e["source"])
                    edge_eps2.add(e["target"])
                graph_d2["nodes"] = [n for n in graph_d2["nodes"] if n["id"] == eid or n["id"] in edge_eps2]
        except Exception:
            # Defensive: malformed S7 payload should not poison the bundle.
            logger.warning("entity_intelligence_bundle_graph_transform_failed", entity_id=eid)
            graph_d2 = None

    bundle: dict[str, Any] = {
        "detail": detail_t,
        "brief": brief_t,
        "graph_d2": graph_d2,
        "paths": paths_t,
        "intelligence_summary": intel_t,
    }

    # ── Cache store (5 min TTL) ──────────────────────────────────────────────
    # Serialise the assembled bundle once and cache as raw JSON bytes so warm
    # hits bypass both the 6-leg fan-out AND the graph transform CPU work.
    if valkey is not None:
        try:
            await valkey.set(cache_key, json.dumps(bundle), ex=300)
        except Exception:
            # Fail-open: caching is best-effort.
            logger.warning("bundle_cache_write_failed", entity_id=str(entity_id))

    return Response(
        content=json.dumps(bundle).encode(),
        status_code=200,
        media_type="application/json",
    )


# ── Prediction Markets (PRD-0019 Wave C-1) ────────────────────────────────────


@router.get(
    "/signals/prediction-markets",
    response_model=PredictionMarketsListResponse,
    response_model_exclude_none=True,
)
async def list_prediction_markets(
    request: Request,
    # PLAN-0049 T-C-3-03 — declared explicitly (rather than left as a generic
    # ``request.query_params`` pass-through) so the OpenAPI spec advertises
    # it to frontend type-generators.  The ``description`` lists the
    # non-binding suggested values; backend does case-insensitive equality
    # so any future Polymarket tag works without a code change.
    category: str | None = Query(
        default=None,
        max_length=50,
        description=(
            "Optional category filter. Suggested values: macro, politics, "
            "sports, crypto, general (non-binding — backend does case-"
            "insensitive equality, never validates the enum)."
        ),
    ),
) -> Any:
    """Proxy GET /api/v1/prediction-markets → S3 Market Data.

    Requires authentication. Forwards query params (status, limit, offset,
    category) and auth headers derived from the JWT payload.

    WHY response_model=PredictionMarketsListResponse: S3 returns
    {items: [...], total, limit, offset}. PredictionMarketsListResponse
    mirrors that shape exactly (extra=allow passes any new fields through).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    # F-QAC-09 fix: forward all query params verbatim. The explicit
    # ``category`` parameter declaration above exists purely so OpenAPI
    # documents it for type-generators; FastAPI parses ``category`` from
    # the same query string that backs ``request.query_params``, so the
    # values cannot disagree.
    forwarded: dict[str, Any] = dict(request.query_params)
    resp = await clients.market_data.get(
        "/api/v1/prediction-markets",
        params=forwarded,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/signals/prediction-markets/categories")
async def get_prediction_market_categories(request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets/categories → S3 Market Data.

    PLAN-0053 T-C-3-05. Registered BEFORE the ``/{market_id}`` route so the
    literal "categories" path matches first (FastAPI evaluates routes in
    registration order; if /{market_id} were declared first it would shadow
    this and treat "categories" as a market_id).

    Returns ``[{category, count}, ...]`` and a top-level ``total`` for all
    currently-open markets.  Used by PredictionMarketsWidget to render
    filter pill counts and the empty-state explainer.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/prediction-markets/categories",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/signals/prediction-markets/{market_id}",
    response_model=PredictionMarket,
    response_model_exclude_none=True,
)
async def get_prediction_market(
    market_id: str = Path(..., min_length=1, max_length=80, pattern=r"^[\w\-\.]+$"),
    *,
    request: Request,
) -> Any:
    """Proxy GET /api/v1/prediction-markets/{id} → S3 Market Data.

    Requires authentication. S3 returns 404 if the market_id is unknown.

    WHY response_model=PredictionMarket: S3 PredictionMarketDetailResponse
    is a superset of PredictionMarketSummaryResponse (adds description +
    created_at). PredictionMarket uses extra=allow so those extra fields
    pass through without a validation error.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/prediction-markets/{market_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/signals/prediction-markets/{market_id}/history")
async def get_prediction_market_history(
    market_id: str = Path(..., min_length=1, max_length=80, pattern=r"^[\w\-\.]+$"),
    *,
    request: Request,
) -> Any:
    """Proxy GET /api/v1/prediction-markets/{id}/history → S3 Market Data.

    Requires authentication. Forwards from/to/limit query params.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/prediction-markets/{market_id}/history",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Entity Sentiment Timeseries (PLAN-0091 Wave A-2 / E-2, T-A-2-02) ─────────


@router.get("/entities/{entity_id}/sentiment-timeseries")
async def get_entity_sentiment_timeseries(
    entity_id: UUID,
    request: Request,
    days: int = Query(default=90, ge=1, le=365),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/sentiment-timeseries → S6 NLP Pipeline.

    Returns daily sentiment and relevance aggregates for the entity over the
    requested window. The S6 route (PLAN-0091 Wave E-1) is the authoritative
    source; this gateway endpoint simply proxies and forwards auth headers.
    Returns 401 if unauthenticated, 502 if S6 is unavailable.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        f"/api/v1/entities/{entity_id}/sentiment-timeseries",
        params={"days": days},
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
