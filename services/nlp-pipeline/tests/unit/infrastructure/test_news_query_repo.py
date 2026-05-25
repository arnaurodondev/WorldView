"""Unit tests for SqlaNewsQueryRepo (PRD-0026 §6.7 Flow C + Flow D)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


class TestSqlaNewsQueryRepoSql:
    """Structural SQL tests — verify CTE shape without hitting a real database."""

    def test_get_top_news_sql_contains_hour_filter(self) -> None:
        """Flow C SQL contains the published_at time-window filter."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _TOP_NEWS_SQL

        assert "published_at >= now() - :hours * interval '1 hour'" in _TOP_NEWS_SQL

    def test_get_top_news_sql_uses_is_null_for_routing_tier(self) -> None:
        """Flow C SQL handles nullable :routing_tier via CAST + IS NULL (BP-069, BP-178).

        asyncpg raises AmbiguousParameterError when a nullable param appears only in
        ':param IS NULL' (no type inference context). Explicit CAST resolves the type.
        """
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _TOP_NEWS_SQL

        # Must use explicit CAST for asyncpg type resolution (BP-178 pattern).
        assert "CAST(:routing_tier AS TEXT) IS NULL" in _TOP_NEWS_SQL

    def test_get_entity_articles_sql_uses_entity_mentions_cte(self) -> None:
        """Flow D SQL uses entity_mentions CTE to scope article IDs by entity."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _ENTITY_ARTICLES_SQL

        assert "entity_mentions" in _ENTITY_ARTICLES_SQL
        assert "entity_article_ids" in _ENTITY_ARTICLES_SQL
        assert ":entity_id" in _ENTITY_ARTICLES_SQL

    def test_get_entity_articles_sql_has_order_by_case(self) -> None:
        """Flow D SQL has conditional ORDER BY for published_at vs display_relevance_score."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _ENTITY_ARTICLES_SQL

        assert ":order_by = 'published_at'" in _ENTITY_ARTICLES_SQL
        assert "display_relevance_score" in _ENTITY_ARTICLES_SQL

    def test_display_score_case_fragment_present_in_both_queries(self) -> None:
        """Both Flow C and Flow D SQL contain the display_relevance_score CASE expression."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import (
            _ENTITY_ARTICLES_SQL,
            _TOP_NEWS_SQL,
        )

        for sql, name in ((_TOP_NEWS_SQL, "top_news"), (_ENTITY_ARTICLES_SQL, "entity_articles")):
            assert "display_relevance_score" in sql, f"Missing display_relevance_score in {name} SQL"
            assert "0.50" in sql, f"Missing full-signal weight 0.50 in {name} SQL"
            assert "0.70" in sql, f"Missing market-only weight 0.70 in {name} SQL"


class TestSqlaNewsQueryRepoGetTopNewsTickers:
    """Tests for the optional tickers filter in SqlaNewsQueryRepo.get_top_news()."""

    def _make_session(self) -> AsyncMock:
        """Build a minimal async-session mock that records execute() calls."""
        # Rows list is empty — we only care about what was passed to execute(), not
        # the returned data.  .all() returns [] so get_top_news() returns ([], 0).
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        return session

    @pytest.mark.asyncio
    async def test_no_tickers_does_not_include_tickers_param(self) -> None:
        """When tickers=None the params dict passed to session.execute() has no 'tickers' key."""

        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import SqlaNewsQueryRepo

        session = self._make_session()
        repo = SqlaNewsQueryRepo(session)

        await repo.get_top_news(
            hours=24,
            limit=10,
            offset=0,
            min_display_score=None,
            routing_tier=None,
            tickers=None,
        )

        # Unpack the positional args passed to session.execute(sql, params).
        _sql_arg, params_arg = session.execute.call_args.args
        assert "tickers" not in params_arg

    @pytest.mark.asyncio
    async def test_tickers_adds_any_clause_and_param(self) -> None:
        """When tickers=["AAPL", "MSFT"]: params["tickers"] is set and SQL contains = ANY(:tickers)."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import SqlaNewsQueryRepo

        session = self._make_session()
        repo = SqlaNewsQueryRepo(session)

        await repo.get_top_news(
            hours=24,
            limit=10,
            offset=0,
            min_display_score=None,
            routing_tier=None,
            tickers=["AAPL", "MSFT"],
        )

        sql_arg, params_arg = session.execute.call_args.args
        # The params dict must carry the tickers list for asyncpg's = ANY() binding.
        assert params_arg["tickers"] == ["AAPL", "MSFT"]
        # The compiled SQL text must contain the ANY clause so the DB filters correctly.
        assert "= ANY(:tickers)" in sql_arg.text
