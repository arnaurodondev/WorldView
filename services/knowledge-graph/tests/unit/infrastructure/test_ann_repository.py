"""Unit tests for SqlalchemyEntityEmbeddingANNRepository (PRD-0017 §6.5, Wave B-3).

Tests:
- test_find_nearest_returns_sorted_ann_results
- test_find_nearest_empty_when_no_rows
- test_find_nearest_excludes_entity_id
- test_find_nearest_entity_types_filter_included
- test_similar_entities_no_embedding  (get_embedding returns None for null row)
- test_similar_entities_not_found     (find_nearest returns empty list — no candidates)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(fetchall_return: list | None = None, fetchone_return: object = None) -> AsyncMock:
    """Build a mock AsyncSession whose execute() returns fetchall/fetchone results."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall_return or []
    result.fetchone.return_value = fetchone_return
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# find_nearest
# ---------------------------------------------------------------------------


class TestFindNearest:
    def test_find_nearest_returns_sorted_ann_results(self) -> None:
        """find_nearest() maps DB rows to AnnResult(entity_id, distance) objects."""
        from knowledge_graph.application.ports.repositories import AnnResult
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        entity_a = uuid4()
        entity_b = uuid4()
        session = _make_session(
            fetchall_return=[
                (str(entity_a), 0.12),
                (str(entity_b), 0.37),
            ]
        )
        repo = SqlalchemyEntityEmbeddingANNRepository(session)
        query_vec = [0.1, 0.2, 0.3]

        results = _run(repo.find_nearest(query_vec, view_type="fundamentals_ohlcv", limit=10))

        assert len(results) == 2
        assert isinstance(results[0], AnnResult)
        assert results[0].entity_id == entity_a
        assert results[0].distance == pytest.approx(0.12)
        assert results[1].entity_id == entity_b
        assert results[1].distance == pytest.approx(0.37)
        # Confirm execute was called once
        session.execute.assert_awaited_once()

    def test_similar_entities_not_found(self) -> None:
        """find_nearest() returns empty list when the DB returns no rows.

        This is the 'not found' path: no financial_instrument entities with embeddings
        close enough to qualify as neighbours.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        results = _run(repo.find_nearest([0.1, 0.2], view_type="fundamentals_ohlcv"))

        assert results == []
        session.execute.assert_awaited_once()

    def test_find_nearest_excludes_entity_id(self) -> None:
        """find_nearest() passes exclude_entity_id as a parameter to the query."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        exclude_id = uuid4()
        session = _make_session(fetchall_return=[])
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        _run(repo.find_nearest([0.1], "fundamentals_ohlcv", exclude_entity_id=exclude_id))

        # Verify the exclude_entity_id was passed into the SQL params
        call_args = session.execute.call_args
        params = call_args[0][1]  # positional arg: params dict
        assert "exclude_entity_id" in params
        assert params["exclude_entity_id"] == str(exclude_id)

    def test_find_nearest_entity_types_filter_included(self) -> None:
        """find_nearest() includes entity_types in params when provided."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        _run(
            repo.find_nearest(
                [0.1],
                "fundamentals_ohlcv",
                entity_types=["financial_instrument"],
            )
        )

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert "entity_types" in params
        assert params["entity_types"] == ["financial_instrument"]

    def test_find_nearest_no_extra_params_when_defaults(self) -> None:
        """find_nearest() with default args does not inject exclude or entity_types params."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        _run(repo.find_nearest([0.1], "fundamentals_ohlcv"))

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert "exclude_entity_id" not in params
        assert "entity_types" not in params


# ---------------------------------------------------------------------------
# get_embedding
# ---------------------------------------------------------------------------


class TestGetEmbedding:
    def test_similar_entities_no_embedding(self) -> None:
        """get_embedding() returns None when the embedding column is NULL.

        This is the 'no embedding' path: entity exists but has no
        fundamentals_ohlcv embedding (e.g. non-financial-instrument entity or
        not yet refreshed).  The use case raises EmbeddingNotAvailableError.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        # Row exists but embedding is NULL
        session = _make_session(fetchone_return=(None,))
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        result = _run(repo.get_embedding(uuid4(), "fundamentals_ohlcv"))

        assert result is None

    def test_get_embedding_row_not_found(self) -> None:
        """get_embedding() returns None when no row exists for the entity+view."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        session = _make_session(fetchone_return=None)
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        result = _run(repo.get_embedding(uuid4(), "fundamentals_ohlcv"))

        assert result is None

    def test_get_embedding_returns_float_list(self) -> None:
        """get_embedding() parses pgvector text representation into list[float]."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
            SqlalchemyEntityEmbeddingANNRepository,
        )

        session = _make_session(fetchone_return=("[0.1,0.2,0.3]",))
        repo = SqlalchemyEntityEmbeddingANNRepository(session)

        result = _run(repo.get_embedding(uuid4(), "fundamentals_ohlcv"))

        assert result == pytest.approx([0.1, 0.2, 0.3])


# ---------------------------------------------------------------------------
# Domain object tests
# ---------------------------------------------------------------------------


class TestAnnResult:
    def test_ann_result_construction(self) -> None:
        """AnnResult is a simple dataclass with entity_id and distance."""
        from knowledge_graph.application.ports.repositories import AnnResult

        eid = UUID("00000000-0000-0000-0000-000000000001")
        r = AnnResult(entity_id=eid, distance=0.25)
        assert r.entity_id == eid
        assert r.distance == pytest.approx(0.25)

    def test_ann_result_distance_zero_means_identical(self) -> None:
        """distance=0 represents identical vectors."""
        from knowledge_graph.application.ports.repositories import AnnResult

        r = AnnResult(entity_id=uuid4(), distance=0.0)
        assert r.distance == 0.0


class TestSimilarEntityResult:
    def test_similar_entity_result_is_frozen(self) -> None:
        """SimilarEntityResult is an immutable frozen dataclass."""
        from knowledge_graph.domain.models import SimilarEntityResult

        eid = uuid4()
        r = SimilarEntityResult(
            entity_id=eid,
            canonical_name="Apple Inc.",
            entity_type="financial_instrument",
            ticker="AAPL",
            exchange="NASDAQ",
            ann_similarity_score=0.85,
            competes_with_confidence=0.72,
            final_score=1.0,
            has_competes_with_relation=True,
        )
        with pytest.raises(Exception):  # FrozenInstanceError  # noqa: B017
            r.entity_id = uuid4()  # type: ignore[misc]

    def test_similar_entity_result_no_competitor(self) -> None:
        """SimilarEntityResult with no competes_with relation has None confidence."""
        from knowledge_graph.domain.models import SimilarEntityResult

        r = SimilarEntityResult(
            entity_id=uuid4(),
            canonical_name="Microsoft Corp.",
            entity_type="financial_instrument",
            ticker="MSFT",
            exchange="NASDAQ",
            ann_similarity_score=0.75,
            competes_with_confidence=None,
            final_score=0.75,
            has_competes_with_relation=False,
        )
        assert r.competes_with_confidence is None
        assert not r.has_competes_with_relation
        assert r.final_score == pytest.approx(0.75)


class TestEmbeddingNotAvailableError:
    def test_error_message_contains_entity_id_and_view_type(self) -> None:
        """EmbeddingNotAvailableError message includes entity_id and view_type."""
        from knowledge_graph.domain.errors import EmbeddingNotAvailableError

        eid = UUID("00000000-0000-0000-0000-000000000042")
        exc = EmbeddingNotAvailableError(eid, "fundamentals_ohlcv")
        assert "fundamentals_ohlcv" in str(exc)
        assert "00000000-0000-0000-0000-000000000042" in str(exc)

    def test_error_is_subclass_of_entity_error(self) -> None:
        """EmbeddingNotAvailableError inherits from EntityError."""
        from knowledge_graph.domain.errors import EmbeddingNotAvailableError, EntityError

        assert issubclass(EmbeddingNotAvailableError, EntityError)
