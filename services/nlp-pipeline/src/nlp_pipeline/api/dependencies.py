"""FastAPI dependency factories for the NLP Pipeline service."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

# PLAN-0053 platform-stability iter-1 F-PLATFORM-02: switched from importing
# the concrete EntityMentionRepository (infrastructure) to its Protocol port
# (application/ports). The Protocol is the type used in the Annotated[] alias
# below; the concrete class is only loaded inside the dependency function via
# a body-level import. This satisfies LAYER-API-NO-MODULE-LEVEL-INFRA without
# the runtime NameError that previously blocked the TYPE_CHECKING approach.
from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
from nlp_pipeline.application.ports.entity_mention import EntityMentionRepositoryPort
from nlp_pipeline.application.ports.repositories import (
    DocumentSourceMetadataRepository,
    NewsQueryPort,
    SignalsQueryPort,
)
from nlp_pipeline.application.ports.trending_entities import TrendingEntitiesQueryPort
from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase
from nlp_pipeline.application.use_cases.enhanced_chunk_search import EnhancedChunkSearchUseCase
from nlp_pipeline.application.use_cases.get_entity_sentiment_timeseries import GetEntitySentimentTimeseriesUseCase
from nlp_pipeline.application.use_cases.query_entity_resolver import QueryEntityResolverUseCase
from nlp_pipeline.application.use_cases.search_documents import SearchDocumentsUseCase

_VALID_ADMIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")


async def get_nlp_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a write-side AsyncSession from the nlp_db session factory."""
    async with request.app.state.nlp_session_factory() as session:
        yield session


async def get_read_nlp_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-replica AsyncSession from the nlp_db read factory (R27).

    Falls back to the write factory when no dedicated read URL is configured.
    Used by query routes (signals, news, chunk search) to avoid routing reads
    through the primary write connection pool.
    """
    # nlp_read_factory is set in lifespan and falls back to nlp_session_factory
    # when DATABASE_READ_URL is not configured (see app.py lifespan).
    factory = getattr(request.app.state, "nlp_read_factory", request.app.state.nlp_session_factory)
    async with factory() as session:
        yield session


async def get_intelligence_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a write-side AsyncSession from the intelligence_db session factory."""
    async with request.app.state.intelligence_session_factory() as session:
        yield session


async def get_read_intelligence_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-replica AsyncSession from the intelligence_db read factory (R27).

    Falls back to the write factory when no dedicated read URL is configured.
    Used by query routes (entity resolver, chunk search) that only read from
    the intelligence DB.
    """
    factory = getattr(request.app.state, "intel_read_factory", request.app.state.intelligence_session_factory)
    async with factory() as session:
        yield session


async def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    """Validate X-Admin-Token header against configured secret.

    Rejects missing/invalid tokens with 401. Constant-time comparison is
    performed via ``hmac.compare_digest`` to prevent timing attacks.
    """
    import hmac

    configured: str = getattr(request.app.state.settings, "admin_token", "")
    if not configured:
        raise HTTPException(status_code=503, detail="Admin token not configured")

    if x_admin_token is None or not _VALID_ADMIN_TOKEN_RE.match(x_admin_token):
        raise HTTPException(status_code=401, detail="Missing or malformed admin token")

    if not hmac.compare_digest(x_admin_token, configured):
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── Type aliases for FastAPI injection ────────────────────────────────────────

NlpDbSessionDep = Annotated[AsyncSession, Depends(get_nlp_session)]
IntelDbSessionDep = Annotated[AsyncSession, Depends(get_intelligence_session)]
AdminAuthDep = Annotated[None, Depends(require_admin_token)]


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_nlp_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository

    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]


def get_signals_query_repo(
    session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> SignalsQueryPort:
    """Build a SqlaSignalsQueryRepo backed by the read replica (R27 — query-only)."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.signals_query import SqlaSignalsQueryRepo

    return SqlaSignalsQueryRepo(session)


SignalsQueryRepoDep = Annotated[SignalsQueryPort, Depends(get_signals_query_repo)]


def get_news_query_repo(
    session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> NewsQueryPort:
    """Build a SqlaNewsQueryRepo backed by the read replica (R27 — query-only)."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import SqlaNewsQueryRepo

    return SqlaNewsQueryRepo(session)


NewsQueryRepoDep = Annotated[NewsQueryPort, Depends(get_news_query_repo)]


def get_entity_mention_repo(
    session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> EntityMentionRepositoryPort:
    """Build an EntityMentionRepository backed by the read replica (R27 — query-only).

    Used by GET /api/v1/entities/{entity_id}/articles in the entities router.
    The function-body import keeps the API layer free of module-level
    infrastructure references (LAYER-API-NO-MODULE-LEVEL-INFRA).
    """
    from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import EntityMentionRepository

    return EntityMentionRepository(session)


EntityMentionRepoDep = Annotated[EntityMentionRepositoryPort, Depends(get_entity_mention_repo)]


def get_trending_entities_repo(
    session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> TrendingEntitiesQueryPort:
    """Build a SqlaTrendingEntitiesQueryRepo backed by the read replica (R27 — query-only).

    Used by GET /api/v1/news/trending-entities (NEWS MOMENTUM, PLAN-0099 W4).
    The function-body import keeps the API layer free of module-level
    infrastructure references (LAYER-API-NO-MODULE-LEVEL-INFRA / R25).
    """
    from nlp_pipeline.infrastructure.nlp_db.repositories.trending_entities_query import (
        SqlaTrendingEntitiesQueryRepo,
    )

    return SqlaTrendingEntitiesQueryRepo(session)


TrendingEntitiesRepoDep = Annotated[TrendingEntitiesQueryPort, Depends(get_trending_entities_repo)]


def get_canonical_entity_repo(
    session: Annotated[AsyncSession, Depends(get_read_intelligence_session)],  # R27: read replica
) -> CanonicalEntityPort:
    """Build a CanonicalEntityRepository backed by the intelligence_db read replica (R27).

    Used by GET /api/v1/news/trending-entities to resolve entity_id → ticker/name
    (the cross-database join the SQL layer cannot do). Read-only here — only
    ``batch_get`` is exercised on this path.
    """
    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )

    return CanonicalEntityRepository(session)


CanonicalEntityRepoDep = Annotated[CanonicalEntityPort, Depends(get_canonical_entity_repo)]


def get_entity_resolver_use_case(
    request: Request,
    intel_session: Annotated[AsyncSession, Depends(get_read_intelligence_session)],  # R27: read replica
) -> QueryEntityResolverUseCase:
    """Build QueryEntityResolverUseCase for the current request.

    ML clients (ner_client, embedding_client) are not available in the API
    process — stages 4 and 5 are skipped gracefully.
    """
    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
        EntityAliasRepository,
    )

    valkey = getattr(request.app.state, "valkey", None)
    raw_valkey = valkey._redis if valkey is not None else None  # type: ignore[attr-defined]
    return QueryEntityResolverUseCase(
        alias_repo=EntityAliasRepository(intel_session),
        canonical_repo=CanonicalEntityRepository(intel_session),
        valkey=raw_valkey,
        ner_client=None,
        embedding_client=None,
        embedding_repo=None,
    )


EntityResolverDep = Annotated[QueryEntityResolverUseCase, Depends(get_entity_resolver_use_case)]


def get_chunk_search_use_case(
    request: Request,
    nlp_session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
    intel_session: Annotated[AsyncSession, Depends(get_read_intelligence_session)],  # R27: read replica
) -> EnhancedChunkSearchUseCase:
    """Build EnhancedChunkSearchUseCase for the current request.

    EmbeddingClient is not available in the API process — callers must supply
    ``query_embedding`` directly (pre-computed by S8 or passed through).
    ``chunk_text_store`` is injected from app.state when MinIO is configured.
    """
    valkey = getattr(request.app.state, "valkey", None)
    raw_valkey = valkey._redis if valkey is not None else None  # type: ignore[attr-defined]
    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository
    from nlp_pipeline.infrastructure.nlp_db.repositories.document_source_metadata import (
        SQLAlchemyDocumentSourceMetadataRepository,
    )

    chunk_text_store = getattr(request.app.state, "chunk_text_store", None)
    # PLAN-0063 W5-3: pull the hybrid lexical boost from settings so the
    # tuned value flows from env → Settings → use case. Falls back to the
    # spec default of 1.5 when the setting is absent (older configs).
    settings = getattr(request.app.state, "settings", None)
    lexical_boost = float(getattr(settings, "hybrid_lexical_boost", 1.5)) if settings is not None else 1.5
    # embedding_client is set on app.state at startup (app.py:179); pass it
    # through so query_text searches can embed the query without a pre-computed vector.
    embedding_client = getattr(request.app.state, "embedding_client", None)
    # BUG-3: raise the HNSW candidate pool so selective post-filters (source_type,
    # tenant, entity, date) keep real rows instead of degenerating to ~0.
    ef_search = int(getattr(settings, "chunk_ann_ef_search", 200)) if settings is not None else 200
    # BUG-3 finish: filter-first EXACT KNN when a selective filter is present —
    # ef_search alone cannot surface a ~2%-density source under a hard post-filter.
    exact_when_filtered = (
        bool(getattr(settings, "chunk_ann_exact_when_filtered", True)) if settings is not None else True
    )
    exact_max_rows = int(getattr(settings, "chunk_ann_exact_max_rows", 100_000)) if settings is not None else 100_000
    # S6 chunk-search latency fix: a single indexed source_type (partial HNSW
    # index idx_chunk_emb_hnsw_<src>, migration 0024) skips the O(bucket) exact
    # sort. Parse the comma-separated allow-list from settings; the accel ef is
    # slightly wider than the general ef so a date post-filter still yields top_k.
    _raw_indexed = (
        str(getattr(settings, "chunk_ann_indexed_source_types", "sec_edgar")) if settings is not None else "sec_edgar"
    )
    indexed_source_types = frozenset(s.strip() for s in _raw_indexed.split(",") if s.strip())
    accel_ef_search = int(getattr(settings, "chunk_ann_accel_ef_search", 400)) if settings is not None else 400

    def _make_chunk_repo(session: AsyncSession) -> ChunkANNRepository:
        """Build a ChunkANNRepository with the tuned knobs, bound to *session*.

        Factored out so BOTH the request-scoped repo (shared session, sequential
        fallback + result enrichment) and the per-leg parallel scopes below use
        IDENTICAL configuration — otherwise the two hybrid legs could diverge in
        ef_search / exact-filter behaviour.
        """
        return ChunkANNRepository(
            session,
            ef_search=ef_search,
            exact_when_filtered=exact_when_filtered,
            exact_max_rows=exact_max_rows,
            indexed_source_types=indexed_source_types,
            accel_ef_search=accel_ef_search,
        )

    # ── Per-leg session scope for the parallel hybrid path (R1 latency fix) ────
    # The hybrid search runs its ANN and lexical legs concurrently, and a single
    # SQLAlchemy AsyncSession is NOT safe for concurrent use. So each leg leases
    # its OWN read-replica session from nlp_read_factory via this async-CM
    # factory. Falls back to the write factory when no read URL is configured
    # (same rule as get_read_nlp_session). Disabled → sequential shared-session
    # path (chunk_search_scope stays wired but parallel_hybrid gates it).
    from contextlib import asynccontextmanager

    nlp_read_factory = getattr(request.app.state, "nlp_read_factory", request.app.state.nlp_session_factory)

    @asynccontextmanager
    async def _chunk_search_scope() -> AsyncGenerator[ChunkANNRepository, None]:
        async with nlp_read_factory() as leg_session:
            yield _make_chunk_repo(leg_session)

    parallel_hybrid = bool(getattr(settings, "chunk_search_parallel_hybrid", True)) if settings is not None else True
    embed_cache_ttl_s = int(getattr(settings, "chunk_embed_cache_ttl_s", 3600)) if settings is not None else 3600

    return EnhancedChunkSearchUseCase(
        chunk_ann_repo=_make_chunk_repo(nlp_session),
        source_metadata_repo=SQLAlchemyDocumentSourceMetadataRepository(nlp_session),
        canonical_entity_repo=CanonicalEntityRepository(intel_session),
        valkey=raw_valkey,
        embedding_client=embedding_client,
        chunk_text_store=chunk_text_store,
        lexical_boost=lexical_boost,
        chunk_search_scope=_chunk_search_scope,
        parallel_hybrid=parallel_hybrid,
        embed_cache_ttl_s=embed_cache_ttl_s,
    )


ChunkSearchUseCaseDep = Annotated[EnhancedChunkSearchUseCase, Depends(get_chunk_search_use_case)]


def get_search_documents_use_case(
    request: Request,
    nlp_session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> SearchDocumentsUseCase:
    """Build SearchDocumentsUseCase for the current request (PLAN-0064 W6 T-W6-3-01).

    Uses the read replica session per R27 (this is a query-only path).
    S5 (content-store) and S7 (knowledge-graph) base URLs come from settings
    so they are operator-configurable without a code change.

    The body-level imports (AsyncpgDocumentSearchRepository, _S5BatchClient,
    _S7BatchClient) keep the API layer free of module-level infrastructure
    references (LAYER-API-NO-MODULE-LEVEL-INFRA / R25).
    """
    # Body-level imports: infrastructure references must not appear at module
    # scope in api/ (R25 / LAYER-API-NO-MODULE-LEVEL-INFRA). Importing here
    # means the architecture test (tests/architecture/test_layer_invariants.py)
    # will not flag the dependency as a module-level cross-layer violation.
    from nlp_pipeline.application.use_cases.search_documents import _S5BatchClient, _S7BatchClient
    from nlp_pipeline.infrastructure.nlp_db.repositories.document_search import AsyncpgDocumentSearchRepository

    settings = request.app.state.settings
    # content_store_internal_url / knowledge_graph_internal_url are operator-configurable
    # (defaults point to Docker Compose service hostnames — see config.py).
    s5_base_url: str = settings.content_store_internal_url
    s7_base_url: str = settings.knowledge_graph_internal_url

    # Forward the X-Internal-JWT that S9 attached when proxying the request to S6.
    # S5 and S7 both run InternalJWTMiddleware, so they require this header on
    # every inbound call.  Reading from request.state (set by InternalJWTMiddleware
    # after successful validation) is more reliable than re-reading request.headers
    # through stacked BaseHTTPMiddleware wrappers in Starlette 0.37.x.
    jwt: str | None = getattr(request.state, "internal_jwt", None)

    # HIGH-1: force the GIN index for the FTS scan (planner mis-costs a Seq Scan).
    force_index_scan = bool(getattr(settings, "fts_force_index_scan", True))
    repo = AsyncpgDocumentSearchRepository(nlp_session, force_index_scan=force_index_scan)
    s5_client = _S5BatchClient(s5_base_url, jwt=jwt)
    s7_client = _S7BatchClient(s7_base_url, jwt=jwt)

    return SearchDocumentsUseCase(repo=repo, s5_client=s5_client, s7_client=s7_client)


SearchDocumentsUseCaseDep = Annotated[SearchDocumentsUseCase, Depends(get_search_documents_use_case)]


def get_sentiment_timeseries_repo(
    session: Annotated[AsyncSession, Depends(get_read_nlp_session)],  # R27: read replica
) -> DocumentSourceMetadataRepository:
    """Build SQLAlchemyDocumentSourceMetadataRepository backed by the read replica (R27)."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.document_source_metadata import (
        SQLAlchemyDocumentSourceMetadataRepository,
    )

    return SQLAlchemyDocumentSourceMetadataRepository(session)


SentimentTimeseriesRepoDep = Annotated[DocumentSourceMetadataRepository, Depends(get_sentiment_timeseries_repo)]


def get_entity_sentiment_timeseries_use_case(
    repo: Annotated[DocumentSourceMetadataRepository, Depends(get_sentiment_timeseries_repo)],
) -> GetEntitySentimentTimeseriesUseCase:
    """Build GetEntitySentimentTimeseriesUseCase for the current request.

    Uses the read replica session (R27) via get_sentiment_timeseries_repo.
    """
    return GetEntitySentimentTimeseriesUseCase(repo)


SentimentTimeseriesUseCaseDep = Annotated[
    GetEntitySentimentTimeseriesUseCase,
    Depends(get_entity_sentiment_timeseries_use_case),
]


async def require_internal_jwt(request: Request) -> None:
    """Belt-and-suspenders auth check on top of InternalJWTMiddleware.

    In production (skip_verification=False), InternalJWTMiddleware sets
    ``request.state.internal_jwt`` in its ``_post_validate`` hook after
    successful RS256 signature verification.  This dependency asserts that
    attribute is present, giving a second layer of protection if the middleware
    is ever misconfigured (e.g. removed from app.py without updating routes).

    In dev/E2E mode (skip_verification=True), the middleware decodes the token
    without signature verification and does NOT call ``_post_validate``, so
    ``internal_jwt`` is not set.  We detect this via the
    ``_internal_jwt_skip_verification`` app.state flag and allow the request
    through — the middleware has already validated the token shape.
    """
    skip = getattr(request.app.state, "_internal_jwt_skip_verification", False)
    if skip:
        return
    if getattr(request.state, "internal_jwt", None) is None:
        raise HTTPException(status_code=401, detail="X-Internal-JWT header required")


InternalJwtAuthDep = Annotated[None, Depends(require_internal_jwt)]
