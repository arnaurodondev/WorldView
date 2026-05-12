"""Intelligence, knowledge graph, narratives, and prediction market routes.

Handles /v1/entities/{id}/graph, /v1/entities/{id}/intelligence,
/v1/entities/{id}/narratives, /v1/entities/{id}/paths,
/v1/entities/{id}/contradictions, /v1/search/relations, /v1/claims/search,
/v1/signals/prediction-markets/* — proxies to S7 Knowledge Graph and S3 Market Data.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients
from api_gateway.schemas import PredictionMarket, PredictionMarketsListResponse
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
            }
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
            }
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
            }
        )

    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(
    entity_id: UUID,  # WHY UUID not str: enforces 422 on malformed values before any downstream call
    request: Request,
    limit: int = Query(default=40, ge=1, le=200),
    depth: int = Query(default=1, ge=1, le=3),
    confidence_breakdown: bool = Query(default=False),
    focus_node: str | None = Query(default=None),
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

    # Build params: forward known S7 params explicitly so the intent of each
    # forwarded param is clear and log noise from unknown params is avoided.
    raw_params = dict(request.query_params)
    s7_params: dict[str, str] = {"limit": str(limit)}
    if "min_confidence" in raw_params:
        s7_params["min_confidence"] = raw_params["min_confidence"]
    if "semantic_mode" in raw_params:
        s7_params["semantic_mode"] = raw_params["semantic_mode"]
    # ISSUE-5 (2026-05-10): forward depth to S7 which supports AGE Cypher multi-hop
    # traversal. depth=1 is S7's default (SQL query) so only send when >1 to avoid
    # a redundant param on the common case. depth>1 requires KNOWLEDGE_GRAPH_CYPHER_ENABLED.
    if depth > 1:
        s7_params["depth"] = str(depth)
    # PLAN-0074 Wave G: forward confidence_breakdown and focus_node (Wave D additions).
    if confidence_breakdown:
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
    import json as _json

    raw: dict[str, Any] = resp.json()
    transformed = _transform_graph_response(raw)
    return Response(
        content=_json.dumps(transformed).encode(),
        status_code=resp.status_code,
        media_type="application/json",
    )


@router.get("/entities/{entity_id}/contradictions")
async def get_entity_contradictions(entity_id: str, request: Request) -> Any:
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
    focus_node: str | None = Query(default=None),
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
    cache_key = f"intel:{tenant_id}:{entity_id}"
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
async def get_prediction_market(market_id: str, request: Request) -> Any:
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
async def get_prediction_market_history(market_id: str, request: Request) -> Any:
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
