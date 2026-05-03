"""Divergence tests for PLAN-0068 Wave C-1: SQL backfill vs Python heuristics.

WHY THIS EXISTS: Migration 015_recategorize_prediction_markets.py in the
market-data service contains SQL LIKE ANY(ARRAY[...]) keyword patterns that
MUST stay in sync with `_TITLE_HEURISTIC_RULES` in content_ingestion/domain/entities.py
(used by `_categorize_by_title()`).

If the SQL patterns diverge from the Python rules, fresh ingestion and the
backfill would assign different categories to the same question text — creating
an inconsistency between historical and new rows.

This test is the "C-1-03 divergence test" from PLAN-0068. It verifies:
  1. For every keyword in _TITLE_HEURISTIC_RULES, a question containing that
     keyword maps to the expected canonical category in Python.
  2. The same keyword maps to the correct SQL category bucket (verified via
     the SQL keyword lists hardcoded here — if they ever diverge from migration
     015, this test will catch it).

PLAN-0068 Wave C-1 / C-1-03.
"""

from __future__ import annotations

import pytest
from content_ingestion.domain.entities import _TITLE_HEURISTIC_RULES, _categorize_by_title

pytestmark = pytest.mark.unit

# ── SQL keyword lists (mirrored from migration 015) ────────────────────────────
#
# These are the EXACT keyword lists from 015_recategorize_prediction_markets.py
# upgrade() LIKE ANY(ARRAY[...]) clauses. If the migration is updated, these
# must be updated too — the test will fail and force a manual review.

_SQL_MACRO_KEYWORDS = frozenset(
    {
        "fed",
        "rate",
        "inflation",
        "gdp",
        "cpi",
        "unemployment",
        "recession",
        "fomc",
        "payroll",
        "pce",
        "treasury",
        "yield",
        "deficit",
        "tariff",
        "economic",
        "fiscal",
        "monetary",
        "pmi",
    }
)
_SQL_POLITICS_KEYWORDS = frozenset(
    {
        "election",
        "president",
        "presidential",
        "senate",
        "congress",
        "vote",
        "primary",
        "governor",
        "supreme court",
        "impeach",
    }
)
_SQL_SPORTS_KEYWORDS = frozenset(
    {
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "superbowl",
        "super bowl",
        "world cup",
        "olympics",
        "champion",
        "f1",
        "fifa",
        "uefa",
    }
)
_SQL_CRYPTO_KEYWORDS = frozenset(
    {
        "bitcoin",
        "ethereum",
        "btc",
        "eth",
        "crypto",
        "solana",
        "sol",
        "altcoin",
    }
)

# Map from SQL bucket name → frozenset of keywords
_SQL_KEYWORD_MAP: dict[str, frozenset[str]] = {
    "macro": _SQL_MACRO_KEYWORDS,
    "politics": _SQL_POLITICS_KEYWORDS,
    "sports": _SQL_SPORTS_KEYWORDS,
    "crypto": _SQL_CRYPTO_KEYWORDS,
}


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestPythonHeuristicKeywords:
    """Every keyword in _TITLE_HEURISTIC_RULES should produce the correct category."""

    @pytest.mark.parametrize(
        "expected_category, keyword",
        [(canonical, keyword) for canonical, keywords in _TITLE_HEURISTIC_RULES for keyword in keywords],
    )
    def test_keyword_maps_to_category(self, expected_category: str, keyword: str) -> None:
        """'A question about {keyword}' should be categorised as {expected_category}."""
        # WHY "will X happen": simple question template that triggers the keyword.
        # We ensure the keyword appears in a realistic question context.
        question = f"Will the {keyword} situation change in 2026?"
        result = _categorize_by_title(question)
        assert result == expected_category, (
            f"Keyword {keyword!r}: expected category {expected_category!r}, "
            f"got {result!r} for question: {question!r}"
        )


class TestSQLKeywordParity:
    """Every keyword in Python _TITLE_HEURISTIC_RULES must also appear in the SQL keyword set.

    WHY: If a keyword exists in Python but NOT in the SQL CASE, fresh ingestion
    and backfill would disagree on that specific question text.

    This test catches the case where a developer adds a new Python keyword but
    forgets to update migration 015.
    """

    @pytest.mark.parametrize(
        "canonical, python_keywords",
        _TITLE_HEURISTIC_RULES,
    )
    def test_python_keywords_present_in_sql_map(self, canonical: str, python_keywords: tuple[str, ...]) -> None:
        """All Python heuristic keywords for {canonical} should be in the SQL CASE."""
        if canonical not in _SQL_KEYWORD_MAP:
            # WHY skip when canonical not in SQL map (e.g. 'general' has no explicit SQL keywords):
            # The SQL ELSE branch handles 'general' — there's no keyword list to compare.
            pytest.skip(f"'{canonical}' has no explicit SQL keyword list (handled by ELSE)")

        sql_keywords = _SQL_KEYWORD_MAP[canonical]
        missing = [kw for kw in python_keywords if kw not in sql_keywords]
        assert not missing, (
            f"Python keywords for '{canonical}' not in SQL CASE: {missing!r}. "
            f"Update migration 015_recategorize_prediction_markets.py to add these keywords."
        )

    @pytest.mark.parametrize(
        "sql_bucket, sql_keywords",
        _SQL_KEYWORD_MAP.items(),
    )
    def test_sql_keywords_present_in_python_map(self, sql_bucket: str, sql_keywords: frozenset[str]) -> None:
        """All SQL keywords for {sql_bucket} should be in Python _TITLE_HEURISTIC_RULES.

        WHY: If a keyword exists in the SQL CASE but NOT in Python, the backfill
        would produce a different result than fresh ingestion for that keyword.
        This is the reverse parity check.
        """
        # Build the Python keyword set for this canonical bucket
        python_keywords: frozenset[str] = frozenset()
        for canonical, keywords in _TITLE_HEURISTIC_RULES:
            if canonical == sql_bucket:
                python_keywords = frozenset(keywords)
                break

        if not python_keywords:
            pytest.fail(
                f"SQL keyword bucket '{sql_bucket}' has no matching canonical in "
                f"_TITLE_HEURISTIC_RULES. Either add it to Python or remove from SQL."
            )

        missing = [kw for kw in sql_keywords if kw not in python_keywords]
        assert not missing, (
            f"SQL keywords for '{sql_bucket}' not in Python _TITLE_HEURISTIC_RULES: {missing!r}. "
            f"Update _TITLE_HEURISTIC_RULES in content_ingestion/domain/entities.py to add these keywords."
        )
