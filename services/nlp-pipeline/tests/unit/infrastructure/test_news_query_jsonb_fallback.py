"""BP-606 (PLAN-0100 W1 T-W1-01) — JSONB-fallback discovery in entity articles SQL.

Regression coverage for the MSTR canary: documents whose entity lineage
lives ONLY in the denormalised ``chunks.entity_mentions`` JSONB column (with
zero rows in the normalised ``entity_mentions`` table) must still surface
through ``get_entity_articles``. Before BP-606 the LLM saw ``item_count=0``
for MSTR and substituted a different ticker, producing the Q2 HARMFUL fault.

We can't reach Postgres at unit-test scope, so we assert structurally on the
generated SQL text:

  1. The Leg-1 ``entity_mentions``-table SELECT is preserved.
  2. The Leg-2 ``chunks.entity_mentions`` JSONB-containment SELECT is present.
  3. The two legs are joined by ``UNION`` (de-duplicates the doc_id set).
  4. Both legs honour the R35 three-row-class tenant filter.

Combined with the existing tenant-filter test, this is the strongest
unit-level guarantee available without a live Postgres fixture.
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

_NOW = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
_MSTR_ENTITY_ID = uuid4()


class TestEntityArticlesJsonbFallback:
    """BP-606: JSONB-fallback discovery in the entity-articles CTE."""

    def test_sql_preserves_normalised_table_leg(self) -> None:
        """Leg 1 — original ``entity_mentions`` table SELECT must still be present."""
        assert "FROM entity_mentions em" in _ENTITY_ARTICLES_SQL
        assert "em.resolved_entity_id = :entity_id" in _ENTITY_ARTICLES_SQL

    def test_sql_adds_jsonb_containment_leg(self) -> None:
        """Leg 2 — denormalised ``chunks.entity_mentions`` JSONB containment.

        The fix uses ``@> jsonb_build_array(jsonb_build_object('entity_id', ...))``
        so the existing GIN index on ``chunks.entity_mentions`` is consulted.
        """
        assert "FROM chunks c" in _ENTITY_ARTICLES_SQL
        assert "c.entity_mentions @> jsonb_build_array(" in _ENTITY_ARTICLES_SQL
        assert "jsonb_build_object('entity_id', CAST(:entity_id AS TEXT))" in _ENTITY_ARTICLES_SQL

    def test_legs_are_unioned(self) -> None:
        """The two discovery paths must be combined with UNION (de-dupes article_ids)."""
        # Locate the two SELECTs and ensure a UNION sits between them.
        idx_table = _ENTITY_ARTICLES_SQL.find("FROM entity_mentions em")
        idx_union = _ENTITY_ARTICLES_SQL.find("UNION", idx_table)
        idx_jsonb = _ENTITY_ARTICLES_SQL.find("FROM chunks c", idx_union)
        assert idx_table != -1, "missing entity_mentions table leg"
        assert idx_union != -1, "missing UNION between the two legs"
        assert idx_jsonb != -1, "missing chunks JSONB leg"
        assert idx_table < idx_union < idx_jsonb, "legs out of order"

    def test_jsonb_leg_honours_three_row_class_tenant_filter(self) -> None:
        """R35 (PLAN-0097): every tenant query must admit NULL + tenant + PUBLIC sentinel."""
        # Slice from the JSONB leg start to the end of the CTE to scope assertions.
        idx_jsonb = _ENTITY_ARTICLES_SQL.find("FROM chunks c")
        idx_cte_close = _ENTITY_ARTICLES_SQL.find("),", idx_jsonb)
        leg_sql = _ENTITY_ARTICLES_SQL[idx_jsonb:idx_cte_close]
        assert "c.tenant_id IS NULL" in leg_sql, "JSONB leg missing NULL-tenant OR-leg"
        assert "c.tenant_id = CAST(:tenant_id AS UUID)" in leg_sql, "JSONB leg missing real-tenant OR-leg"
        assert "'00000000-0000-0000-0000-000000000000'::uuid" in leg_sql, "JSONB leg missing PUBLIC_TENANT_ID leg"

    @pytest.mark.asyncio
    async def test_get_entity_articles_passes_entity_id_into_jsonb_param(self) -> None:
        """End-to-end (mock-session) check that the same ``:entity_id`` param
        feeds BOTH legs (the table SELECT and the JSONB cast).  A regression
        that splits the param would silently break Leg-2 for every query.
        """
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        repo = SqlaNewsQueryRepo(session)
        await repo.get_entity_articles(
            entity_id=_MSTR_ENTITY_ID,
            start_date=_NOW,
            end_date=_NOW,
            order_by="display_relevance_score",
            limit=20,
            offset=0,
            tenant_id=str(uuid4()),
        )

        session.execute.assert_awaited_once()
        params = session.execute.call_args[0][1]
        # The single ``:entity_id`` value must equal the str(UUID) we passed.
        assert params["entity_id"] == str(_MSTR_ENTITY_ID)
