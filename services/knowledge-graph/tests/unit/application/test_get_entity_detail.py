"""Unit tests for GetEntityDetailUseCase (PRD-0073 §9.6).

Covers F-Q13 of the PLAN-0073 QA report — verifies that the use case calls
``CanonicalEntityRepository.get_by_id()`` (which DOES exist on the repo, so
the QA-flagged AttributeError concern is unfounded — see VERIFICATION below).

VERIFICATION (PLAN-0073 F-Q13):
    Read of services/knowledge-graph/src/.../intelligence_db/repositories/
    canonical_entity.py confirms ``get_by_id(entity_id: UUID) -> CanonicalEntity | None``
    is defined (line 86).  The use case is therefore correct as-shipped.

This test suite still builds an end-to-end test that constructs the real
``CanonicalEntityRepository`` (NOT mocked) on top of a session whose execute
returns no rows.  Were ``get_by_id`` ever removed by a future refactor, this
test would surface it as an AttributeError immediately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from knowledge_graph.application.use_cases.get_entity_detail import (
    GetEntityDetailUseCase,
)
from knowledge_graph.domain.models import CanonicalEntity
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000001")


# ---------------------------------------------------------------------------
# Use case behaviour with a mocked repo
# ---------------------------------------------------------------------------


class TestUseCaseWithMockedRepo:
    async def test_calls_repo_get_by_id_with_entity_id(self) -> None:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)
        uc = GetEntityDetailUseCase(repo)

        await uc.execute(_ENTITY_ID)

        repo.get_by_id.assert_awaited_once_with(_ENTITY_ID)

    async def test_returns_none_when_repo_returns_none(self) -> None:
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=None)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)
        assert result is None

    async def test_returns_canonical_entity_when_found(self) -> None:
        expected = CanonicalEntity(
            entity_id=_ENTITY_ID,
            canonical_name="Apple Inc.",
            entity_type="financial_instrument",
            ticker="AAPL",
            description="A consumer electronics maker.",
            data_completeness=0.85,
            enrichment_attempts=1,
        )
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=expected)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)
        assert result is expected
        assert result is not None
        assert result.canonical_name == "Apple Inc."
        assert result.description == "A consumer electronics maker."


# ---------------------------------------------------------------------------
# End-to-end with a real CanonicalEntityRepository (no mock spec)
# ---------------------------------------------------------------------------


class TestUseCaseEndToEndWithRealRepo:
    """Construct the real repository — surfaces AttributeError if get_by_id is removed."""

    async def test_real_repo_get_by_id_returns_none_when_no_rows(self) -> None:
        """The repo's get_by_id must execute SQL and return None when fetchone()
        returns None.  This tests the full path without mocking the repo class."""
        # Mock the AsyncSession only — keep the real repository class.
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result_mock)

        repo = CanonicalEntityRepository(session)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)

        assert result is None
        # Confirm the SELECT actually ran.
        session.execute.assert_awaited_once()

    async def test_real_repo_get_by_id_returns_entity_when_row_present(self) -> None:
        """End-to-end: the real repo maps a DB row tuple → CanonicalEntity correctly.

        The column order MUST match the repo's SELECT:
            entity_id, canonical_name, entity_type, ticker, isin, exchange,
            metadata, enrichment_attempts, description, data_completeness,
            enriched_at
        """
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone = MagicMock(
            return_value=(
                str(_ENTITY_ID),
                "Apple Inc.",
                "financial_instrument",
                "AAPL",
                None,  # isin
                "NASDAQ",
                {"sector": "Technology"},  # metadata jsonb
                1,  # enrichment_attempts
                "A consumer electronics maker.",
                0.85,
                None,  # enriched_at
                None,  # health_score (migration 0031)
            )
        )
        session.execute = AsyncMock(return_value=result_mock)

        repo = CanonicalEntityRepository(session)
        uc = GetEntityDetailUseCase(repo)

        result = await uc.execute(_ENTITY_ID)

        assert result is not None
        assert result.entity_id == _ENTITY_ID
        assert result.canonical_name == "Apple Inc."
        assert result.entity_type == "financial_instrument"
        assert result.ticker == "AAPL"
        assert result.exchange == "NASDAQ"
        assert result.metadata == {"sector": "Technology"}
        assert result.description == "A consumer electronics maker."
        assert result.data_completeness == 0.85

    def test_get_by_id_method_exists_on_repo(self) -> None:
        """Compile-time guard against accidental method removal (F-Q13)."""
        assert hasattr(CanonicalEntityRepository, "get_by_id")
        # Must be async — use-case awaits it.
        import inspect

        assert inspect.iscoroutinefunction(CanonicalEntityRepository.get_by_id)
