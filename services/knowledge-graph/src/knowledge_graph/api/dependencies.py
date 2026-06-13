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


# ── Entity alias repo (name resolution) ──────────────────────────────────────


def get_entity_alias_repo(session: ReadOnlyDbSessionDep) -> object:
    """Build EntityAliasRepository for read-only name resolution queries."""
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
        EntityAliasRepository,
    )

    return EntityAliasRepository(session)


EntityAliasRepoDep = Annotated[object, Depends(get_entity_alias_repo)]


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
    """Build GetEntityDetailUseCase bound to the current read-only session.

    PLAN-0099: alias / relation / summary repos wired so the detail endpoint
    can return aliases, top relations and the relation count (node-click panel).
    """
    from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
        EntityAliasRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
        RelationSummaryRepository,
    )

    return GetEntityDetailUseCase(
        CanonicalEntityRepository(session),
        alias_repo=EntityAliasRepository(session),
        relation_repo=RelationRepository(session),
        summary_repo=RelationSummaryRepository(session),
    )


GetEntityDetailUseCaseDep = Annotated[GetEntityDetailUseCase, Depends(get_entity_detail_uc)]


# ── Relation detail use case (PLAN-0099 edge detail) ──────────────────────────


def get_relation_detail_uc() -> GetRelationDetailUseCase_:
    """Depends() factory for GetRelationDetailUseCase (R25 compliance).

    The use case is stateless — repos are passed per-call from the
    EntityGraphReposDep bundle by the route handler.
    """
    from knowledge_graph.application.use_cases.get_relation_detail import GetRelationDetailUseCase

    return GetRelationDetailUseCase()


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


# ── Pairwise pathfinding (PLAN-0112 W4) ───────────────────────────────────────
# R25: All infrastructure wiring happens here — the router imports only the Dep.
# R27 exception: AGE traversal needs LOAD 'age' → the engine holds the WRITE
# session factory (same documented precedent as CypherPathUseCase).  Entity
# existence + the WeirdnessScorer prefetch run on their own sessions opened by
# the factory; the use case itself owns no session.


def get_find_paths_between_uc(
    session: ReadOnlyDbSessionDep,
    request: Request,
) -> FindPathsBetweenUseCase_:
    """Build FindPathsBetweenUseCase for the on-demand pairwise endpoint.

    Wires:
      • ``AgeGraphPathEngine`` over ``app.state.write_factory`` (R27 exception —
        AGE ``LOAD 'age'`` requires a write session, like the existing engine
        callers).
      • ``entity_exists`` over the read-only request session (R27).
      • ``build_scorer`` — an async factory that pre-fetches the SAME global
        lookups the ``PathInsightWorker`` uses (degree map, graph stats,
        definition embeddings, first-seen) for the entities/relations on the
        candidate paths and returns a configured pure ``WeirdnessScorer``.  This
        keeps pairwise scoring byte-for-byte identical to batch discovery.
    """
    from datetime import timedelta

    from knowledge_graph.application.ports.node_degree_repository import GraphStats
    from knowledge_graph.application.services.weirdness_scorer import WeirdnessScorer
    from knowledge_graph.application.use_cases.find_paths_between import FindPathsBetweenUseCase
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
        NodeDegreeRepository,
    )
    from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

    settings: Settings = request.app.state.settings
    write_factory = request.app.state.write_factory

    engine = AgeGraphPathEngine(write_factory)

    canonical_repo = CanonicalEntityRepository(session)

    async def _entity_exists(entity_id: UUID) -> bool:
        return await canonical_repo.exists(entity_id)

    async def _build_scorer(raw_paths: object) -> WeirdnessScorer:
        # Collect endpoint ids + rel ids exactly as the worker does.
        from uuid import UUID as _UUID

        endpoint_ids: set[UUID] = set()
        rel_ids: set[UUID] = set()
        for p in raw_paths:  # type: ignore[attr-defined]
            for nid in p.node_ids:
                try:
                    endpoint_ids.add(_UUID(str(nid)))
                except (ValueError, AttributeError):
                    continue
            rel_ids.update(p.rel_ids)

        # Reuse the worker's static prefetch helpers (single source of truth for
        # the degree / embedding / first-seen SQL).  Runs on the WRITE factory —
        # same connection class the engine uses — so the GUC + AGE search_path are
        # available if needed.
        async with write_factory() as scoring_session:
            degree_repo = NodeDegreeRepository(scoring_session)
            degree_map = await degree_repo.get_degree_map()
            stats = await degree_repo.get_graph_stats() or GraphStats(0, 0, 0)
            embeddings = await PathInsightWorker._fetch_definition_embeddings(scoring_session, endpoint_ids)
            first_seen = await PathInsightWorker._fetch_first_seen(scoring_session, rel_ids)

        return WeirdnessScorer(
            degree_of=lambda eid: degree_map.get(eid, (1, 1))[0],
            meaningful_degree_of=lambda eid: degree_map.get(eid, (1, 1))[1],
            graph_stats=stats,
            embedding_of=lambda eid: embeddings.get(eid),
            first_seen_of=lambda rid: first_seen.get(rid),
            novelty_window=timedelta(days=settings.novelty_window_days),
            w_unexpectedness=settings.weirdness_w_unexpectedness,
            w_semantic=settings.weirdness_w_semantic,
            w_novelty=settings.weirdness_w_novelty,
            unexpectedness_mode=settings.weirdness_unexpectedness_mode,
        )

    return FindPathsBetweenUseCase(
        path_engine=engine,
        entity_exists=_entity_exists,
        build_scorer=_build_scorer,  # type: ignore[arg-type]
        max_hops_cap=settings.path_max_hops,
    )


# Import the concrete type for the Annotated alias — deferred to avoid a
# circular import at module load time (dependencies ← use_cases ← schemas).
from knowledge_graph.application.use_cases.find_paths_between import (  # noqa: E402
    FindPathsBetweenUseCase as FindPathsBetweenUseCase_,
)
from knowledge_graph.application.use_cases.get_entity_paths import (  # noqa: E402
    GetEntityPathsUseCase as GetEntityPathsUseCase_,
)
from knowledge_graph.application.use_cases.get_relation_detail import (  # noqa: E402
    GetRelationDetailUseCase as GetRelationDetailUseCase_,
)

GetEntityPathsUseCaseDep = Annotated[GetEntityPathsUseCase_, Depends(get_entity_paths_uc)]
GetRelationDetailUseCaseDep = Annotated[GetRelationDetailUseCase_, Depends(get_relation_detail_uc)]
FindPathsBetweenUseCaseDep = Annotated[FindPathsBetweenUseCase_, Depends(get_find_paths_between_uc)]
