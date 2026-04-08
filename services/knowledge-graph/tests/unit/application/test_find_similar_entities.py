"""Unit tests for FindSimilarEntitiesUseCase (PRD-0017 §6.5, Wave B-4).

Tests:
- test_similar_entities_final_score_with_boost
- test_similar_entities_final_score_cap
- test_similar_entities_no_boost_when_no_competes_with
- test_similar_entities_entity_not_found
- test_similar_entities_embedding_not_available
- test_similar_entities_empty_ann_results
- test_similar_entities_min_score_filter
- test_similar_entities_include_competitors_only
- test_similar_entities_top_k_limits_results
- test_similar_entities_sorted_by_final_score_desc
- test_find_competes_with_batch_empty_candidates
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: object) -> object:
    return asyncio.get_event_loop().run_until_complete(coro)  # type: ignore[arg-type]


def _make_entity_repo(
    entity: dict | None = None,
    *,
    detail_map: dict | None = None,
) -> AsyncMock:
    """Build a mock CanonicalEntityRepositoryPort.

    ``entity``: returned for the get() call (query entity lookup).
    ``detail_map``: maps entity_id (UUID) → dict returned by get_batch().
    """
    detail_map = detail_map or {}
    mock = AsyncMock()

    async def _get(eid: UUID) -> dict | None:
        return entity

    async def _get_batch(eids: list[UUID]) -> list[dict]:
        return [detail_map[eid] for eid in eids if eid in detail_map]

    mock.get = _get
    mock.get_batch = _get_batch
    return mock


def _make_embedding_repo(
    embedding: list[float] | None = None,
    ann_results: list | None = None,
) -> AsyncMock:
    mock = AsyncMock()
    mock.get_embedding = AsyncMock(return_value=embedding)
    mock.find_nearest = AsyncMock(return_value=ann_results or [])
    return mock


def _make_relation_repo(
    competes_map: dict | None = None,
) -> AsyncMock:
    mock = AsyncMock()
    mock.find_competes_with_batch = AsyncMock(return_value=competes_map or {})
    return mock


def _entity_dict(entity_id: UUID, name: str = "Test Corp", *, ticker: str | None = "TEST") -> dict:
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "entity_type": "financial_instrument",
        "ticker": ticker,
        "exchange": "NASDAQ",
        "isin": None,
        "metadata": {},
    }


def _ann_result(entity_id: UUID, distance: float):
    from knowledge_graph.application.ports.repositories import AnnResult

    return AnnResult(entity_id=entity_id, distance=distance)


# ---------------------------------------------------------------------------
# Core scoring tests
# ---------------------------------------------------------------------------


class TestFinalScore:
    def test_similar_entities_final_score_with_boost(self) -> None:
        """final_score = min(ann_similarity + 0.15, 1.0) when competes_with exists."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        cand_id = uuid4()

        ann = [_ann_result(cand_id, distance=0.20)]  # similarity = 0.80
        competes = {cand_id: (True, 0.72)}

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id, "Apple Inc.", ticker="AAPL"),
            detail_map={cand_id: _entity_dict(cand_id, "Microsoft Corp.", ticker="MSFT")},
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1, 0.2], ann_results=ann)
        relation_repo = _make_relation_repo(competes_map=competes)

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
            )
        )

        assert len(results) == 1
        r = results[0]
        assert r.entity_id == cand_id
        assert r.ann_similarity_score == pytest.approx(0.80)
        assert r.has_competes_with_relation is True
        assert r.competes_with_confidence == pytest.approx(0.72)
        assert r.final_score == pytest.approx(0.80 + 0.15)

    def test_similar_entities_final_score_cap(self) -> None:
        """final_score is capped at 1.0 even when ann_similarity + boost > 1.0."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        cand_id = uuid4()

        ann = [_ann_result(cand_id, distance=0.02)]  # similarity = 0.98
        competes = {cand_id: (True, 0.90)}  # boost = 0.15 → 1.13 → capped at 1.0

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={cand_id: _entity_dict(cand_id, "Near-Identical Corp.")},
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1, 0.2], ann_results=ann)
        relation_repo = _make_relation_repo(competes_map=competes)

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
            )
        )

        assert results[0].final_score == pytest.approx(1.0)

    def test_similar_entities_no_boost_when_no_competes_with(self) -> None:
        """final_score == ann_similarity when there is no competes_with relation."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        cand_id = uuid4()

        ann = [_ann_result(cand_id, distance=0.30)]  # similarity = 0.70
        # No competes_with relation

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={cand_id: _entity_dict(cand_id, "Unrelated Corp.")},
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=ann)
        relation_repo = _make_relation_repo(competes_map={})

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
            )
        )

        assert results[0].final_score == pytest.approx(0.70)
        assert results[0].has_competes_with_relation is False
        assert results[0].competes_with_confidence is None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_similar_entities_entity_not_found(self) -> None:
        """EntityNotFoundError is raised when the query entity does not exist."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase
        from knowledge_graph.domain.errors import EntityNotFoundError

        entity_repo = _make_entity_repo(entity=None)
        embedding_repo = _make_embedding_repo()
        relation_repo = _make_relation_repo()

        with pytest.raises(EntityNotFoundError):
            _run(
                FindSimilarEntitiesUseCase().execute(
                    entity_repo=entity_repo,  # type: ignore[arg-type]
                    embedding_repo=embedding_repo,
                    relation_repo=relation_repo,  # type: ignore[arg-type]
                    entity_id=uuid4(),
                )
            )

    def test_similar_entities_embedding_not_available(self) -> None:
        """EmbeddingNotAvailableError is raised when entity has no fundamentals_ohlcv embedding."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase
        from knowledge_graph.domain.errors import EmbeddingNotAvailableError

        query_id = uuid4()
        entity_repo = _make_entity_repo(entity=_entity_dict(query_id))
        embedding_repo = _make_embedding_repo(embedding=None)  # no embedding
        relation_repo = _make_relation_repo()

        with pytest.raises(EmbeddingNotAvailableError):
            _run(
                FindSimilarEntitiesUseCase().execute(
                    entity_repo=entity_repo,  # type: ignore[arg-type]
                    embedding_repo=embedding_repo,
                    relation_repo=relation_repo,  # type: ignore[arg-type]
                    entity_id=query_id,
                )
            )

    def test_similar_entities_empty_ann_results(self) -> None:
        """Returns empty list when no ANN neighbours are found."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        entity_repo = _make_entity_repo(entity=_entity_dict(query_id))
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=[])
        relation_repo = _make_relation_repo()

        entity_dict, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
            )
        )

        assert results == []
        assert entity_dict["entity_id"] == query_id


# ---------------------------------------------------------------------------
# Filter / sort tests
# ---------------------------------------------------------------------------


class TestFiltersAndSort:
    def test_similar_entities_min_score_filter(self) -> None:
        """Results below min_score are excluded."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        low_id = uuid4()
        high_id = uuid4()

        ann = [
            _ann_result(low_id, distance=0.50),  # similarity = 0.50 → below min_score=0.6
            _ann_result(high_id, distance=0.20),  # similarity = 0.80 → above
        ]

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={
                low_id: _entity_dict(low_id, "Low Similarity Corp."),
                high_id: _entity_dict(high_id, "High Similarity Corp."),
            },
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=ann)
        relation_repo = _make_relation_repo()

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
                min_score=0.6,
            )
        )

        assert len(results) == 1
        assert results[0].entity_id == high_id

    def test_similar_entities_include_competitors_only(self) -> None:
        """include_competitors_only=True excludes non-competitors."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        comp_id = uuid4()
        non_comp_id = uuid4()

        ann = [
            _ann_result(comp_id, distance=0.20),
            _ann_result(non_comp_id, distance=0.25),
        ]
        competes = {comp_id: (True, 0.80)}

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={
                comp_id: _entity_dict(comp_id, "Competitor Corp."),
                non_comp_id: _entity_dict(non_comp_id, "Non-Competitor Corp."),
            },
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=ann)
        relation_repo = _make_relation_repo(competes_map=competes)

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
                include_competitors_only=True,
            )
        )

        assert len(results) == 1
        assert results[0].entity_id == comp_id

    def test_similar_entities_top_k_limits_results(self) -> None:
        """top_k=2 returns at most 2 results even if more pass filters."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        ids = [uuid4() for _ in range(5)]

        ann = [_ann_result(eid, distance=0.1 * (i + 1)) for i, eid in enumerate(ids)]

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={eid: _entity_dict(eid, f"Corp {i}") for i, eid in enumerate(ids)},
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=ann)
        relation_repo = _make_relation_repo()

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
                top_k=2,
            )
        )

        assert len(results) == 2

    def test_similar_entities_sorted_by_final_score_desc(self) -> None:
        """Results are sorted by final_score descending."""
        from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase

        query_id = uuid4()
        near_id = uuid4()
        far_id = uuid4()

        ann = [
            _ann_result(near_id, distance=0.10),  # similarity=0.90
            _ann_result(far_id, distance=0.40),  # similarity=0.60
        ]

        entity_repo = _make_entity_repo(
            entity=_entity_dict(query_id),
            detail_map={
                near_id: _entity_dict(near_id, "Near Corp"),
                far_id: _entity_dict(far_id, "Far Corp"),
            },
        )
        embedding_repo = _make_embedding_repo(embedding=[0.1], ann_results=ann)
        relation_repo = _make_relation_repo()

        _, results = _run(
            FindSimilarEntitiesUseCase().execute(
                entity_repo=entity_repo,  # type: ignore[arg-type]
                embedding_repo=embedding_repo,
                relation_repo=relation_repo,  # type: ignore[arg-type]
                entity_id=query_id,
            )
        )

        assert results[0].final_score >= results[1].final_score
        assert results[0].entity_id == near_id


# ---------------------------------------------------------------------------
# find_competes_with_batch — empty candidates guard
# ---------------------------------------------------------------------------


class TestFindCompetesWithBatch:
    def test_find_competes_with_batch_empty_candidates(self) -> None:
        """find_competes_with_batch returns empty dict when candidate_ids is empty."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository

        session = AsyncMock()
        repo = RelationRepository(session)

        result = _run(repo.find_competes_with_batch(uuid4(), []))

        assert result == {}
        session.execute.assert_not_awaited()
