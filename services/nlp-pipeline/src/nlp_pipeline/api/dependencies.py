"""FastAPI dependency factories for the NLP Pipeline service."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nlp_pipeline.application.ports.repositories import NewsQueryPort, SignalsQueryPort
from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase
from nlp_pipeline.application.use_cases.enhanced_chunk_search import EnhancedChunkSearchUseCase
from nlp_pipeline.application.use_cases.query_entity_resolver import QueryEntityResolverUseCase

# PLAN-0053 platform-stability iter-1 F-PLATFORM-02: switched from importing
# the concrete EntityMentionRepository (infrastructure) to its Protocol port
# (application/ports). The Protocol is the type used in the Annotated[] alias
# below; the concrete class is only loaded inside the dependency function via
# a body-level import. This satisfies LAYER-API-NO-MODULE-LEVEL-INFRA without
# the runtime NameError that previously blocked the TYPE_CHECKING approach.
from nlp_pipeline.application.ports.entity_mention import EntityMentionRepositoryPort

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
    return EnhancedChunkSearchUseCase(
        chunk_ann_repo=ChunkANNRepository(nlp_session),
        source_metadata_repo=SQLAlchemyDocumentSourceMetadataRepository(nlp_session),
        canonical_entity_repo=CanonicalEntityRepository(intel_session),
        valkey=raw_valkey,
        embedding_client=None,
        chunk_text_store=chunk_text_store,
    )


ChunkSearchUseCaseDep = Annotated[EnhancedChunkSearchUseCase, Depends(get_chunk_search_use_case)]
