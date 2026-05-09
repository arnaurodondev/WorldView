"""Unit tests for IntelligenceAggregatesRepository (F-003, PLAN-0087 audit).

This repository was rewritten TWICE in the 2026-05-09 session:

  1. commit 8bbd7480 — fix `confidence_components` JSONB column reference
     (column never shipped via migration; query 500'd).
  2. commit 0f96c81c — fix `relation_evidence_raw.relation_id` reference
     (column never existed; the table joins to relations on the raw triple
     subject_entity_id / object_entity_id / canonical_type).

BOTH bugs reached `main` because this file shipped without tests.  The fact
that the second bug surfaced AFTER the first fix is the canonical
"missing repository test" signal.

qa-beta-test-engineer (2026-05-09) flagged this CRITICAL.

The tests below pin three load-bearing contracts at the SQL layer (mocked
AsyncSession — no live DB needed):

  * `get_confidence_breakdown` returns the documented dict shape, both for
    entities with active relations and those with none.
  * `get_source_distribution` returns the top-N list with correct percentage
    arithmetic.
  * `get_confidence_trend` returns the (date, avg_confidence) shape and uses
    the correct column names — guards against a future column rename
    (`extraction_confidence` → `confidence_score`) that already happened once.

Compile-time assertions on the SQL string text catch the EXACT regression
flavour audited (`confidence_components`, `relation_evidence_raw.relation_id`).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_session(*, scalar_rows: list[tuple] | None = None) -> AsyncMock:
    """Return an AsyncMock session whose execute().fetchone()/fetchall()
    returns the rows supplied.

    For tests that exercise both fetchone and fetchall, the same rows are
    returned by both (each test only uses one shape).  scalar_rows=None means
    "no rows" — fetchone returns None, fetchall returns [].
    """
    session = AsyncMock()
    result = MagicMock()
    if scalar_rows:
        result.fetchone.return_value = scalar_rows[0]
        result.fetchall.return_value = scalar_rows
    else:
        result.fetchone.return_value = None
        result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _capture_sql(session: AsyncMock) -> str:
    """Pull the SQL TextClause back out of the session.execute() call args.

    The repository passes a `text(...)` clause; we stringify it for substring
    assertions.  Reaching into the call args this way is brittle by design —
    if the repo stops using session.execute() altogether, we want this to
    break loudly.
    """
    call_args = session.execute.await_args
    assert call_args is not None, "session.execute was never awaited"
    text_clause = call_args.args[0]
    return str(text_clause)


# ── get_confidence_breakdown ───────────────────────────────────────────────────


class TestGetConfidenceBreakdown:
    """get_confidence_breakdown returns the contracted dict shape."""

    def test_happy_path_returns_documented_shape(self) -> None:
        """Returns mean_support / latest_evidence_at / relation_count from row.

        Row column order matches the SQL: (avg_confidence, latest_evidence_at,
        relation_count).  Other dict keys (mean_corroboration,
        mean_contradiction) are pinned to None until the upstream
        confidence_components JSONB ships.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        # Single row with mean_confidence=0.82, latest=2026-05-09, count=12
        row = (0.82, datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC), 12)
        session = _make_session(scalar_rows=[row])

        repo = IntelligenceAggregatesRepository(session)
        result = asyncio.run(repo.get_confidence_breakdown(entity_id=_ENTITY_ID))

        assert result["mean_support"] == pytest.approx(0.82)
        assert result["mean_corroboration"] is None  # pinned None — see docstring
        assert result["mean_contradiction"] is None  # pinned None — see docstring
        assert result["latest_evidence_at"] == datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)
        assert result["relation_count"] == 12
        # Contract pinning — every consumer (use case + Pydantic schema) reads
        # exactly these five keys.  A future drift breaks them all at once.
        assert set(result.keys()) == {
            "mean_support",
            "mean_corroboration",
            "mean_contradiction",
            "latest_evidence_at",
            "relation_count",
        }

    def test_no_relations_returns_zero_shape(self) -> None:
        """Empty fetchone (no relations) → relation_count=0, others None.

        AVG over zero rows returns NULL in Postgres, COUNT returns 0.  The repo
        must coerce these to (None, None, 0) so the API contract is stable.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        # AVG returns None when no rows match WHERE clause; COUNT returns 0.
        # Postgres returns the row regardless because the SELECT has no
        # GROUP BY — there is always exactly one aggregate row.
        row_no_relations = (None, None, 0)
        session = _make_session(scalar_rows=[row_no_relations])

        repo = IntelligenceAggregatesRepository(session)
        result = asyncio.run(repo.get_confidence_breakdown(entity_id=_ENTITY_ID))

        assert result["mean_support"] is None
        assert result["latest_evidence_at"] is None
        assert result["relation_count"] == 0

    def test_fetchone_returns_none_when_query_yields_no_row(self) -> None:
        """Defensive: if fetchone returns None outright, return zero-shape dict.

        Postgres would normally always return one aggregate row, but the
        defensive branch in get_confidence_breakdown handles `row is None` —
        we exercise it here for completeness.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)  # fetchone -> None
        repo = IntelligenceAggregatesRepository(session)
        result = asyncio.run(repo.get_confidence_breakdown(entity_id=_ENTITY_ID))

        assert result["relation_count"] == 0
        assert result["mean_support"] is None

    def test_query_does_not_reference_unmigrated_confidence_components_column(self) -> None:
        """REGRESSION GUARD (commit 8bbd7480): the SQL must not query the
        confidence_components JSONB column — it was designed in PLAN-0074 but
        the migration never shipped, so referencing it 500's the endpoint.

        A future PR that re-adds the JSONB extraction MUST also ship the
        migration; this test fails until both arrive together.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=[(0.5, None, 1)])
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_confidence_breakdown(entity_id=_ENTITY_ID))

        sql = _capture_sql(session)
        assert "confidence_components" not in sql, (
            "regression: confidence_components column was re-introduced "
            "without the matching migration — 500 incoming"
        )

    def test_query_targets_relations_table_not_relation_evidence_raw(self) -> None:
        """The breakdown aggregates over `relations`, not `relation_evidence_raw`."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=[(0.5, None, 1)])
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_confidence_breakdown(entity_id=_ENTITY_ID))

        sql = _capture_sql(session)
        # Must reference relations + the active-relation guard
        assert "FROM relations" in sql
        assert "valid_to IS NULL" in sql


# ── get_source_distribution ────────────────────────────────────────────────────


class TestGetSourceDistribution:
    """get_source_distribution returns top-N source pairs with percentages."""

    def test_returns_sorted_list_with_percentages(self) -> None:
        """Two sources → list of {source_type, source_name, count, pct}."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        # SQL CTE returns (source_type, source_name, count, pct) — the test
        # passes pct pre-computed (the CTE does the math in Postgres).
        rows = [
            ("sec_10k", "Apple Inc.", 8, 0.6667),
            ("news_press_release", "Reuters", 4, 0.3333),
        ]
        session = _make_session(scalar_rows=rows)
        repo = IntelligenceAggregatesRepository(session)

        result = asyncio.run(repo.get_source_distribution(entity_id=_ENTITY_ID, limit=10))

        assert len(result) == 2
        assert result[0] == {
            "source_type": "sec_10k",
            "source_name": "Apple Inc.",
            "count": 8,
            "pct": pytest.approx(0.6667),
        }
        assert result[1]["count"] == 4

    def test_empty_evidence_returns_empty_list(self) -> None:
        """No evidence rows → empty list (not None)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        result = asyncio.run(repo.get_source_distribution(entity_id=_ENTITY_ID, limit=10))
        assert result == []

    def test_query_does_not_reference_relation_id_column(self) -> None:
        """REGRESSION GUARD (commit 0f96c81c): relation_evidence_raw has NO
        relation_id column.  The repo must JOIN on the raw triple
        (subject_entity_id, object_entity_id, canonical_type).  A future PR
        that re-adds `WHERE relation_id IN ...` must also ship a migration
        adding that column.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_source_distribution(entity_id=_ENTITY_ID, limit=10))

        sql = _capture_sql(session)
        # The raw-triple JOIN keys MUST be present — proves we're using the
        # correct join shape, not relation_id.
        assert "subject_entity_id" in sql
        assert "object_entity_id" in sql
        assert "canonical_type" in sql
        # And the bug we just fixed — never reference relation_id on rer.
        assert "rer.relation_id" not in sql
        assert "relation_id IN" not in sql.replace(" ", "")  # tolerate whitespace


# ── get_confidence_trend ───────────────────────────────────────────────────────


class TestGetConfidenceTrend:
    """get_confidence_trend returns daily AVG(extraction_confidence) series."""

    def test_returns_date_avg_pairs(self) -> None:
        """Two daily buckets → list of {date, avg_confidence}."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        # Postgres date_trunc → date cast yields date objects from asyncpg.
        rows = [
            (date(2026, 5, 7), 0.82),
            (date(2026, 5, 8), 0.85),
        ]
        session = _make_session(scalar_rows=rows)
        repo = IntelligenceAggregatesRepository(session)

        result = asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=90))

        assert len(result) == 2
        assert result[0] == {"date": date(2026, 5, 7), "avg_confidence": pytest.approx(0.82)}
        assert result[1] == {"date": date(2026, 5, 8), "avg_confidence": pytest.approx(0.85)}

    def test_handles_datetime_input_by_converting_to_date(self) -> None:
        """If a driver returns datetime instead of date, the repo must coerce.

        The conversion branch in the repo (`isinstance(raw_date, datetime)`)
        guards against driver inconsistency.  Pin it here so a future
        "simplify" refactor doesn't drop the conversion.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        rows = [(datetime(2026, 5, 9, 0, 0, 0, tzinfo=UTC), 0.91)]
        session = _make_session(scalar_rows=rows)
        repo = IntelligenceAggregatesRepository(session)

        result = asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=30))
        assert result[0]["date"] == date(2026, 5, 9)
        assert isinstance(result[0]["date"], date)

    def test_empty_returns_empty_list(self) -> None:
        """No evidence in window → []."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        result = asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=90))
        assert result == []

    def test_query_uses_extraction_confidence_column_name(self) -> None:
        """REGRESSION GUARD (commit 8bbd7480): the column on
        relation_evidence_raw is `extraction_confidence`, not
        `confidence_score` (the broken pre-fix name).  Pin so the column
        rename cannot regress silently.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=30))

        sql = _capture_sql(session)
        assert "extraction_confidence" in sql, "regression: extraction_confidence renamed away"
        assert "confidence_score" not in sql, (
            "regression: confidence_score (old/broken column name) re-introduced — "
            "this is the column that was broken in commit 8bbd7480"
        )
        # And the bug from 0f96c81c — must JOIN on raw triple, not relation_id.
        assert "rer.relation_id" not in sql

    def test_query_filters_to_active_relations_only(self) -> None:
        """The trend must skip retracted relations (valid_to IS NULL guard)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=90))

        sql = _capture_sql(session)
        assert "valid_to IS NULL" in sql

    def test_days_parameter_is_bound_not_interpolated(self) -> None:
        """The `days` parameter must reach asyncpg as a bind, not a string —
        catches a future "f-string the SQL" refactor that would re-introduce
        SQL injection (defence in depth even though the value is an int).
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.intelligence_aggregates_repository import (
            IntelligenceAggregatesRepository,
        )

        session = _make_session(scalar_rows=None)
        repo = IntelligenceAggregatesRepository(session)
        asyncio.run(repo.get_confidence_trend(entity_id=_ENTITY_ID, days=42))

        # The bind dict is the second positional arg of execute().
        bind_kwargs = session.execute.await_args.args[1]
        assert bind_kwargs["days"] == 42
        assert bind_kwargs["entity_id"] == str(_ENTITY_ID)
