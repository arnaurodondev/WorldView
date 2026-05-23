"""Content, news, entity, and document routes for the API Gateway.

Handles /v1/news/*, /v1/entities/similar, /v1/entities/{id},
/v1/entities/{id}/articles, /v1/documents/* — proxies to S5/S6 NLP Pipeline,
S7 Knowledge Graph, S4 Content Ingestion, and S5 Content Store.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients, _document_headers, _system_headers
from api_gateway.schemas import NewsTopResponse
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


# ── Similar entities (PRD-0017 Wave C-1) ─────────────────────────────────────


@router.post("/entities/similar")
async def find_similar_entities(request: Request) -> Any:
    """Proxy POST /api/v1/entities/similar → S7 Knowledge Graph.

    Public endpoint — issues a system JWT for backend authentication.
    S7 returns 404 (entity not found), 422 (no embedding), 503 (pgvector unavailable).
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/entities/similar",
        content=body,
        headers={"Content-Type": "application/json", **_system_headers(request)},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Entity detail (PRD-0073 Wave D-1) ────────────────────────────────────────


@router.get("/entities/{entity_id}")
async def get_entity_detail(entity_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id} → S7 Knowledge Graph.

    Returns enrichment fields (description, metadata, data_completeness, enriched_at)
    populated by Worker 13J (PRD-0073).  Returns 404 when the entity does not exist
    or enrichment has not yet run.

    Requires authentication — enrichment data is behind the user JWT boundary.

    F-S04 (PLAN-0073 cleanup): ``entity_id`` is typed as ``UUID`` so FastAPI validates
    the path param at the gateway boundary before we issue any downstream request.
    This blocks path-traversal probes (e.g. ``../../admin``) and arbitrary string
    payloads from reaching S7 — defence-in-depth even though S7 also validates.

    WHY registered before /entities/{entity_id}/graph and /entities/{entity_id}/contradictions:
    The bare /{entity_id} path will NOT shadow the sub-resource paths because those have
    an extra path segment.  FastAPI matches the most specific (longest) path first when
    both are registered; `/entities/UUID/graph` always wins over `/entities/UUID`.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /entities/{entity_id}/articles MUST be registered before /entities/{entity_id}/graph
# to avoid ambiguity with other entity sub-resource paths. FastAPI matches in registration order.
@router.get("/entities/{entity_id}/articles")
async def get_entity_articles(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/articles → S6 NLP Pipeline.

    Canonical alias for /v1/news/entity/{entity_id} — same S6 endpoint.

    WHY this alias exists: the frontend Instrument page components (InstrumentTopNews,
    FundamentalsTopNews, IntelligenceTab) reference /v1/entities/{id}/articles as the
    canonical path for entity-scoped news.  Maintaining both /v1/news/entity/{id} and
    this path ensures backward compat while giving instrument-page consumers a natural
    resource-oriented URL shape.

    Requires authentication. Forwards query parameters (start_date, end_date,
    order_by, limit, offset) unchanged.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        f"/api/v1/entities/{entity_id}/articles",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── News (PRD-0028 Wave S9-1) ────────────────────────────────────────────────


@router.get("/news/top", response_model=NewsTopResponse, response_model_exclude_none=True)
async def get_news_top(request: Request) -> Any:
    """Proxy GET /api/v1/news/top → S6 NLP Pipeline with cluster_size enrichment.

    No authentication required — public endpoint.  Issues a system JWT so S6's
    InternalJWTMiddleware accepts the request.
    Forwards query parameters (hours, limit, offset, min_display_score, routing_tier) unchanged.

    SA-4 enrichment: after fetching from S6, calls content-store
    POST /api/v1/documents/cluster-sizes in a single batch to add cluster_size
    to each article.  cluster_size=1 means no near-duplicates detected;
    cluster_size=N means N-1 near-duplicate siblings exist.  Enrichment
    failure is non-fatal (cluster_size defaults to null in the response).

    PERF-001 (2026-05-11): this endpoint is on the dashboard critical path (every
    page load + every 5-minute refetch).  Two sequential downstream hops (S6 SQL
    with 3-CTE window pivot + content-store cluster enrichment) caused 3-5 s
    cold latency.  Added a 2-minute Valkey cache keyed on all query params so
    only the first request per 2-minute window pays the full cost; all others
    return in <10 ms.  TTL=120 s is short enough to surface breaking news within
    2 minutes and long enough to amortise the cost across all dashboard tabs.
    Cache is skipped gracefully when Valkey is unavailable (fail-open pattern).
    """
    # ── Valkey cache check ────────────────────────────────────────────────────
    # WHY cache at S9 (not S6): S9 owns the composed response (S6 body +
    # cluster-size enrichment). Caching at S6 would not capture the enrichment.
    # WHY 120 s TTL: news relevance changes slowly within a 2-minute window.
    # This collapses repeated dashboard loads/tab switches to a single S6 call.
    _news_top_cache_ttl = 120
    valkey = getattr(request.app.state, "valkey", None)
    qp = dict(request.query_params)
    # Cache key: sorted params so ?limit=20&hours=24 == ?hours=24&limit=20.
    _cache_key = "news:top:v1:" + ":".join(f"{k}={v}" for k, v in sorted(qp.items()))

    if valkey is not None:
        try:
            cached = await valkey.get(_cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return Response(content=raw, status_code=200, media_type="application/json")
        except Exception as _e:
            logger.warning("news_top_cache_read_failed", error=str(_e))

    clients = _clients(request)
    sys_headers = _system_headers(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/news/top",
        params=qp,
        headers=sys_headers,
    )
    if resp.status_code != 200:
        # Pass through non-200 responses unchanged (e.g. 429, 503 from S6).
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    # ── Cluster-size enrichment ───────────────────────────────────────────────
    # Parse the S6 response, collect article_ids (= content-store doc_ids),
    # and batch-fetch cluster sizes.  Merge back into each article dict.
    # WHY best-effort (try/except): enrichment is cosmetic — a content-store
    # outage should never break the news feed.
    try:
        body = json.loads(resp.content)
        articles = body.get("articles", [])
        doc_ids = [a["article_id"] for a in articles if a.get("article_id")]
        cluster_size_map: dict[str, int] = {}
        # WHY cluster_id added (P2-F): the "+N sim" chip click opens a drawer
        # that fetches GET /v1/news/cluster/{cluster_id}.  The frontend needs
        # cluster_id on the article to make that call.  cluster_id is None when
        # cluster_size=1 (no near-duplicates) — content-store contract.
        cluster_id_map: dict[str, str | None] = {}
        if doc_ids:
            cs_resp = await clients.content_store.post(
                "/api/v1/documents/cluster-sizes",
                json={"doc_ids": doc_ids},
                headers=sys_headers,
            )
            if cs_resp.status_code == 200:
                cs_body = json.loads(cs_resp.content)
                for entry in cs_body.get("entries", []):
                    aid_str = str(entry["doc_id"])
                    cluster_size_map[aid_str] = entry["cluster_size"]
                    # cluster_id present since P2-F; None for isolated articles.
                    cluster_id_map[aid_str] = entry.get("cluster_id")
        for article in articles:
            aid = str(article.get("article_id", ""))
            # cluster_size=1 means "alone in cluster" (no near-duplicates)
            article["cluster_size"] = cluster_size_map.get(aid, 1)
            article["cluster_id"] = cluster_id_map.get(aid)
        body["articles"] = articles
        final_body = json.dumps(body)

        # ── Write enriched response to Valkey cache ───────────────────────────
        if valkey is not None:
            try:
                await valkey.set(_cache_key, final_body, ex=_news_top_cache_ttl)
            except Exception as _e:
                logger.warning("news_top_cache_write_failed", error=str(_e))

        return Response(
            content=final_body,
            status_code=200,
            media_type="application/json",
        )
    except Exception:
        # Enrichment failed — return the original S6 response unchanged.
        logger.warning("news_top_cluster_size_enrichment_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/news/cluster/{cluster_id}")
async def get_news_cluster(cluster_id: str, request: Request) -> Any:
    """Proxy GET /v1/news/cluster/{cluster_id} → content-store cluster articles.

    No authentication required — same public-read posture as /v1/news/top.
    Issues a system JWT so content-store's InternalJWTMiddleware accepts the
    request.

    WHY this endpoint (P2-F): the frontend "+N sim" chip click opens a Sheet
    (side panel) showing all articles in the same near-duplicate cluster.
    The frontend passes the cluster_id it received from the enriched news/top
    response to fetch the cluster member list.

    Returns the content-store response unchanged (200 with articles list, or
    404 if the cluster_id is not found).
    """
    clients = _clients(request)
    sys_headers = _system_headers(request)
    resp = await clients.content_store.get(
        f"/api/v1/documents/cluster/{cluster_id}/articles",
        headers=sys_headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/news/entity/{entity_id}")
async def get_news_entity(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/articles → S6 NLP Pipeline (PRD-0026 §6.7 Flow D).

    Requires authentication. entity_id is a path parameter (not a query param).
    Forwards query parameters (start_date, end_date, order_by, limit, offset) unchanged.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    # entity_id is part of the path, not a query param (BP-026 guard).
    resp = await clients.nlp_pipeline.get(
        f"/api/v1/entities/{entity_id}/articles",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Article Impact History (PLAN-0091 Wave A-2, T-A-2-01) ───────────────────


@router.get("/articles/{article_id}/impact-history")
async def get_article_impact_history(article_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/articles/{article_id}/impact-windows → S6 NLP Pipeline.

    Returns the 4-window (t0/t1/t2/t5) price-impact history for the article.
    Auth required — the S6 endpoint enforces tenant scoping via X-Internal-JWT.
    """
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        f"/api/v1/articles/{article_id}/impact-windows",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Tenant Document Management (PLAN-0086 Wave E-2) ───────────────────────────
#
# These routes proxy tenant document upload/list/get/delete to S4
# (content-ingestion service).  All four require authentication — documents are
# tenant-scoped and must never be accessible to unauthenticated callers.
#
# Header forwarding strategy:
# - X-Internal-JWT: issued by _auth_headers(); carries user_id, tenant_id, role.
# - X-Tenant-ID / X-User-ID: forwarded explicitly for S4's header-based dep
#   extractors (tenant_id_dep / user_id_dep in documents.py).
#
# The upload route uses httpx multipart forwarding: the file bytes are read from
# the incoming request and re-sent as a multipart/form-data body to S4.  httpx
# handles the boundary header automatically when ``files=`` is used.


@router.post("/documents/upload", status_code=202)
async def upload_document_proxy(request: Request) -> Response:
    """Proxy POST /v1/documents/upload → S4 POST /api/v1/documents/upload.

    PLAN-0086 Wave E-2: Tenant document upload.

    The multipart file is forwarded by reading the raw body and passing it
    through with the original Content-Type header (which includes the boundary
    parameter).  This avoids parsing and re-encoding the multipart data at the
    gateway layer.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Read raw multipart body — pass it through verbatim to S4.
    # The Content-Type header (multipart/form-data; boundary=...) MUST be
    # forwarded unchanged so S4 can decode the boundary.
    body = await request.body()
    content_type = request.headers.get("Content-Type", "")
    headers = _document_headers(request)

    clients = _clients(request)
    resp = await clients.content_ingestion.post(
        "/api/v1/documents/upload",
        content=body,
        headers={"Content-Type": content_type, **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/documents/{doc_id}")
async def get_document_proxy(doc_id: str, request: Request) -> Response:
    """Proxy GET /v1/documents/{doc_id} → S4 GET /api/v1/documents/{doc_id}.

    PLAN-0086 Wave E-2: Fetch a single tenant document status.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    resp = await clients.content_ingestion.get(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/documents")
async def list_documents_proxy(request: Request) -> Response:
    """Proxy GET /v1/documents → S4 GET /api/v1/documents.

    PLAN-0086 Wave E-2: Paginated list of tenant documents.

    Forwards all query params (status, limit, cursor) to S4 unchanged.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    # Forward all query params (status filter, limit, cursor) to S4 as-is.
    resp = await clients.content_ingestion.get(
        "/api/v1/documents",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/documents/{doc_id}", status_code=200)
async def delete_document_proxy(doc_id: str, request: Request) -> Response:
    """Proxy DELETE /v1/documents/{doc_id} → S4 DELETE /api/v1/documents/{doc_id}.

    PLAN-0086 Wave E-2: Soft-delete a tenant document.

    Returns 200 with body (BP-064: never 204) — S4 returns the same.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    resp = await clients.content_ingestion.delete(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
