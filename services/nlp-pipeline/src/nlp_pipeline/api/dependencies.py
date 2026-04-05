"""FastAPI dependency factories for the NLP Pipeline service."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nlp_pipeline.application.ports.repositories import SignalsQueryPort
from nlp_pipeline.application.use_cases.dlq_admin import DLQAdminUseCase
from nlp_pipeline.application.use_cases.query_entity_resolver import QueryEntityResolverUseCase
from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import CanonicalEntityRepository
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.dlq import DLQRepository
from nlp_pipeline.infrastructure.nlp_db.repositories.signals_query import SqlaSignalsQueryRepo

_VALID_ADMIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")


async def get_nlp_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the nlp_db session factory."""
    async with request.app.state.nlp_session_factory() as session:
        yield session


async def get_intelligence_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the intelligence_db session factory."""
    async with request.app.state.intelligence_session_factory() as session:
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
    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]


def get_signals_query_repo(session: Annotated[AsyncSession, Depends(get_nlp_session)]) -> SignalsQueryPort:
    """Build a SqlaSignalsQueryRepo for the current request session (R25-compliant)."""
    return SqlaSignalsQueryRepo(session)


SignalsQueryRepoDep = Annotated[SignalsQueryPort, Depends(get_signals_query_repo)]


def get_entity_resolver_use_case(
    request: Request,
    intel_session: Annotated[AsyncSession, Depends(get_intelligence_session)],
) -> QueryEntityResolverUseCase:
    """Build QueryEntityResolverUseCase for the current request.

    ML clients (ner_client, embedding_client) are not available in the API
    process — stages 4 and 5 are skipped gracefully.
    """
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
