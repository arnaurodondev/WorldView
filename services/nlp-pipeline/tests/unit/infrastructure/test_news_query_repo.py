"""Unit tests for SqlaNewsQueryRepo (PRD-0026 §6.7 Flow C + Flow D)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestSqlaNewsQueryRepoSql:
    """Structural SQL tests — verify CTE shape without hitting a real database."""

    def test_get_top_news_sql_contains_hour_filter(self) -> None:
        """Flow C SQL contains the published_at time-window filter."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _TOP_NEWS_SQL

        assert "published_at >= now() - :hours * interval '1 hour'" in _TOP_NEWS_SQL

    def test_get_top_news_sql_uses_is_null_for_routing_tier(self) -> None:
        """Flow C SQL handles nullable :routing_tier via IS NULL, not bare equality (BP-069)."""
        from nlp_pipeline.infrastructure.nlp_db.repositories.news_query import _TOP_NEWS_SQL

        # Must contain IS NULL check (not just = :routing_tier directly).
        assert ":routing_tier IS NULL" in _TOP_NEWS_SQL

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
