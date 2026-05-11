"""Unit tests for deprecated ArticlePriceImpactRepository (PRD-0026 Wave 3).

The article_price_impacts table was dropped in migration 0009. The repository
is kept as a temporary shim while PriceImpactLabellingWorker is migrated
in Wave 4. Tests validate the shim behavior of the updated class.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.ports.repositories import PriceImpactRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.repositories.price_impact import (
    ArticlePriceImpactRepository,
)

pytestmark = pytest.mark.unit


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestPortIsAbstract:
    def test_price_impact_repo_port_is_abstract(self) -> None:
        """PriceImpactRepositoryPort cannot be instantiated directly."""
        with pytest.raises(TypeError):
            PriceImpactRepositoryPort()  # type: ignore[abstract]


class TestDeprecatedUpsertIsNoop:
    @pytest.mark.asyncio
    async def test_upsert_is_noop(self) -> None:
        """upsert() is a no-op since article_price_impacts table was dropped (migration 0009)."""
        session = _make_session()
        repo = ArticlePriceImpactRepository(session)

        # Should not raise and should not call execute (table no longer exists)
        await repo.upsert(None)  # type: ignore[arg-type]

        session.execute.assert_not_awaited()


class TestDeprecatedGetByArticleIdReturnsNone:
    @pytest.mark.asyncio
    async def test_get_by_article_id_always_returns_none(self) -> None:
        """get_by_article_id() always returns None since table no longer exists."""
        session = _make_session()
        repo = ArticlePriceImpactRepository(session)

        result = await repo.get_by_article_id(uuid.uuid4())

        assert result is None


class TestGetMaxImpactQueriesNewTable:
    @pytest.mark.asyncio
    async def test_get_max_impact_returns_zero_when_no_rows(self) -> None:
        """No windows for doc_id -> Decimal('0.0') (queries article_impact_windows)."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticlePriceImpactRepository(session)

        result = await repo.get_max_impact_for_doc(uuid.uuid4())

        assert result == Decimal("0.0")
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_max_impact_returns_value_from_new_table(self) -> None:
        """Returns Decimal value from article_impact_windows (new table)."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = Decimal("0.6")

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticlePriceImpactRepository(session)

        result = await repo.get_max_impact_for_doc(uuid.uuid4())

        assert result == Decimal("0.6")
