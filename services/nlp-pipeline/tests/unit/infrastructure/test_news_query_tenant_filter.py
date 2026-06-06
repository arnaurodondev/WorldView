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

    def test_entity_articles_sql_includes_public_tenant_sentinel(self) -> None:
        """R35 (PLAN-0097 W4 T-W4-01): the SQL must include the PUBLIC_TENANT_ID
        sentinel OR-leg so PLAN-0096 W4 fallback rows are visible to every
        authenticated tenant — not just anonymous callers.
        """
        # The sentinel must appear as a literal in the SQL so even tenants whose
        # UUID differs from 00000000-... still see PUBLIC_TENANT_ID rows.
        assert "'00000000-0000-0000-0000-000000000000'::uuid" in _ENTITY_ARTICLES_SQL

    @pytest.mark.asyncio
    async def test_get_entity_articles_filter_admits_all_three_row_classes(self) -> None:
        """End-to-end (mock-session) assertion that the executed SQL admits:
            1) NULL-tenant legacy rows,
            2) rows owned by the requesting tenant,
            3) rows owned by the PUBLIC_TENANT_ID sentinel.

        We can't reach Postgres here; instead we assert on the prepared SQL
        text that all three OR-legs are present in a single WHERE-clause.
        Combined with the asserting unit test above (per-leg substrings), this
        is the strongest unit-level guarantee available without an integration
        test against a live ``intelligence_db``.
        """
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
            tenant_id=str(uuid4()),
        )

        # Inspect the SQL text actually passed to session.execute and assert
        # all three OR-legs land in the SAME boolean grouping (no leg dropped
        # in a later refactor).
        sql_text = str(session.execute.call_args[0][0])
        # Each leg must appear, and they must be joined by OR within a single
        # AND-clause. We assert the three substrings sequentially appear in order.
        idx_null = sql_text.find("em.tenant_id IS NULL")
        idx_tenant = sql_text.find("CAST(:tenant_id AS UUID)")
        idx_public = sql_text.find("'00000000-0000-0000-0000-000000000000'::uuid")
        assert idx_null != -1, "missing NULL-tenant OR-leg"
        assert idx_tenant != -1, "missing real-tenant OR-leg"
        assert idx_public != -1, "missing PUBLIC_TENANT_ID OR-leg (R35)"
        # Ordering: NULL → tenant → public (matches the source code grouping).
        assert idx_null < idx_tenant < idx_public

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
