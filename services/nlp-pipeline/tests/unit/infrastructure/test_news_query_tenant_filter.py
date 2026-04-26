"""Unit tests for F-009 Option B: tenant_id filter in entity articles SQL.

Verifies that:
  1. The _ENTITY_ARTICLES_SQL includes the tenant_id filter clause
  2. SqlaNewsQueryRepo.get_entity_articles passes tenant_id to the query
  3. tenant_id=None is passed through (SQL IS NULL handles it correctly)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import (
    _ENTITY_ARTICLES_SQL,
    SqlaNewsQueryRepo,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
_ENTITY_ID = uuid4()


class TestEntityArticlesTenantFilter:
    """F-009: Verify tenant_id SQL filter is present and parameterised."""

    def test_entity_articles_sql_contains_tenant_filter(self) -> None:
        """The raw SQL must include the tenant_id IS NULL OR tenant_id = :tenant_id clause."""
        assert "em.tenant_id IS NULL" in _ENTITY_ARTICLES_SQL
        assert "CAST(:tenant_id AS UUID)" in _ENTITY_ARTICLES_SQL

    @pytest.mark.asyncio
    async def test_get_entity_articles_passes_tenant_id(self) -> None:
        """SqlaNewsQueryRepo.get_entity_articles passes tenant_id to the SQL execution."""
        session = AsyncMock()
        # Mock execute to return no rows
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlaNewsQueryRepo(session)
        tenant = str(uuid4())
        await repo.get_entity_articles(
            entity_id=_ENTITY_ID,
            start_date=_NOW,
            end_date=_NOW,
            order_by="display_relevance_score",
            limit=20,
            offset=0,
            tenant_id=tenant,
        )

        # Verify execute was called and the params dict includes tenant_id
        session.execute.assert_awaited_once()
        call_args = session.execute.call_args
        params = call_args[0][1]  # Second positional arg is the params dict
        assert params["tenant_id"] == tenant

    @pytest.mark.asyncio
    async def test_get_entity_articles_passes_none_tenant_id(self) -> None:
        """When tenant_id is None, it should still be passed to the query (IS NULL handles it)."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlaNewsQueryRepo(session)
        await repo.get_entity_articles(
            entity_id=_ENTITY_ID,
            start_date=_NOW,
            end_date=_NOW,
            order_by="display_relevance_score",
            limit=20,
            offset=0,
            tenant_id=None,
        )

        session.execute.assert_awaited_once()
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["tenant_id"] is None
