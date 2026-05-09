"""FastAPI dependency injection for the Knowledge Graph service (S7)."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_graph.application.ports.claim_repository import ClaimRepositoryPort
from knowledge_graph.application.ports.event_repository import EventRepositoryPort
from knowledge_graph.application.ports.relation_summary_repository import RelationSummaryRepositoryPort
from knowledge_graph.application.ports.temporal_event_repository import TemporalEventRepositoryPort
from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase
from knowledge_graph.application.use_cases.dlq_admin import DLQAdminUseCase
from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase
from knowledge_graph.application.use_cases.get_entity_intelligence import GetEntityIntelligenceUseCase
from knowledge_graph.application.use_cases.list_narrative_versions import ListNarrativeVersionsUseCase

# ── Database sessions ─────────────────────────────────────────────────────────


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the intelligence_db session factory."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_readonly_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only AsyncSession from the read-replica session factory."""
    async with request.app.state.readonly_session_factory() as session:
        yield session


DbSessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadOnlyDbSessionDep = Annotated[AsyncSession, Depends(get_readonly_session)]


# ── Admin auth ────────────────────────────────────────────────────────────────


async def require_admin_token(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    """Validate the X-Admin-Token header."""
    expected: str = getattr(request.app.state, "admin_token", "")
    provided: str = x_admin_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


AdminAuthDep = Annotated[None, Depends(require_admin_token)]


# ── DLQ admin use case ────────────────────────────────────────────────────────


def get_dlq_use_case(session: Annotated[AsyncSession, Depends(get_session)]) -> DLQAdminUseCase:
    """Build a DLQAdminUseCase for the current request session."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.dlq import DLQRepository

    return DLQAdminUseCase(DLQRepository(session))


DLQUseCaseDep = Annotated[DLQAdminUseCase, Depends(get_dlq_use_case)]


# ── Entity graph use cases (read-only) ───────────────────────────────────────
# These factories encapsulate all infrastructure imports so that API route files
# never import from the infrastructure layer directly (R25 compliance).


class _EntityGraphUseCaseBundle:
    """Pre-bound bundle of repos for read-only entity graph queries."""

    def __init__(self, session: AsyncSession) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        self.entity_repo = CanonicalEntityRepository(session)
        self.relation_repo = RelationRepository(session)
        self.evidence_repo = RelationEvidenceRepository(session)
        self.summary_repo = RelationSummaryRepository(session)


def get_entity_graph_repos(session: ReadOnlyDbSessionDep) -> _EntityGraphUseCaseBundle:
    """Build read-only repos for graph neighbourhood queries."""
    return _EntityGraphUseCaseBundle(session)


EntityGraphReposDep = Annotated[_EntityGraphUseCaseBundle, Depends(get_entity_graph_repos)]


class _FindSimilarEntitiesBundle:
    """Pre-bound bundle of repos for the similar-entities ANN query."""

    def __init__(self, session: AsyncSession) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository

        self.entity_repo = CanonicalEntityRepository(session)
        self.embedding_repo = SqlalchemyEntityEmbeddingANNRepository(session)
        self.relation_repo = RelationRepository(session)


def get_find_similar_entities_repos(
    session: ReadOnlyDbSessionDep,
) -> _FindSimilarEntitiesBundle:
    """Build read-only repos for the similar-entities ANN query."""
    return _FindSimilarEntitiesBundle(session)


FindSimilarEntitiesReposDep = Annotated[_FindSimilarEntitiesBundle, Depends(get_find_similar_entities_repos)]


def get_entity_contradictions_repo(session: ReadOnlyDbSessionDep) -> object:
    """Build the ClaimRepository for entity contradiction queries."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.claim_repository import (
        ClaimRepository,
    )

    return ClaimRepository(session)


EntityContradictionsRepoDep = Annotated[object, Depends(get_entity_contradictions_repo)]


def get_temporal_event_repo(session: ReadOnlyDbSessionDep) -> TemporalEventRepositoryPort:
    """Build a TemporalEventRepository for the current read-only request session."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
        TemporalEventRepository,
    )

    return TemporalEventRepository(session)


TemporalEventRepoDep = Annotated[TemporalEventRepositoryPort, Depends(get_temporal_event_repo)]


# ── Cypher (AGE) endpoint bundle ─────────────────────────────────────────────
# Uses the write session (DbSessionDep) because AGE requires LOAD 'age' which
# is a session-level command. Read-replica connections may reject it.


class _CypherBundle:
    """Pre-bound bundle of repos + session for AGE Cypher endpoints (R25 compliance).

    Infrastructure imports are deferred to this factory so that route files
    never import from the infrastructure layer directly.
    """

    def __init__(self, session: AsyncSession, cypher_enabled: bool) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        self.session = session
        self.entity_repo = CanonicalEntityRepository(session)
        self.relation_repo = RelationRepository(session)
        self.temporal_event_repo = TemporalEventRepository(session)
        self.cypher_enabled = cypher_enabled


def get_cypher_bundle(session: DbSessionDep, request: Request) -> _CypherBundle:
    """Build a Cypher repo bundle for the current write-session request."""
    from knowledge_graph.config import Settings

    settings: Settings = request.app.state.settings
    return _CypherBundle(session=session, cypher_enabled=settings.cypher_enabled)


CypherBundleDep = Annotated[_CypherBundle, Depends(get_cypher_bundle)]


def get_cypher_neighborhood_uc() -> CypherNeighborhoodUseCase:
    """Depends() factory for CypherNeighborhoodUseCase (R25 / DEF-015 compliance).

    Routes must inject via CypherNeighborhoodUseCaseDep — never instantiate
    CypherNeighborhoodUseCase directly inside a route handler.
    """
    return CypherNeighborhoodUseCase()


CypherNeighborhoodUseCaseDep = Annotated[CypherNeighborhoodUseCase, Depends(get_cypher_neighborhood_uc)]


# ── R25-compliant repo factories for claims / events / search routes ──────────
# Infrastructure imports are deferred inside each factory so that route files
# never need to import from the infrastructure layer directly.


def get_claim_repo(session: ReadOnlyDbSessionDep) -> ClaimRepositoryPort:
    """Build ClaimRepository for read-only claims search queries."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.claim_repository import (
        ClaimRepository,
    )

    return ClaimRepository(session)  # type: ignore[return-value]


ClaimRepoDep = Annotated[ClaimRepositoryPort, Depends(get_claim_repo)]


def get_event_repo(session: ReadOnlyDbSessionDep) -> EventRepositoryPort:
    """Build EventRepository for read-only event search queries."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.event_repository import (
        EventRepository,
    )

    return EventRepository(session)  # type: ignore[return-value]


EventRepoDep = Annotated[EventRepositoryPort, Depends(get_event_repo)]


def get_relation_summary_repo(session: ReadOnlyDbSessionDep) -> RelationSummaryRepositoryPort:
    """Build RelationSummaryRepository for ANN relation search queries."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
        RelationSummaryRepository,
    )

    return RelationSummaryRepository(session)  # type: ignore[return-value]


RelationSummaryRepoDep = Annotated[RelationSummaryRepositoryPort, Depends(get_relation_summary_repo)]


# ── Entity detail (PRD-0073 §9.6) ────────────────────────────────────────────


def get_entity_detail_uc(
    session: ReadOnlyDbSessionDep,
) -> GetEntityDetailUseCase:
    """Build GetEntityDetailUseCase bound to the current read-only session."""
    from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )

    return GetEntityDetailUseCase(CanonicalEntityRepository(session))


GetEntityDetailUseCaseDep = Annotated[GetEntityDetailUseCase, Depends(get_entity_detail_uc)]


# ── Entity intelligence use case (PRD-0074 Wave D) ────────────────────────────


def get_entity_intelligence_uc(
    session: ReadOnlyDbSessionDep,
) -> GetEntityIntelligenceUseCase:
    """Build GetEntityIntelligenceUseCase bound to the current read-only session.

    All infrastructure imports are deferred inside this factory (R25).
    API routes annotate their parameters with GetEntityIntelligenceUseCaseDep.
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
        IntelligenceAggregatesRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository,
    )

    return GetEntityIntelligenceUseCase(
        entity_repo=CanonicalEntityRepository(session),
        narrative_repo=NarrativeRepository(session),
        aggregates_repo=IntelligenceAggregatesRepository(session),
    )


GetEntityIntelligenceUseCaseDep = Annotated[GetEntityIntelligenceUseCase, Depends(get_entity_intelligence_uc)]


# ── Narrative version history (PRD-0074 Wave C) ───────────────────────────────
# R25: NarrativeRepository wired here, not in the router.
# R27: list_versions is read-only → ReadOnlyDbSessionDep.


def get_list_narrative_versions_uc(
    session: ReadOnlyDbSessionDep,
) -> ListNarrativeVersionsUseCase:
    """Build ListNarrativeVersionsUseCase bound to the current read-only session.

    Wires NarrativeRepository here (dependencies.py) so the narratives.py
    router never imports from infrastructure/ (R25).
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository,
    )

    return ListNarrativeVersionsUseCase(NarrativeRepository(session))


ListNarrativeVersionsUseCaseDep = Annotated[ListNarrativeVersionsUseCase, Depends(get_list_narrative_versions_uc)]


# ── Path Insights (PLAN-0074 Wave E2) ─────────────────────────────────────────
# R25: All infrastructure wiring happens here — routers import only the Dep alias.
# R27: list_by_anchor is a read-only query → ReadOnlyDbSessionDep.
# The PathExplanationService write-session is provided via app.state (set at
# startup), NOT via a per-request session, so this factory is read-only.


def get_entity_paths_uc(
    session: ReadOnlyDbSessionDep,
    request: Request,
) -> GetEntityPathsUseCase_:
    """Build GetEntityPathsUseCase bound to the current read-only session.

    ``PathExplanationService`` is pulled from ``app.state`` so it can hold a
    write-session factory.  When the app state has no ``path_explanation_service``
    attribute (tests, dev) explanation generation is silently skipped.
    """
    from knowledge_graph.application.services.path_explanation_service import PathExplanationService
    from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
        PathInsightRepository,
    )

    repo = PathInsightRepository(session)

    # Optional — None when not wired at startup (tests, dev, no LLM configured).
    explanation_service: PathExplanationService | None = getattr(request.app.state, "path_explanation_service", None)

    # Entity existence check callable — R27: uses the same read-only session.
    # Injected into the use case so the router stays R25 compliant (no infra import).
    canonical_repo = CanonicalEntityRepository(session)

    async def _entity_exists(entity_id: UUID) -> bool:
        entity = await canonical_repo.get_by_id(entity_id)
        return entity is not None

    return GetEntityPathsUseCase(
        path_insight_repo=repo,
        explanation_service=explanation_service,
        entity_exists_fn=_entity_exists,
    )


# Import the concrete type for the Annotated alias — deferred to avoid a
# circular import at module load time (dependencies ← use_cases ← schemas).
from knowledge_graph.application.use_cases.get_entity_paths import (  # noqa: E402
    GetEntityPathsUseCase as GetEntityPathsUseCase_,
)

GetEntityPathsUseCaseDep = Annotated[GetEntityPathsUseCase_, Depends(get_entity_paths_uc)]
